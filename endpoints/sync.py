"""
Conversation Sync (one-way push) endpoints.

This is an intentionally isolated blueprint implementing the feature described in
``documentation/features/conversation_sync``:

- ``POST /sync/upload`` (RECEIVER): token-authenticated, session-less upsert of a
  serialized conversation pushed from another instance. This is the first and
  only token-authenticated route in the codebase; it is kept deliberately small
  and self-contained. The endpoint 404s entirely when the feature is unconfigured
  so it can never become an accidental unauthenticated surface.
- ``POST /sync_conversation/<conversation_id>`` (SENDER): normal session-auth
  route that serializes a local conversation and POSTs it to the configured
  remote's ``/sync/upload``.
- ``GET /sync/config`` (SENDER): tiny boolean so the UI can gate the menu item.

Configuration is read into ``app.config`` in ``server.create_app`` and referenced
here via ``current_app.config``:
- Receiver: ``SYNC_UPLOAD_TOKEN`` (shared secret; endpoint disabled if unset),
  ``SYNC_UPLOAD_USER_EMAIL`` (target-side owner of all synced conversations).
- Sender: ``SYNC_REMOTE_URL``, ``SYNC_REMOTE_TOKEN``, optional ``SYNC_HOST_LABEL``.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import os

import requests
from flask import Blueprint, current_app, jsonify, request, session

from Conversation import Conversation
from database.conversations import addConversation
from database.workspaces import createWorkspace, load_workspaces_for_user
from endpoints.auth import login_required
from endpoints.request_context import get_conversation_with_keys
from endpoints.responses import json_error
from endpoints.session_utils import get_session_identity
from endpoints.state import get_state
from endpoints.utils import keyParser
from extensions import limiter


sync_bp = Blueprint("sync", __name__)
logger = logging.getLogger(__name__)

# Reject payloads larger than this (checked before JSON parsing via content_length).
MAX_SYNC_BYTES = 25 * 1024 * 1024
SYNC_VERSION = 1
SYNC_WORKSPACE_NAME = "sync"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _target_conversation_id(source_user_id: str, source_cid: str, owner_email: str) -> str:
    """
    Deterministic target conversation id, so re-syncing the same source
    conversation upserts the same target copy (no duplicates, no mapping table).

    Keyed on ``source_user_id + '|' + source_cid`` (collision-safe across hosts
    and source users); prefixed with the owner + ``sync`` for recognisability.
    """
    digest = hashlib.sha256(
        f"{source_user_id}|{source_cid}".encode("utf-8")
    ).hexdigest()[:24]
    return f"{owner_email}_sync_{digest}"


def _resolve_or_create_sync_workspace(users_dir: str, owner_email: str, domain: str) -> str:
    """
    Return the workspace_id of the (case-sensitive) ``sync`` workspace for
    ``(owner_email, domain)``, creating it if absent. No get-by-name helper
    exists, so we scan the user's workspaces for this domain.
    """
    workspaces = load_workspaces_for_user(
        users_dir=users_dir, user_email=owner_email, domain=domain
    )
    for ws in workspaces:
        if ws.get("workspace_name") == SYNC_WORKSPACE_NAME:
            return ws["workspace_id"]

    workspace_id = f"sync_{owner_email}_{domain}"
    createWorkspace(
        users_dir=users_dir,
        user_email=owner_email,
        workspace_id=workspace_id,
        domain=domain,
        workspace_name=SYNC_WORKSPACE_NAME,
        workspace_color=None,
    )
    return workspace_id


def _apply_payload_fields(conv: Conversation, payload: dict) -> None:
    """
    Overwrite the conversation's fields from a validated sync payload.

    ``set_field(..., overwrite=True)`` REPLACES (not appends) for messages,
    memory, artefacts, artefact_message_links and conversation_settings (verified
    against Conversation._set_field_sqlite), so this cleanly mirrors the source.
    """
    conv.set_field("memory", payload.get("memory") or {}, overwrite=True)
    conv.set_field("messages", payload.get("messages") or [], overwrite=True)
    conv.set_field("artefacts", payload.get("artefact_metadata") or [], overwrite=True)
    conv.set_field(
        "artefact_message_links", payload.get("artefact_message_links") or {}, overwrite=True
    )

    # Settings: carry the source settings, then stamp provenance for display + no-op checks.
    settings = dict(payload.get("conversation_settings") or {})
    source = dict(payload.get("source") or {})
    source["content_hash"] = payload.get("content_hash", "")
    settings["sync_source"] = source
    docs = payload.get("uploaded_documents") or []
    if docs:
        # v1: display-only; do NOT populate uploaded_documents_list (would break refs).
        settings["sync_source_documents"] = docs
    conv.set_field("conversation_settings", settings, overwrite=True)


def _write_artefact_files(conv: Conversation, payload: dict) -> None:
    """Replace the target artefacts/ dir contents with the inlined payload files."""
    art_dir = conv.artefacts_path  # ensures dir exists
    inlined = payload.get("artefacts") or []
    for item in inlined:
        rel = item.get("path")
        b64 = item.get("b64")
        if not rel or b64 is None:
            continue
        # Guard against path traversal: only allow a bare filename.
        rel = os.path.basename(rel)
        try:
            with open(os.path.join(art_dir, rel), "wb") as fh:
                fh.write(base64.b64decode(b64))
        except Exception as e:  # pragma: no cover - defensive
            logger.warning("sync: failed writing artefact %s: %s", rel, e)


def _reindex(conv: Conversation) -> None:
    """Best-effort cross-conversation search index update (mirrors clone/edit paths)."""
    try:
        idx = getattr(conv, "_cross_conv_index", None)
        if idx:
            idx.index_conversation(conv)
    except Exception:
        pass


# ---------------------------------------------------------------------------
# Receiver: POST /sync/upload  (token auth, no session)
# ---------------------------------------------------------------------------

@sync_bp.route("/sync/upload", methods=["POST"])
@limiter.limit("30 per minute")
def sync_upload():
    """Receive and upsert a conversation pushed from another instance."""
    token = current_app.config.get("SYNC_UPLOAD_TOKEN")
    owner_email = current_app.config.get("SYNC_UPLOAD_USER_EMAIL")

    # 1. Feature gate: unset token -> feature disabled entirely (404).
    if not token or not owner_email:
        return json_error("Not found", status=404, code="sync_disabled")

    # 2. Size cap BEFORE parsing (cheap DoS guard on a public endpoint).
    if request.content_length is not None and request.content_length > MAX_SYNC_BYTES:
        return json_error("Payload too large", status=413, code="sync_too_large")

    # 3. Bearer auth (constant-time compare).
    auth = request.headers.get("Authorization", "")
    presented = auth[7:] if auth.startswith("Bearer ") else ""
    if not presented or not hmac.compare_digest(presented, token):
        return json_error("Unauthorized", status=401, code="sync_unauthorized")

    # 4. Validate payload early.
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return json_error("Invalid JSON body", status=400, code="sync_bad_body")
    if payload.get("sync_version") != SYNC_VERSION:
        return json_error(
            f"Unsupported sync_version (expected {SYNC_VERSION})",
            status=400,
            code="sync_bad_version",
        )
    source = payload.get("source") or {}
    source_cid = source.get("conversation_id")
    source_user = source.get("user_id") or ""
    domain = payload.get("domain")
    if not source_cid or not domain or not isinstance(payload.get("messages"), list):
        return json_error("Missing source.conversation_id / domain / messages", status=400,
                          code="sync_bad_payload")

    state = get_state()
    target_cid = _target_conversation_id(source_user, source_cid, owner_email)
    target_dir = os.path.join(state.conversation_folder, target_cid)
    updated = os.path.isdir(target_dir)

    # Evict any stale cached object before we mutate storage.
    try:
        if target_cid in state.conversation_cache:
            del state.conversation_cache[target_cid]
    except Exception:
        pass

    try:
        if updated:
            conv = Conversation.load_local(target_dir)
            if conv is None:
                # Folder exists but is unreadable; recreate fresh.
                conv = Conversation(owner_email, None, state.conversation_folder, target_cid, domain)
                updated = False
        else:
            conv = Conversation(owner_email, None, state.conversation_folder, target_cid, domain)

        conv._cross_conv_index = getattr(state, "cross_conversation_index", None)
        conv.domain = domain

        _apply_payload_fields(conv, payload)
        _write_artefact_files(conv, payload)
        conv.save_local()

        if not updated:
            sync_ws_id = _resolve_or_create_sync_workspace(state.users_dir, owner_email, domain)
            ok = addConversation(
                owner_email, target_cid, workspace_id=sync_ws_id, domain=domain,
                users_dir=state.users_dir,
            )
            if not ok:
                # Ops must ensure SYNC_UPLOAD_USER_EMAIL exists; surface clearly.
                return json_error(
                    "Failed to register conversation for target user "
                    "(does SYNC_UPLOAD_USER_EMAIL exist on this instance?)",
                    status=500, code="sync_register_failed",
                )

        state.conversation_cache[target_cid] = conv
        _reindex(conv)
    except Exception as e:
        logger.exception("sync upload failed for source cid=%s", source_cid)
        return json_error(f"Sync import failed: {e}", status=500, code="sync_import_error")

    logger.info(
        "sync upload ok: source_cid=%s target_cid=%s updated=%s messages=%d",
        source_cid, target_cid, updated, len(payload.get("messages") or []),
    )
    return jsonify({"status": "ok", "target_conversation_id": target_cid, "updated": updated})


# ---------------------------------------------------------------------------
# Sender: POST /sync_conversation/<cid>  (session auth)
# ---------------------------------------------------------------------------

@sync_bp.route("/sync_conversation/<conversation_id>", methods=["POST"])
@limiter.limit("25 per minute")
@login_required
def sync_conversation(conversation_id: str):
    """Serialize a local conversation and push it to the configured remote."""
    remote_url = current_app.config.get("SYNC_REMOTE_URL")
    remote_token = current_app.config.get("SYNC_REMOTE_TOKEN")
    host_label = current_app.config.get("SYNC_HOST_LABEL") or ""

    if not remote_url or not remote_token:
        return json_error("Sync not configured on this server", status=400,
                          code="sync_not_configured")

    state = get_state()
    keys = keyParser(session)

    if conversation_id not in state.conversation_cache:
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)
    payload = conversation.export_sync_payload(host_label=host_label)
    payload.pop("skipped_artefacts", None)  # advisory-only; not part of the wire schema

    force = request.args.get("force") in ("1", "true", "yes")
    content_hash = payload.get("content_hash", "")

    # No-op optimisation: skip the HTTP call when nothing changed since last sync.
    settings = conversation.get_conversation_settings()
    last = settings.get("last_sync") or {}
    if (not force and last.get("url") == remote_url
            and last.get("content_hash") == content_hash):
        return jsonify({"status": "ok", "skipped": True,
                        "target_conversation_id": last.get("target_conversation_id")})

    try:
        resp = requests.post(
            f"{remote_url.rstrip('/')}/sync/upload",
            json=payload,
            headers={"Authorization": f"Bearer {remote_token}"},
            timeout=60,
        )
    except requests.RequestException as e:
        return json_error(f"Could not reach remote: {e}", status=502, code="sync_unreachable")

    if resp.status_code // 100 != 2:
        # Surface the remote's message to the browser (mapped to a 4xx/502).
        try:
            remote_msg = resp.json().get("message", resp.text)
        except Exception:
            remote_msg = resp.text
        status = resp.status_code if resp.status_code in (400, 401, 404, 413) else 502
        return json_error(f"Remote rejected sync: {remote_msg}", status=status,
                          code="sync_remote_error")

    data = resp.json()
    target_cid = data.get("target_conversation_id")

    # Record last_sync for the no-op check (merge into settings, don't clobber).
    settings["last_sync"] = {
        "url": remote_url,
        "content_hash": content_hash,
        "target_conversation_id": target_cid,
        "at": payload["source"]["exported_at"],
    }
    conversation.set_field("conversation_settings", settings, overwrite=True)
    conversation.save_local()

    return jsonify({
        "status": "ok",
        "skipped": False,
        "updated": data.get("updated", False),
        "target_conversation_id": target_cid,
    })


# ---------------------------------------------------------------------------
# Sender: GET /sync/config  (session auth) — UI gate
# ---------------------------------------------------------------------------

@sync_bp.route("/sync/config", methods=["GET"])
@login_required
def sync_config():
    """Report whether this server can send syncs, so the UI can gate the menu."""
    enabled = bool(
        current_app.config.get("SYNC_REMOTE_URL")
        and current_app.config.get("SYNC_REMOTE_TOKEN")
    )
    return jsonify({"sync_send_enabled": enabled})
