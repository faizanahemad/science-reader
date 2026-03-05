"""
Document-related endpoints.

This module extracts the conversation document management API surface from
`server.py` into a Flask Blueprint.
"""

from __future__ import annotations

import json
import logging
import os
import threading
import time
import traceback
import uuid
from typing import List

from flask import Blueprint, Response, jsonify, redirect, request, send_from_directory, session, stream_with_context

from endpoints.auth import login_required
from endpoints.request_context import attach_keys, get_state_and_keys
from endpoints.responses import json_error
from extensions import limiter


documents_bp = Blueprint("documents", __name__)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# In-memory task tracker for background doc upgrades.  Keyed by task_id.
# Each value is a dict: {status, phase, message, conversation_id, doc_id, ...}
# Entries are cleaned up 120s after completion.
# ---------------------------------------------------------------------------
_UPGRADE_TASKS: dict = {}




@documents_bp.route("/upload_doc_to_conversation/<conversation_id>", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def upload_doc_to_conversation_route(conversation_id: str):
    state, keys = get_state_and_keys()

    pdf_file = request.files.get("pdf_file")
    display_name = (request.form.get("display_name") or "").strip() or None
    conversation = attach_keys(state.conversation_cache[conversation_id], keys)

    if pdf_file and conversation_id:
        try:
            pdf_file.save(os.path.join(state.pdfs_dir, pdf_file.filename))
            full_pdf_path = os.path.join(state.pdfs_dir, pdf_file.filename)
            doc_index = conversation.add_fast_uploaded_document(full_pdf_path, display_name=display_name, docs_folder=getattr(state, 'docs_folder', None))
            conversation.save_local()
            result = {"status": "Indexing started"}
            if doc_index and hasattr(doc_index, "get_short_info"):
                info = doc_index.get_short_info()
                result["doc_id"] = info.get("doc_id", "")
                result["source"] = info.get("source", "")
                result["title"] = info.get("title", pdf_file.filename)
                result["display_name"] = info.get("display_name", "")
            return jsonify(result)
        except Exception as e:
            traceback.print_exc()
            return json_error(str(e), status=400, code="bad_request")
    pdf_url = None
    if request.is_json and request.json:
        pdf_url = request.json.get("pdf_url")
        if display_name is None:
            display_name = (request.json.get("display_name") or "").strip() or None

    if pdf_url:
        from common import convert_to_pdf_link_if_needed
        pdf_url = convert_to_pdf_link_if_needed(pdf_url)

    if pdf_url:
        try:
            doc_index = conversation.add_fast_uploaded_document(pdf_url, display_name=display_name, docs_folder=getattr(state, 'docs_folder', None))
            conversation.save_local()
            result = {"status": "Indexing started"}
            if doc_index and hasattr(doc_index, "get_short_info"):
                info = doc_index.get_short_info()
                result["doc_id"] = info.get("doc_id", "")
                result["source"] = info.get("source", "")
                result["title"] = info.get("title", "")
                result["display_name"] = info.get("display_name", "")
            return jsonify(result)
        except Exception as e:
            traceback.print_exc()
            return json_error(str(e), status=400, code="bad_request")
    return json_error("No pdf_url or pdf_file provided", status=400, code="bad_request")




@documents_bp.route("/attach_doc_to_message/<conversation_id>", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def attach_doc_to_message_route(conversation_id: str):
    """Upload a file and store it as a message-attached FastDocIndex.

    Used by the drag-onto-page and paperclip-icon flows: the file appears in
    the attachment-preview strip above the message box, is available to the LLM
    for the current turn via display_attachments, and lives in
    ``message_attached_documents_list`` (not the conversation document panel).

    Returns the same JSON shape as /upload_doc_to_conversation/ so the JS
    enrichAttachmentWithDocInfo() call works without modification.
    """
    state, keys = get_state_and_keys()
    pdf_file = request.files.get("pdf_file")
    conversation = attach_keys(state.conversation_cache[conversation_id], keys)

    if pdf_file and conversation_id:
        try:
            pdf_file.save(os.path.join(state.pdfs_dir, pdf_file.filename))
            full_pdf_path = os.path.join(state.pdfs_dir, pdf_file.filename)
            doc_index = conversation.add_message_attached_document(full_pdf_path, docs_folder=getattr(state, 'docs_folder', None))
            conversation.save_local()
            result = {"status": "Attached"}
            if doc_index and hasattr(doc_index, "get_short_info"):
                info = doc_index.get_short_info()
                result["doc_id"] = info.get("doc_id", "")
                result["source"] = info.get("source", "")
                result["title"] = info.get("title", pdf_file.filename)
            return jsonify(result)
        except Exception as e:
            traceback.print_exc()
            return json_error(str(e), status=400, code="bad_request")

    return json_error("No pdf_file provided", status=400, code="bad_request")

@documents_bp.route(
    "/promote_message_doc/<conversation_id>/<document_id>",
    methods=["POST"],
)
@limiter.limit("20 per minute")
@login_required
def promote_message_doc_route(conversation_id: str, document_id: str):
    state, keys = get_state_and_keys()
    conversation = attach_keys(state.conversation_cache[conversation_id], keys)
    if document_id:
        try:
            promoted = conversation.promote_message_attached_document(document_id, docs_folder=getattr(state, 'docs_folder', None))
            if promoted is None:
                return json_error(
                    "Document not found in message attachments",
                    status=404,
                    code="not_found",
                )
            info = (
                promoted.get_short_info() if hasattr(promoted, "get_short_info") else {}
            )
            return jsonify(
                {
                    "status": "Document promoted to conversation",
                    "doc_id": info.get("doc_id", ""),
                    "source": info.get("source", ""),
                    "title": info.get("title", ""),
                }
            )
        except Exception as e:
            traceback.print_exc()
            return json_error(str(e), status=400, code="bad_request")
    return json_error("No document_id provided", status=400, code="bad_request")


@documents_bp.route(
    "/delete_document_from_conversation/<conversation_id>/<document_id>",
    methods=["DELETE"],
)
@limiter.limit("100 per minute")
@login_required
def delete_document_from_conversation_route(conversation_id: str, document_id: str):
    state, keys = get_state_and_keys()

    conversation = attach_keys(state.conversation_cache[conversation_id], keys)

    doc_id = document_id
    if doc_id:
        try:
            conversation.delete_uploaded_document(doc_id)
            return jsonify({"status": "Document deleted"})
        except Exception as e:
            traceback.print_exc()
            return json_error(str(e), status=400, code="bad_request")

    return json_error("No doc_id provided", status=400, code="bad_request")


@documents_bp.route(
    "/list_documents_by_conversation/<conversation_id>", methods=["GET"]
)
@limiter.limit("30 per minute")
@login_required
def list_documents_by_conversation_route(conversation_id: str):
    state, keys = get_state_and_keys()

    conversation = attach_keys(state.conversation_cache[conversation_id], keys)

    if conversation:
        docs: List = conversation.get_uploaded_documents(readonly=True, docs_folder=getattr(state, 'docs_folder', None))
        docs = [d for d in docs if d is not None]
        docs = attach_keys(docs, keys)
        docs = [d.get_short_info() for d in docs]
        return jsonify(docs)

    return json_error(
        "Conversation not found", status=404, code="conversation_not_found"
    )


@documents_bp.route(
    "/download_doc_from_conversation/<conversation_id>/<doc_id>", methods=["GET"]
)
@limiter.limit("30 per minute")
@login_required
def download_doc_from_conversation_route(conversation_id: str, doc_id: str):
    state, keys = get_state_and_keys()

    conversation = state.conversation_cache[conversation_id]
    if conversation:
        conversation = attach_keys(conversation, keys)
        doc = conversation.get_uploaded_documents(doc_id, readonly=True)[0]
        if doc and os.path.exists(doc.doc_source):
            file_dir, file_name = os.path.split(doc.doc_source)
            if os.path.dirname(__file__).strip() != "":
                root_dir = os.path.dirname(__file__) + "/"
                file_dir = file_dir.replace(root_dir, "")
            return send_from_directory(file_dir, file_name)
        if doc:
            return redirect(doc.doc_source)
        return json_error("Document not found", status=404, code="document_not_found")

    return json_error(
        "Conversation not found", status=404, code="conversation_not_found"
    )



@documents_bp.route(
    "/upgrade_doc_index/<conversation_id>/<doc_id>", methods=["POST"]
)
@limiter.limit("10 per minute")
@login_required
def upgrade_doc_index_route(conversation_id: str, doc_id: str):
    """Start a background upgrade of a FastDocIndex to a full DocIndex.

    Returns 202 with a ``task_id``.  Connect to
    ``GET /upgrade_doc_index_progress/<task_id>`` for SSE progress events.
    """
    state, keys = get_state_and_keys()
    conversation = attach_keys(state.conversation_cache.get(conversation_id), keys)
    if conversation is None:
        return json_error("Conversation not found", status=404, code="not_found")

    docs = conversation.get_uploaded_documents(
        doc_id=doc_id,
        readonly=False,
        docs_folder=getattr(state, "docs_folder", None),
    )
    if not docs:
        return json_error("Document not found", status=404, code="not_found")

    doc_index = docs[0]
    if not getattr(doc_index, "_is_fast_index", False):
        return jsonify({"status": "ok", "is_fast_index": False, "message": "Already a full index"})

    task_id = str(uuid.uuid4())
    _UPGRADE_TASKS[task_id] = {
        "status": "running",
        "phase": "queued",
        "message": "Starting upgrade…",
        "conversation_id": conversation_id,
        "doc_id": doc_id,
        "started_at": time.time(),
    }

    # Capture what we need; run the heavy work outside the request.
    doc_source = doc_index.doc_source
    parent_dir = os.path.dirname(doc_index._storage)
    visible = doc_index.visible
    display_name = getattr(doc_index, "_display_name", None)

    t = threading.Thread(
        target=_run_upgrade_background,
        args=(task_id, conversation_id, doc_id, doc_source, parent_dir,
              keys, visible, display_name, state),
        daemon=True,
    )
    t.start()
    return jsonify({"status": "started", "task_id": task_id}), 202


def _run_upgrade_background(
    task_id: str,
    conversation_id: str,
    doc_id: str,
    doc_source: str,
    parent_dir: str,
    keys: dict,
    visible: bool,
    display_name,
    state,
):
    """Background thread that builds the full DocIndex and updates progress."""
    task = _UPGRADE_TASKS[task_id]

    def _progress(phase: str, message: str):
        task["phase"] = phase
        task["message"] = message

    try:
        from DocIndex import create_immediate_document_index

        full_doc_index = create_immediate_document_index(
            doc_source, parent_dir, keys, progress_callback=_progress
        )
        full_doc_index._visible = visible
        full_doc_index._display_name = display_name
        full_doc_index.save_local()

        _progress("saving", "Updating conversation…")

        # Re-load conversation to update its document list.
        conversation = state.conversation_cache.get(conversation_id)
        if conversation is not None:
            from endpoints.request_context import attach_keys as _ak
            conversation = _ak(conversation, keys)
            doc_list = conversation.get_field("uploaded_documents_list") or []
            updated = []
            for entry in doc_list:
                if entry[0] == doc_id:
                    entry = (full_doc_index.doc_id, full_doc_index._storage) + entry[2:]
                updated.append(entry)
            conversation.set_field("uploaded_documents_list", updated, overwrite=True)
            conversation.save_local()

        task.update({
            "status": "completed",
            "phase": "done",
            "message": "Full index built successfully.",
            "is_fast_index": False,
        })
    except Exception as exc:
        traceback.print_exc()
        task.update({
            "status": "error",
            "phase": "error",
            "message": str(exc),
        })
    finally:
        # Auto-cleanup after 120 s so the dict doesn't grow unboundedly.
        def _cleanup():
            time.sleep(120)
            _UPGRADE_TASKS.pop(task_id, None)
        threading.Thread(target=_cleanup, daemon=True).start()


@documents_bp.route("/upgrade_doc_index_progress/<task_id>")
@login_required
def upgrade_doc_index_progress(task_id: str):
    """SSE stream of upgrade progress for *task_id*."""

    def generate():
        last_phase = None
        while True:
            task = _UPGRADE_TASKS.get(task_id)
            if task is None:
                yield f"data: {json.dumps({'status': 'error', 'phase': 'not_found', 'message': 'Task not found or expired'})}\n\n"
                break
            # Emit only on phase change (or first iteration)
            if task["phase"] != last_phase:
                last_phase = task["phase"]
                yield f"data: {json.dumps(task)}\n\n"
            if task["status"] in ("completed", "error"):
                break
            time.sleep(0.5)

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )

@documents_bp.route("/cleanup_orphan_docs", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def cleanup_orphan_docs_route():
    """Delete canonical doc folders with zero references across all conversations and global docs.

    Accepts optional JSON body: ``{"dry_run": true}`` to preview without deleting.

    Returns::

        {
            "status": "ok",
            "referenced": <int>,   # doc_ids still referenced somewhere
            "orphaned": <int>,    # orphan folders found
            "deleted": <int>,    # folders actually deleted (0 if dry_run)
            "errors": <int>,     # non-fatal errors encountered
            "dry_run": <bool>
        }
    """
    from flask import session
    import canonical_docs as _cd

    state = get_state_and_keys()[0]
    email = session.get("email", "")
    if not email:
        return json_error("Not authenticated", status=401, code="not_authenticated")

    body = request.get_json(silent=True) or {}
    dry_run = bool(body.get("dry_run", False))

    u_hash = _cd.user_hash(email)
    try:
        result = _cd.cleanup_orphan_docs(
            docs_folder=state.docs_folder,
            u_hash=u_hash,
            conversation_folder=state.conversation_folder,
            user_email=email,
            users_dir=state.users_dir,
            dry_run=dry_run,
        )
        return jsonify({"status": "ok", **result})
    except Exception as e:
        traceback.print_exc()
        return json_error(str(e), status=500, code="cleanup_failed")




@documents_bp.route("/docs/autocomplete", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def docs_autocomplete():
    """Unified document autocomplete for @doc/ references in chat input.

    Searches both conversation (local) documents and global documents by
    prefix, returning a combined list with type badges.

    Query params:
        conversation_id (optional): Include conversation docs in results.
        prefix (optional): Filter by display_name / title substring (case-insensitive).
        limit (optional): Max total results (default 10, max 20).

    Returns JSON::

        {
            "status": "ok",
            "docs": [
                {"type": "local", "index": 1, "doc_id": "...", "title": "...",
                 "display_name": "...", "short_summary": "...", "ref": "#doc_1"},
                {"type": "global", "index": 3, "doc_id": "...", "title": "...",
                 "display_name": "...", "short_summary": "...", "ref": "#gdoc_3"}
            ]
        }
    """
    state, keys = get_state_and_keys()
    email = session.get("email", "")
    if not email:
        return json_error("Not authenticated", status=401, code="not_authenticated")

    conversation_id = request.args.get("conversation_id", "").strip()
    prefix = request.args.get("prefix", "").strip().lower()
    try:
        limit = min(int(request.args.get("limit", "10")), 20)
    except (ValueError, TypeError):
        limit = 10

    results = []

    # --- Conversation (local) documents ---
    if conversation_id and conversation_id in state.conversation_cache:
        try:
            conversation = attach_keys(
                state.conversation_cache[conversation_id], keys
            )
            doc_list = conversation.get_field("uploaded_documents_list") or []
            for idx, entry in enumerate(doc_list):
                doc_id = entry[0]
                doc_storage = entry[1]
                display_name = entry[3] if len(entry) > 3 and entry[3] else ""
                # Load lightweight info from stored DocIndex (cheap pickle load).
                title = display_name or doc_id
                short_summary = ""
                try:
                    from DocIndex import DocIndex as _DI
                    loaded = _DI.load_local(doc_storage)
                    if loaded is not None:
                        title = display_name or getattr(loaded, '_title', '') or doc_id
                        short_summary = getattr(loaded, '_short_summary', '') or ''

                except Exception:
                    pass  # fall back to display_name / empty summary
                # Filter by prefix
                match_text = (title + " " + display_name + " " + doc_id).lower()
                if prefix and prefix not in match_text:
                    continue

                results.append({
                    "type": "local",
                    "index": idx + 1,
                    "doc_id": doc_id,
                    "title": title,
                    "display_name": display_name or title,
                    "short_summary": short_summary,
                    "ref": f"#doc_{idx + 1}",
                })
        except Exception:
            logger.exception("docs_autocomplete: error loading conversation docs")

    # --- Global documents ---
    try:
        from database.global_docs import list_global_docs

        global_rows = list_global_docs(
            users_dir=state.users_dir, user_email=email
        )
        for idx, row in enumerate(global_rows):
            display_name = row.get("display_name", "") or ""
            title = row.get("title", "") or ""
            doc_id = row.get("doc_id", "")
            short_summary = row.get("short_summary", "") or ""

            match_text = (
                title + " " + display_name + " " + doc_id + " " + short_summary
            ).lower()
            if prefix and prefix not in match_text:
                continue

            results.append({
                "type": "global",
                "index": idx + 1,
                "doc_id": doc_id,
                "title": title,
                "display_name": display_name or title,
                "short_summary": short_summary,
                "ref": f"#gdoc_{idx + 1}",
            })
    except Exception:
        logger.exception("docs_autocomplete: error loading global docs")

    return jsonify({"status": "ok", "docs": results[:limit]})