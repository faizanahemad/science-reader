"""
Conversation read endpoints (initial slice).

This module starts the extraction of conversation-related routes out of `server.py`.
We keep this first slice intentionally small and low-risk:
- list messages
- list shareable messages
- get conversation history (summary text)
- get conversation details (metadata + workspace)

As we expand, additional conversation write/update endpoints will move here too.
"""

from __future__ import annotations

import json
import os
import time
import threading
import traceback
import logging
import secrets
import string
from datetime import datetime
from typing import List

from flask import Blueprint, Response, jsonify, request, send_from_directory, session

from Conversation import Conversation, model_name_to_canonical_name
from DocIndex import DocIndex
from common import (
    COMMON_SALT_STRING,
    VERY_CHEAP_LLM,
    CHEAP_LLM,
    EXPENSIVE_LLM,
    CHEAP_LONG_CONTEXT_LLM,
    LONG_CONTEXT_LLM,
    SUPERFAST_LLM,
    get_first_n_words,
)
from database.conversations import (
    addConversation,
    checkConversationExists,
    cleanup_deleted_conversations,
    deleteConversationForUser,
    getConversationById,
    getAllCoversations,
    getCoversationsForUser,
    removeUserFromConversation,
)
from database.users import getUserFromUserDetailsTable
from database.workspaces import getWorkspaceForConversation, load_workspaces_for_user
from endpoints.auth import login_required
from endpoints.request_context import attach_keys, get_conversation_with_keys
from endpoints.responses import json_error
from endpoints.session_utils import get_session_identity
from endpoints.state import get_state
from endpoints.utils import keyParser, set_keys_on_docs
from extensions import limiter
from very_common import get_async_future


conversations_bp = Blueprint("conversations", __name__)
logger = logging.getLogger(__name__)
_ALPHABET = string.ascii_letters + string.digits

# ---------------------------------------------------------------------------
# Thread-safe storage for interactive tool responses.
# Used by the agentic tool loop in Conversation._run_tool_loop() to pause
# and wait for user input that arrives via POST /tool_response.
# ---------------------------------------------------------------------------
_tool_response_events = {}   # {tool_id: threading.Event}
_tool_response_data = {}     # {tool_id: dict}
_tool_response_lock = threading.Lock()


def wait_for_tool_response(tool_id, timeout=60):
    """Wait for a user's tool response submitted via POST /tool_response.
    
    Called by the background thread running Conversation._run_tool_loop().
    Blocks until the user submits a response or timeout expires.
    
    Parameters
    ----------
    tool_id : str
        The tool call ID to wait for.
    timeout : int
        Maximum seconds to wait (default 60).
    
    Returns
    -------
    dict or None
        The user's response data, or None if timeout.
    """
    event = threading.Event()
    
    with _tool_response_lock:
        _tool_response_events[tool_id] = event
    
    # Block until response arrives or timeout
    got_response = event.wait(timeout=timeout)
    
    # Cleanup and return
    with _tool_response_lock:
        _tool_response_events.pop(tool_id, None)
        if got_response:
            return _tool_response_data.pop(tool_id, None)
        else:
            _tool_response_data.pop(tool_id, None)
            return None


# ---------------------------------------------------------------------------
# Auto-archival throttle and helper
# ---------------------------------------------------------------------------
_last_auto_archive_run: float = 0


def _run_auto_archival(conversations, grace_days: int, users_dir: str) -> list:
    """Run auto-archival pass on active conversations. Returns list of auto-archived IDs."""
    global _last_auto_archive_run
    from database.pinned_messages import get_pinned_messages as db_get_pins
    from database.similarity_cache import get_all_cached, upsert_cache
    from utils.auto_archival import compute_staleness
    from utils.text_similarity import tokenize, compute_title_summary_hash

    now = datetime.now()
    active_convs = [c for c in conversations if not c.archived and not c.stateless]
    if not active_convs:
        _last_auto_archive_run = time.time()
        return []

    # Fetch pinned message conversation IDs (batch)
    pinned_conv_ids = set()
    for c in active_convs:
        try:
            pins = db_get_pins(c.conversation_id, users_dir=users_dir)
            if pins:
                pinned_conv_ids.add(c.conversation_id)
        except Exception:
            pass

    # Build metadata + message counts
    conv_data = []
    for c in active_convs:
        try:
            meta = c.get_metadata()
            msg_count = len(c.get_message_list())
            conv_data.append((c, meta, msg_count))
        except Exception:
            continue

    # Time pre-filter: only score conversations past grace/2
    candidates = []
    for c, meta, msg_count in conv_data:
        last_updated_str = meta.get("last_updated", "")
        last_opened_str = meta.get("last_opened_at")
        try:
            lu = datetime.strptime(last_updated_str, "%Y-%m-%d %H:%M:%S") if last_updated_str else now
        except ValueError:
            lu = now
        lo = lu  # if last_opened_at unknown, fall back to last_updated
        if last_opened_str:
            try:
                lo = datetime.strptime(last_opened_str, "%Y-%m-%d %H:%M:%S") if isinstance(last_opened_str, str) else last_opened_str
            except (ValueError, TypeError):
                lo = lu
        staleness_clock = max(lu, lo)
        age_days = (now - staleness_clock).days
        if age_days > grace_days / 4:
            candidates.append((c, meta, msg_count))

    # Cap at 50 candidates
    candidates = candidates[:50]
    if not candidates:
        _last_auto_archive_run = time.time()
        return []

    # Build similarity cache
    candidate_ids = [c.conversation_id for c, _, _ in candidates]
    all_conv_ids = [c.conversation_id for c in active_convs]
    cache_map = get_all_cached(all_conv_ids, users_dir=users_dir)

    # Populate/update cache for candidates missing entries
    for c, meta, _ in conv_data:
        title = meta.get("title", "")
        summary = meta.get("summary_till_now", "")
        current_hash = compute_title_summary_hash(title, summary)
        cached = cache_map.get(c.conversation_id)
        if cached is None or cached.get("title_summary_hash") != current_hash:
            tokens = tokenize(title + " " + (summary or "")[:200])
            upsert_cache(c.conversation_id, current_hash, bm25_tokens=tokens, users_dir=users_dir)
            cache_map[c.conversation_id] = {
                "conversation_id": c.conversation_id,
                "title_summary_hash": current_hash,
                "bm25_tokens": tokens,
                "embedding": cached.get("embedding") if cached else None,
            }

    # Build all_conv_tokens for superseded detection
    all_conv_tokens = []
    for c, meta, _ in conv_data:
        cached = cache_map.get(c.conversation_id, {})
        tokens = cached.get("bm25_tokens", [])
        lu_str = meta.get("last_updated", "")
        try:
            lu = datetime.strptime(lu_str, "%Y-%m-%d %H:%M:%S") if lu_str else now
        except ValueError:
            lu = now
        all_conv_tokens.append((c.conversation_id, tokens, lu, cached.get("embedding")))

    # Score candidates
    stale_results = []
    for c, meta, msg_count in candidates:
        is_stale, reason = compute_staleness(
            meta, msg_count, all_conv_tokens, cache_map,
            pinned_conv_ids, grace_days=grace_days, now=now
        )
        if is_stale:
            stale_results.append((c, reason))

    # Archive top 5 (Q1: max 5 per load)
    archived_ids = []
    for c, reason in stale_results[:5]:
        c._archived = True
        c._archive_source = "auto"
        archived_ids.append(c.conversation_id)
        logger.info("Auto-archived %s: %s", c.conversation_id, reason)

    # Batch save (synchronous — 5 pickle writes is fast, avoids SQLite lock contention)
    for c, _ in stale_results[:5]:
        c.save_local()

    _last_auto_archive_run = time.time()
    return archived_ids


@conversations_bp.route(
    "/list_messages_by_conversation/<conversation_id>", methods=["GET"]
)
@limiter.limit("1000 per minute")
@login_required
def list_messages_by_conversation(conversation_id: str):
    keys = keyParser(session)
    email, _name, _loggedin = get_session_identity()
    _last_n_messages = request.args.get(
        "last_n_messages", 10
    )  # preserved; unused (legacy)

    if not checkConversationExists(
        email, conversation_id, users_dir=get_state().users_dir
    ):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = get_conversation_with_keys(
        get_state(), conversation_id=conversation_id, keys=keys
    )
    messages = conversation.get_message_list()

    # Optionally fold the conversation UI state into this response so the UI can
    # reach its final rendered state from a SINGLE round trip (and a SINGLE
    # backend conversation load). Message show/hide already ships per-message in
    # `messages` (the `show_hide` field), so we only need to attach the section
    # collapse states, which live in a separate table. This lets the client skip
    # the otherwise-redundant /get_conversation_ui_state call, which re-loads and
    # re-decrypts the conversation purely to re-extract `show_hide`.
    include_ui_state = str(request.args.get("include_ui_state", "")).lower() in (
        "1",
        "true",
        "yes",
    )
    if include_ui_state:
        try:
            from database.sections import get_all_section_hidden_details

            section_details = get_all_section_hidden_details(
                conversation_id=conversation_id,
                users_dir=get_state().users_dir,
                logger=logger,
            )
        except Exception as e:  # pragma: no cover - defensive
            logger.error(f"Failed to load section_details for {conversation_id}: {e}")
            section_details = {}
        return jsonify({"messages": messages, "section_details": section_details})

    return jsonify(messages)


@conversations_bp.route(
    "/list_messages_by_conversation_shareable/<conversation_id>", methods=["GET"]
)
@limiter.limit("100 per minute")
def list_messages_by_conversation_shareable(conversation_id: str):
    keys = keyParser(session)
    _email, _name, _loggedin = get_session_identity()

    conversation_ids = [
        c[1] for c in getAllCoversations(users_dir=get_state().users_dir)
    ]
    if conversation_id not in conversation_ids:
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation: Conversation = get_conversation_with_keys(
        get_state(), conversation_id=conversation_id, keys=keys
    )

    docs: List[DocIndex] = conversation.get_uploaded_documents(readonly=True)
    docs = [d.get_short_info() for d in docs]
    messages = conversation.get_message_list()
    return jsonify({"messages": messages, "docs": docs})


@conversations_bp.route("/get_conversation_history/<conversation_id>", methods=["GET"])
@limiter.limit("100 per minute")
@login_required
def get_conversation_history(conversation_id: str):
    """Get comprehensive conversation history including summary and recent messages."""

    try:
        user_email = session.get("email")
        if not checkConversationExists(
            user_email, conversation_id, users_dir=get_state().users_dir
        ):
            return json_error(
                "Conversation not found or access denied",
                status=404,
                code="conversation_not_found",
            )

        # Use cached conversation + lock-clearing behavior already embedded in the cache loader.
        conversation: Conversation = get_state().conversation_cache[conversation_id]
        conversation.record_access()
        query = request.args.get("query", "")
        history_text = conversation.get_conversation_history(query)

        return jsonify(
            {
                "conversation_id": conversation_id,
                "history": history_text,
                "timestamp": time.time(),
            }
        )
    except Exception as e:
        return json_error(str(e), status=500, code="internal_error")


@conversations_bp.route("/get_conversation_details/<conversation_id>", methods=["GET"])
@limiter.limit("1000 per minute")
@login_required
def get_conversation_details(conversation_id: str):
    """
    Return conversation metadata along with full workspace information for the given conversation_id.
    """

    keys = keyParser(session)
    email, _name, _loggedin = get_session_identity()

    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )
    data = conversation.get_metadata()

    workspace_info = getWorkspaceForConversation(
        users_dir=state.users_dir, conversation_id=conversation_id
    )
    if not workspace_info:
        workspace_info = {"workspace_id": None}

    data["workspace"] = workspace_info
    return jsonify(data)


def _dedupe_models(models: list[str]) -> list[str]:
    seen = set()
    deduped = []
    for model in models:
        if model in seen:
            continue
        seen.add(model)
        deduped.append(model)
    return deduped


def _catalog_model_list() -> list:
    """Deduped union of every model offered in the model-override UI dropdowns.

    This is the single source of truth for which models the UI exposes. The
    ``/model_catalog`` endpoint and the ``set_conversation_settings`` validator
    both use it so that any model a user can pick in the dropdown is also
    accepted on save (see ``set_conversation_settings``).
    """
    return _dedupe_models(
        SUPERFAST_LLM
        + VERY_CHEAP_LLM
        + CHEAP_LLM
        + EXPENSIVE_LLM
        + CHEAP_LONG_CONTEXT_LLM
        + LONG_CONTEXT_LLM
    )


@conversations_bp.route("/model_catalog", methods=["GET"])
@limiter.limit("300 per minute")
@login_required
def get_model_catalog():
    models = _catalog_model_list()
    defaults = {
        "conversation_internal_model": SUPERFAST_LLM[0],
        "quick_action_model": SUPERFAST_LLM[0],
        "artefact_propose_edits_model": EXPENSIVE_LLM[2],
        "doc_model": CHEAP_LONG_CONTEXT_LLM[0],
        "clarify_intent_model": VERY_CHEAP_LLM[0],
        "pkb_nl_model": CHEAP_LLM[0],
    }
    return jsonify({"models": models, "defaults": defaults})


@conversations_bp.route("/get_conversation_settings/<conversation_id>", methods=["GET"])
@limiter.limit("200 per minute")
@login_required
def get_conversation_settings(conversation_id: str):
    keys = keyParser(session)
    email, _name, _loggedin = get_session_identity()
    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )
    settings = conversation.get_conversation_settings()
    return jsonify({"conversation_id": conversation_id, "settings": settings})


@conversations_bp.route("/set_conversation_settings/<conversation_id>", methods=["PUT"])
@limiter.limit("120 per minute")
@login_required
def set_conversation_settings(conversation_id: str):
    keys = keyParser(session)
    email, _name, _loggedin = get_session_identity()
    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )
    payload = request.json if request.is_json and request.json else {}
    # Partial update: only fields explicitly present in the payload are written.
    # This prevents one settings modal (e.g. OpenCode) from clobbering another's
    # settings (e.g. model_overrides) just because it didn't send them.
    has_model_overrides = "model_overrides" in payload
    model_overrides = payload.get("model_overrides")
    if model_overrides is None:
        model_overrides = {}
    if not isinstance(model_overrides, dict):
        return json_error(
            "model_overrides must be an object",
            status=400,
            code="invalid_settings",
        )

    allowed_keys = {
        "conversation_internal_model",
        "quick_action_model",
        "artefact_propose_edits_model",
        "doc_model",
        "clarify_intent_model",
        "pkb_nl_model",
        "auto_doubt_model",
    }
    catalog_models = set(_catalog_model_list())
    normalized_overrides = {}
    for key, value in model_overrides.items():
        if key not in allowed_keys:
            continue
        if value is None:
            continue
        value_str = str(value).strip()
        if not value_str:
            continue
        try:
            normalized_overrides[key] = model_name_to_canonical_name(value_str)
        except Exception:
            # The legacy canonicalizer doesn't know every model. Accept any value
            # the model catalog actually offers (the same list that populates the
            # UI dropdowns) so newly-added models can be selected without a 400.
            if value_str in catalog_models:
                normalized_overrides[key] = value_str
            else:
                return json_error(
                    f"Model name {value_str} not found in the list",
                    status=400,
                    code="invalid_model",
                )

    # --- opencode_config (optional) ---
    opencode_config = payload.get("opencode_config")
    if opencode_config is not None:
        if not isinstance(opencode_config, dict):
            return json_error(
                "opencode_config must be an object",
                status=400,
                code="invalid_settings",
            )
        _valid_injection = {"minimal", "medium", "full"}
        validated_oc: dict = {}
        validated_oc["always_enabled"] = bool(
            opencode_config.get("always_enabled", False)
        )
        inj = opencode_config.get("injection_level", "medium")
        if inj not in _valid_injection:
            return json_error(
                f"injection_level must be one of {_valid_injection}",
                status=400,
                code="invalid_settings",
            )
        validated_oc["injection_level"] = inj
        sess_ids = opencode_config.get("session_ids", [])
        if not isinstance(sess_ids, list):
            return json_error(
                "session_ids must be a list",
                status=400,
                code="invalid_settings",
            )
        validated_oc["session_ids"] = sess_ids
        validated_oc["active_session_id"] = opencode_config.get(
            "active_session_id"
        )
        # --- opencode_provider (optional) ---
        _valid_providers = {"openrouter", "amazon-bedrock"}
        oc_provider = opencode_config.get("opencode_provider", "openrouter")
        if oc_provider not in _valid_providers:
            oc_provider = "openrouter"
        validated_oc["opencode_provider"] = oc_provider
        # --- opencode_model (optional) ---
        _valid_models = {
            "anthropic/claude-haiku-4.5",
            "anthropic/claude-sonnet-4.5",
            "anthropic/claude-opus-4.5",
            "anthropic/claude-sonnet-4.6",
            "anthropic/claude-opus-4.6",
        }
        oc_model = opencode_config.get("opencode_model", "anthropic/claude-sonnet-4.5")
        if oc_model not in _valid_models:
            oc_model = "anthropic/claude-sonnet-4.5"
        validated_oc["opencode_model"] = oc_model
    else:
        validated_oc = None

    # --- auto_doubt_categories (optional) ---
    VALID_AUTO_DOUBT_CATEGORIES = {
        "takeaways", "maximize_learning", "challenge_verify",
        "foundations_practice", "answer_questions",
    }
    auto_doubt_categories = payload.get("auto_doubt_categories")
    if auto_doubt_categories is not None:
        if not isinstance(auto_doubt_categories, list):
            return json_error(
                "auto_doubt_categories must be a list",
                status=400, code="invalid_settings",
            )
        auto_doubt_categories = [
            c for c in auto_doubt_categories if c in VALID_AUTO_DOUBT_CATEGORIES
        ]

    existing = conversation.get_conversation_settings()
    updated = dict(existing) if isinstance(existing, dict) else {}
    if has_model_overrides:
        updated["model_overrides"] = normalized_overrides
    if validated_oc is not None:
        updated["opencode_config"] = validated_oc
    if auto_doubt_categories is not None:
        updated["auto_doubt_categories"] = auto_doubt_categories
    conversation.set_conversation_settings(updated, overwrite=True)
    return jsonify({"conversation_id": conversation_id, "settings": updated})


@conversations_bp.route(
    "/make_conversation_stateless/<conversation_id>", methods=["DELETE"]
)
@limiter.limit("25 per minute")
@login_required
def make_conversation_stateless(conversation_id: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)

    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )
    if conversation.stateless:
        conversation.make_stateful()
        return jsonify({"message": f"Conversation {conversation_id} is now stateful.", "stateless": False})
    else:
        conversation.make_stateless()
        return jsonify({"message": f"Conversation {conversation_id} stateless now.", "stateless": True})


@conversations_bp.route(
    "/make_conversation_stateful/<conversation_id>", methods=["PUT"]
)
@limiter.limit("25 per minute")
@login_required
def make_conversation_stateful(conversation_id: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)

    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )
    conversation.make_stateful()
    return jsonify({"message": f"Conversation {conversation_id} deleted"})


@conversations_bp.route(
    "/edit_message_from_conversation/<conversation_id>/<message_id>/<index>",
    methods=["POST"],
)
@limiter.limit("30 per minute")
@login_required
def edit_message_from_conversation(conversation_id: str, message_id: str, index: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)

    message_text = (
        request.json.get("text") if request.is_json and request.json else None
    )

    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )
    conversation.edit_message(message_id, index, message_text)
    return jsonify({"message": f"Message {message_id} deleted"})


@conversations_bp.route(
    "/get_message_text/<conversation_id>/<message_id>",
    methods=["GET"],
)
@limiter.limit("120 per minute")
@login_required
def get_message_text(conversation_id: str, message_id: str):
    """Return the persisted text of a single message.

    This is the canonical source of truth for a message body. The UI uses it to
    populate the edit dialog so that display-only content streamed during a turn
    (e.g. the "PKB Retrieval Details" collapsible or ``<tool_calls_summary>``
    blocks) — which is intentionally NOT saved to the backend — cannot leak into
    an edit and get re-persisted as junk. The stored text already contains the
    persisted parts (such as the ``<answer_tldr>`` collapsible), so editing it is
    consistent with what a page reload would show.

    Parameters
    ----------
    conversation_id : str
        The conversation that owns the message.
    message_id : str
        The id of the message whose stored text is requested.

    Returns
    -------
    flask.Response
        JSON ``{"message_id", "index", "text"}`` on success, or a JSON error with
        a 404 status if the conversation or message does not exist.
    """
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)

    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )
    message, index = conversation.get_message_by_id(message_id)
    if message is None:
        return json_error(
            "Message not found", status=404, code="message_not_found"
        )

    return jsonify(
        {
            "message_id": message_id,
            "index": index,
            "text": message.get("text", ""),
        }
    )


@conversations_bp.route("/move_messages_up_or_down/<conversation_id>", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def move_messages_up_or_down(conversation_id: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)

    payload = request.json if request.is_json and request.json else {}
    message_ids = payload.get("message_ids")
    direction = payload.get("direction")
    assert isinstance(message_ids, list)
    assert all(isinstance(m, str) for m in message_ids)
    assert direction in ["up", "down"]

    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )
    conversation.move_messages_up_or_down(message_ids, direction)
    return jsonify({"message": f"Messages {message_ids} moved {direction}"})


@conversations_bp.route(
    "/get_next_question_suggestions/<conversation_id>", methods=["GET"]
)
@limiter.limit("30 per minute")
@login_required
def get_next_question_suggestions(conversation_id: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)

    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )
    suggestions = conversation.get_next_question_suggestions()
    return jsonify({"suggestions": suggestions})


@conversations_bp.route(
    "/show_hide_message_from_conversation/<conversation_id>/<message_id>/<index>",
    methods=["POST"],
)
@limiter.limit("30 per minute")
@login_required
def show_hide_message_from_conversation(
    conversation_id: str, message_id: str, index: str
):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)

    show_hide = (
        request.json.get("show_hide") if request.is_json and request.json else None
    )

    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )
    conversation.show_hide_message(message_id, index, show_hide)
    return jsonify({"message": f"Message {message_id} state changed to {show_hide}"})


@conversations_bp.route("/batch_delete_messages/<conversation_id>", methods=["POST"])
@limiter.limit("25 per minute")
@login_required
def batch_delete_messages(conversation_id: str):
    """Delete multiple messages by IDs in one operation."""
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    data = request.json or {}
    message_ids = data.get("message_ids", [])
    if not message_ids:
        return json_error("No message_ids provided", status=400, code="bad_request")

    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)
    deleted = conversation.delete_messages_batch(message_ids)
    return jsonify({"deleted": deleted})


@conversations_bp.route("/batch_hide_messages/<conversation_id>", methods=["POST"])
@limiter.limit("25 per minute")
@login_required
def batch_hide_messages(conversation_id: str):
    """Set show_hide on multiple messages in one operation."""
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    data = request.json or {}
    message_ids = data.get("message_ids", [])
    show_hide = data.get("show_hide", "hide")
    if not message_ids:
        return json_error("No message_ids provided", status=400, code="bad_request")

    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)
    count = conversation.batch_show_hide_messages(message_ids, show_hide)
    return jsonify({"hidden": count})


@conversations_bp.route("/clone_conversation/<conversation_id>", methods=["POST"])
@limiter.limit("25 per minute")
@login_required
def clone_conversation(conversation_id: str):
    """
    Clone an existing conversation, preserving its workspace association.
    """

    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    state = get_state()

    # Preserve legacy behavior: require the conversation to already be in the cache.
    if conversation_id not in state.conversation_cache:
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation: Conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )

    new_conversation: Conversation = conversation.clone_conversation()
    new_conversation.save_local()

    workspace_info = getWorkspaceForConversation(
        users_dir=state.users_dir, conversation_id=conversation_id
    )
    workspace_id = workspace_info.get("workspace_id") if workspace_info else None

    addConversation(
        email,
        new_conversation.conversation_id,
        workspace_id=workspace_id,
        domain=conversation.domain,
        users_dir=state.users_dir,
    )

    state.conversation_cache[new_conversation.conversation_id] = new_conversation

    return jsonify(
        {
            "message": f"Conversation {conversation_id} cloned",
            "conversation_id": new_conversation.conversation_id,
        }
    )


@conversations_bp.route("/fork_conversation/<conversation_id>/<int:msg_index>", methods=["POST"])
@limiter.limit("25 per minute")
@login_required
def fork_conversation(conversation_id: str, msg_index: int):
    """Fork a conversation from a specific message index."""
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    state = get_state()

    if conversation_id not in state.conversation_cache:
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation: Conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )

    messages = conversation.get_field("messages") or []
    if msg_index < 0 or msg_index >= len(messages):
        return json_error("Invalid message index", status=400, code="invalid_index")

    new_conversation: Conversation = conversation.fork_from_message(msg_index)

    workspace_info = getWorkspaceForConversation(
        users_dir=state.users_dir, conversation_id=conversation_id
    )
    workspace_id = workspace_info.get("workspace_id") if workspace_info else None

    addConversation(
        email,
        new_conversation.conversation_id,
        workspace_id=workspace_id,
        domain=conversation.domain,
        users_dir=state.users_dir,
    )
    state.conversation_cache[new_conversation.conversation_id] = new_conversation

    return jsonify({
        "message": f"Forked conversation at message {msg_index}",
        "conversation_id": new_conversation.conversation_id,
    })


@conversations_bp.route("/delete_conversation/<conversation_id>", methods=["DELETE"])
@limiter.limit("5000 per minute")
@login_required
def delete_conversation(conversation_id: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )

    # Cross-conversation search: remove before deleting files
    try:
        index = state.cross_conversation_index
        if index:
            index.remove_conversation(conversation_id)
    except Exception:
        pass

    del state.conversation_cache[conversation_id]
    conversation.delete_conversation()
    deleteConversationForUser(email, conversation_id, users_dir=state.users_dir)
    removeUserFromConversation(email, conversation_id, users_dir=state.users_dir)

    return jsonify({"message": f"Conversation {conversation_id} deleted"})


@conversations_bp.route(
    "/delete_message_from_conversation/<conversation_id>/<message_id>/<index>",
    methods=["DELETE"],
)
@limiter.limit("300 per minute")
@login_required
def delete_message_from_conversation(conversation_id: str, message_id: str, index: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )
    try:
        conversation.delete_message(message_id, index)
        try:
            conversation.delete_artefact_message_link(str(message_id))
        except Exception:
            logger.exception(
                f"Failed to delete artefact link for conversation_id={conversation_id}, message_id={message_id}"
            )
    except ValueError:
        return json_error("Invalid index", status=400, code="invalid_index")
    except json.JSONDecodeError:
        logger.exception(
            f"Conversation JSON storage is corrupted for conversation_id={conversation_id}"
        )
        return json_error(
            "Conversation storage is corrupted (invalid JSON). "
            "This can happen if the server was interrupted mid-write. "
            "Please retry after refresh; if it persists, contact support.",
            status=500,
            code="conversation_storage_corrupt",
        )
    except Exception as e:
        # Covers GenericShortException and other runtime errors.
        logger.exception(
            f"Failed to delete message for conversation_id={conversation_id}, message_id={message_id}, index={index}: {e}"
        )
        return json_error(
            "Failed to delete message", status=500, code="delete_message_failed"
        )

    # Some clients send "undefined" for message_id; include index for clarity.
    return jsonify(
        {"message": f"Message deleted", "message_id": message_id, "index": index}
    )


@conversations_bp.route(
    "/delete_message_pair/<conversation_id>/<message_id>/<index>",
    methods=["DELETE"],
)
@limiter.limit("300 per minute")
@login_required
def delete_message_pair(conversation_id: str, message_id: str, index: str):
    """Delete a user+assistant message pair.

    Validates that the clicked message and its partner form a valid user/assistant pair.
    If clicked on a user message, the next message must be an assistant message.
    If clicked on an assistant message, the previous message must be a user message.
    Returns 400 if the pair is invalid (e.g., two consecutive user messages).
    """
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )

    try:
        deleted_message_ids = conversation.delete_message_pair(index)
    except ValueError as e:
        return json_error(str(e), status=400, code="no_pair_found")
    except json.JSONDecodeError:
        logger.exception(
            f"Conversation JSON storage is corrupted for conversation_id={conversation_id}"
        )
        return json_error(
            "Conversation storage is corrupted",
            status=500,
            code="conversation_storage_corrupt",
        )
    except Exception as e:
        logger.exception(
            f"Failed to delete message pair for conversation_id={conversation_id}, index={index}: {e}"
        )
        return json_error(
            "Failed to delete message pair", status=500, code="delete_pair_failed"
        )

    for mid in deleted_message_ids:
        try:
            conversation.delete_artefact_message_link(mid)
        except Exception:
            logger.exception(
                f"Failed to delete artefact link for conversation_id={conversation_id}, message_id={mid}"
            )

    return jsonify(
        {
            "message": "Message pair deleted",
            "deleted_message_ids": deleted_message_ids,
        }
    )


@conversations_bp.route("/delete_last_message/<conversation_id>", methods=["DELETE"])
@limiter.limit("30 per minute")
@login_required
def delete_last_message(conversation_id: str):
    message_id = 1  # preserved (legacy)
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation: Conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )
    try:
        conversation.delete_last_turn()
    except json.JSONDecodeError:
        logger.exception(
            f"Conversation JSON storage is corrupted for conversation_id={conversation_id}"
        )
        return json_error(
            "Conversation storage is corrupted (invalid JSON). "
            "This can happen if the server was interrupted mid-write. "
            "Please retry after refresh; if it persists, contact support.",
            status=500,
            code="conversation_storage_corrupt",
        )
    except Exception as e:
        logger.exception(
            f"Failed to delete last turn for conversation_id={conversation_id}: {e}"
        )
        return json_error(
            "Failed to delete last message",
            status=500,
            code="delete_last_message_failed",
        )
    return jsonify({"message": f"Message {message_id} deleted"})


@conversations_bp.route("/set_memory_pad/<conversation_id>", methods=["POST"])
@limiter.limit("25 per minute")
@login_required
def set_memory_pad(conversation_id: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )
    memory_pad = request.json.get("text") if request.is_json and request.json else None
    conversation.set_memory_pad(memory_pad)
    return jsonify({"message": "Memory pad set"})


@conversations_bp.route("/fetch_memory_pad/<conversation_id>", methods=["GET"])
@limiter.limit("1000 per minute")
@login_required
def fetch_memory_pad(conversation_id: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )
    memory_pad = conversation.memory_pad
    return jsonify({"text": memory_pad})


@conversations_bp.route(
    f"/get_conversation_output_docs/{COMMON_SALT_STRING}/<conversation_id>/<document_file_name>",
    methods=["GET"],
)
@limiter.limit("25 per minute")
def get_conversation_output_docs(conversation_id: str, document_file_name: str):
    """
    Download a conversation-produced document by filename, gated by a shared salt in the URL.

    Preserves the legacy behavior (no login required) and adds limited CORS headers for
    known embed clients.
    """

    conversation = get_state().conversation_cache[conversation_id]
    if os.path.exists(os.path.join(conversation.documents_path, document_file_name)):
        response = send_from_directory(conversation.documents_path, document_file_name)
        origin = request.headers.get("Origin")
        allowed_origins = [
            "https://laingsimon.github.io",
            "https://app.diagrams.net",
            "https://draw.io",
            "https://www.draw.io",
        ]
        if origin in allowed_origins:
            response.headers["Access-Control-Allow-Origin"] = origin
        response.headers["Access-Control-Allow-Methods"] = "GET"
        response.headers["Access-Control-Allow-Headers"] = "Content-Type"
        return response

    return json_error("Document not found", status=404, code="document_not_found")


@conversations_bp.route("/cancel_response/<conversation_id>", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def cancel_response(conversation_id: str):
    """Cancel an ongoing streaming response."""

    from base import cancellation_requests

    email, _name, _loggedin = get_session_identity()
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    cancellation_requests[conversation_id] = {
        "cancelled": True,
        "timestamp": time.time(),
    }
    logger.info(
        f"Cancellation requested for conversation {conversation_id} by user {email}"
    )
    return jsonify({"message": "Cancellation requested successfully"}), 200


@conversations_bp.route("/cleanup_cancellations", methods=["POST"])
def cleanup_cancellations():
    """Remove old cancellation requests (older than 1 hour)."""

    from base import cancellation_requests

    current_time = time.time()
    to_remove = []

    for conv_id, data in cancellation_requests.items():
        if current_time - data.get("timestamp", 0) > 3600:
            to_remove.append(conv_id)

    for conv_id in to_remove:
        del cancellation_requests[conv_id]

    return jsonify(
        {"message": f"Cleaned up {len(to_remove)} old cancellation requests"}
    ), 200


@conversations_bp.route("/cancel_coding_hint/<conversation_id>", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def cancel_coding_hint(conversation_id: str):
    """Cancel an ongoing coding hint generation."""

    from base import coding_hint_cancellation_requests

    email, _name, _loggedin = get_session_identity()
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    coding_hint_cancellation_requests[conversation_id] = {
        "cancelled": True,
        "timestamp": time.time(),
    }
    logger.info(
        f"Coding hint cancellation requested for conversation {conversation_id} by user {email}"
    )
    return jsonify({"message": "Coding hint cancellation requested successfully"}), 200


@conversations_bp.route("/cancel_coding_solution/<conversation_id>", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def cancel_coding_solution(conversation_id: str):
    """Cancel an ongoing coding solution generation."""

    from base import coding_solution_cancellation_requests

    email, _name, _loggedin = get_session_identity()
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    coding_solution_cancellation_requests[conversation_id] = {
        "cancelled": True,
        "timestamp": time.time(),
    }
    logger.info(
        f"Coding solution cancellation requested for conversation {conversation_id} by user {email}"
    )
    return jsonify(
        {"message": "Coding solution cancellation requested successfully"}
    ), 200


@conversations_bp.route("/get_coding_hint/<conversation_id>", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def get_coding_hint_endpoint(conversation_id: str):
    """Get a coding hint based on current context and code (streaming response)."""

    keys = keyParser(session)
    state = get_state()

    try:
        user_email = session.get("email")
        if not checkConversationExists(
            user_email, conversation_id, users_dir=state.users_dir
        ):
            logger.warning(
                f"User {user_email} attempted to access conversation {conversation_id} without permission"
            )
            return json_error(
                "Conversation not found or access denied",
                status=404,
                code="conversation_not_found",
            )

        data = request.get_json() or {}
        current_code = data.get("current_code", "")
        context_text = data.get("context", "")

        conversation = get_conversation_with_keys(
            state, conversation_id=conversation_id, keys=keys
        )
        conversation_history = conversation.get_conversation_history()

        from base import get_coding_hint

        def generate_hint_stream():
            try:
                yield (
                    json.dumps(
                        {
                            "text": "",
                            "status": "Analyzing your code and generating hint...",
                            "conversation_id": conversation_id,
                            "type": "hint",
                        }
                    )
                    + "\n"
                )

                hint_generator = get_coding_hint(
                    context_text,
                    conversation_history,
                    current_code,
                    keys,
                    stream=True,
                    conversation_id=conversation_id,
                )

                accumulated_text = ""
                for chunk in hint_generator:
                    if chunk:
                        accumulated_text += chunk
                        yield (
                            json.dumps(
                                {
                                    "text": chunk,
                                    "status": "Generating hint...",
                                    "conversation_id": conversation_id,
                                    "type": "hint",
                                    "accumulated_text": accumulated_text,
                                }
                            )
                            + "\n"
                        )

                yield (
                    json.dumps(
                        {
                            "text": "",
                            "status": "Hint generated successfully!",
                            "conversation_id": conversation_id,
                            "type": "hint",
                            "completed": True,
                            "accumulated_text": accumulated_text,
                        }
                    )
                    + "\n"
                )

                logger.info(
                    f"Generated streaming coding hint for conversation {conversation_id}, code length: {len(current_code)} chars"
                )

            except Exception as e:
                logger.error(f"Error in hint streaming for {conversation_id}: {str(e)}")
                yield (
                    json.dumps(
                        {
                            "text": "",
                            "status": f"Error: {str(e)}",
                            "conversation_id": conversation_id,
                            "type": "hint",
                            "error": True,
                        }
                    )
                    + "\n"
                )

        return Response(generate_hint_stream(), content_type="text/plain")

    except Exception as e:
        logger.error(f"Error getting coding hint for {conversation_id}: {str(e)}")
        return json_error(str(e), status=500, code="internal_error")


@conversations_bp.route("/get_full_solution/<conversation_id>", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def get_full_solution_endpoint(conversation_id: str):
    """Get a complete solution based on current context and code (streaming response)."""

    keys = keyParser(session)
    state = get_state()

    try:
        user_email = session.get("email")
        if not checkConversationExists(
            user_email, conversation_id, users_dir=state.users_dir
        ):
            logger.warning(
                f"User {user_email} attempted to access conversation {conversation_id} without permission"
            )
            return json_error(
                "Conversation not found or access denied",
                status=404,
                code="conversation_not_found",
            )

        data = request.get_json() or {}
        current_code = data.get("current_code", "")
        context_text = data.get("context", "")

        conversation = get_conversation_with_keys(
            state, conversation_id=conversation_id, keys=keys
        )
        conversation_history = conversation.get_conversation_history()

        from base import get_full_solution_code

        def generate_solution_stream():
            try:
                yield (
                    json.dumps(
                        {
                            "text": "",
                            "status": "Analyzing problem and generating complete solution...",
                            "conversation_id": conversation_id,
                            "type": "solution",
                        }
                    )
                    + "\n"
                )

                solution_generator = get_full_solution_code(
                    context_text,
                    conversation_history,
                    current_code,
                    keys,
                    stream=True,
                    conversation_id=conversation_id,
                )

                accumulated_text = ""
                for chunk in solution_generator:
                    if chunk:
                        accumulated_text += chunk
                        yield (
                            json.dumps(
                                {
                                    "text": chunk,
                                    "status": "Generating complete solution...",
                                    "conversation_id": conversation_id,
                                    "type": "solution",
                                    "accumulated_text": accumulated_text,
                                }
                            )
                            + "\n"
                        )

                yield (
                    json.dumps(
                        {
                            "text": "",
                            "status": "Complete solution generated successfully!",
                            "conversation_id": conversation_id,
                            "type": "solution",
                            "completed": True,
                            "accumulated_text": accumulated_text,
                        }
                    )
                    + "\n"
                )

                logger.info(
                    f"Generated streaming full solution for conversation {conversation_id}, code length: {len(current_code)} chars"
                )

            except Exception as e:
                logger.error(
                    f"Error in solution streaming for {conversation_id}: {str(e)}"
                )
                yield (
                    json.dumps(
                        {
                            "text": "",
                            "status": f"Error: {str(e)}",
                            "conversation_id": conversation_id,
                            "type": "solution",
                            "error": True,
                        }
                    )
                    + "\n"
                )

        return Response(generate_solution_stream(), content_type="text/plain")

    except Exception as e:
        logger.error(f"Error getting full solution for {conversation_id}: {str(e)}")
        return json_error(str(e), status=500, code="internal_error")


@conversations_bp.route("/cancel_doubt_clearing/<conversation_id>", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def cancel_doubt_clearing(conversation_id: str):
    """Cancel an ongoing doubt clearing."""

    from base import doubt_cancellation_requests

    email, _name, _loggedin = get_session_identity()
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    doubt_cancellation_requests[conversation_id] = {
        "cancelled": True,
        "timestamp": time.time(),
    }
    logger.info(
        f"Doubt clearing cancellation requested for conversation {conversation_id} by user {email}"
    )
    return jsonify(
        {"message": "Doubt clearing cancellation requested successfully"}
    ), 200


@conversations_bp.route("/set_flag/<conversation_id>/<flag>", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def set_flag(conversation_id: str, flag: str):
    email, _name, _loggedin = get_session_identity()
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = state.conversation_cache[conversation_id]
    if conversation is None:
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    valid_colors = [
        "red",
        "blue",
        "green",
        "yellow",
        "orange",
        "purple",
        "pink",
        "cyan",
        "magenta",
        "lime",
        "indigo",
        "teal",
        "brown",
        "gray",
        "black",
        "white",
    ]

    if flag is not None and flag.strip().lower() == "none":
        conversation.flag = None
        # Cross-conversation search: flag cleared
        try:
            index = state.cross_conversation_index
            if index:
                index.update_metadata(conversation)
        except Exception:
            pass
        return jsonify({"message": "Flag cleared successfully"}), 200

    assert (
        flag is not None
        and len(flag.strip()) > 0
        and flag.strip().lower() in valid_colors
    )
    conversation.flag = flag.strip().lower()
    # Cross-conversation search: flag set
    try:
        index = state.cross_conversation_index
        if index:
            index.update_metadata(conversation)
    except Exception:
        pass
    return jsonify({"message": "Flag set successfully"}), 200


@conversations_bp.route("/archive_conversation/<conversation_id>", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def archive_conversation(conversation_id: str):
    email, _name, _loggedin = get_session_identity()
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation = state.conversation_cache[conversation_id]
    if conversation is None:
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    new_archived = not conversation.archived
    conversation._archived = new_archived
    if new_archived:
        conversation._archive_source = "manual"
    else:
        if getattr(conversation, "_archive_source", None) == "auto":
            conversation._auto_archive_exempt = True
        conversation._archive_source = None
    conversation.save_local()
    return jsonify({"success": True, "archived": new_archived}), 200


@conversations_bp.route("/get_auto_archive_setting", methods=["GET"])
@limiter.limit("100 per minute")
@login_required
def get_auto_archive_setting():
    """Get user's auto_archive_grace_days setting from user_preferences JSON."""
    email, _name, _loggedin = get_session_identity()
    state = get_state()
    from database.users import getUserFromUserDetailsTable
    user = getUserFromUserDetailsTable(email, users_dir=state.users_dir, logger=logger)
    grace_days = 90  # default
    if user and user.get("user_preferences"):
        try:
            prefs = json.loads(user["user_preferences"])
            if isinstance(prefs, dict):
                grace_days = prefs.get("auto_archive_grace_days", 90)
        except (json.JSONDecodeError, TypeError):
            pass
    return jsonify({"auto_archive_grace_days": grace_days})


@conversations_bp.route("/set_auto_archive_setting", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def set_auto_archive_setting():
    """Set user's auto_archive_grace_days in user_preferences JSON."""
    email, _name, _loggedin = get_session_identity()
    state = get_state()
    from database.users import getUserFromUserDetailsTable, updateUserInfoInUserDetailsTable
    value = request.json.get("auto_archive_grace_days", 90) if request.is_json else 90
    if value not in (0, 30, 60, 90, 180):
        value = 90
    user = getUserFromUserDetailsTable(email, users_dir=state.users_dir, logger=logger)
    prefs = {}
    if user and user.get("user_preferences"):
        try:
            prefs = json.loads(user["user_preferences"])
            if not isinstance(prefs, dict):
                prefs = {}
        except (json.JSONDecodeError, TypeError):
            prefs = {}
    prefs["auto_archive_grace_days"] = value
    updateUserInfoInUserDetailsTable(email, user_preferences=json.dumps(prefs), users_dir=state.users_dir, logger=logger)
    return jsonify({"success": True, "auto_archive_grace_days": value})


@conversations_bp.route("/auto_archive_all/<domain>", methods=["POST"])
@limiter.limit("5 per minute")
@login_required
def auto_archive_all(domain: str):
    """Mass archive all stale conversations (no cap). Returns count + IDs."""
    domain = domain.strip().lower()
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    state = get_state()

    from database.users import getUserFromUserDetailsTable
    user = getUserFromUserDetailsTable(email, users_dir=state.users_dir, logger=logger)
    grace_days = 90
    if user and user.get("user_preferences"):
        try:
            prefs = json.loads(user["user_preferences"])
            if isinstance(prefs, dict):
                grace_days = prefs.get("auto_archive_grace_days", 90)
        except (json.JSONDecodeError, TypeError):
            pass
    if grace_days <= 0:
        return jsonify({"success": True, "count": 0, "archived_ids": []})

    conv_db = getCoversationsForUser(email, domain, users_dir=state.users_dir)
    conversations = [state.conversation_cache.get(c[1]) for c in conv_db]
    conversations = [c for c in conversations if c is not None and c.domain == domain and not c.archived and not c.stateless]

    # Reuse _run_auto_archival logic but with no cap
    from database.pinned_messages import get_pinned_messages as db_get_pins
    from database.similarity_cache import get_all_cached, upsert_cache
    from utils.auto_archival import compute_staleness
    from utils.text_similarity import tokenize, compute_title_summary_hash

    now = datetime.now()
    pinned_conv_ids = set()
    for c in conversations:
        try:
            if db_get_pins(c.conversation_id, users_dir=state.users_dir):
                pinned_conv_ids.add(c.conversation_id)
        except Exception:
            pass

    conv_data = []
    for c in conversations:
        try:
            meta = c.get_metadata()
            msg_count = len(c.get_message_list())
            conv_data.append((c, meta, msg_count))
        except Exception:
            continue

    all_conv_ids = [c.conversation_id for c in conversations]
    cache_map = get_all_cached(all_conv_ids, users_dir=state.users_dir)

    # Update cache
    for c, meta, _ in conv_data:
        title = meta.get("title", "")
        summary = meta.get("summary_till_now", "")
        current_hash = compute_title_summary_hash(title, summary)
        cached = cache_map.get(c.conversation_id)
        if cached is None or cached.get("title_summary_hash") != current_hash:
            tokens = tokenize(title + " " + (summary or "")[:200])
            upsert_cache(c.conversation_id, current_hash, bm25_tokens=tokens, users_dir=state.users_dir)
            cache_map[c.conversation_id] = {"conversation_id": c.conversation_id, "title_summary_hash": current_hash, "bm25_tokens": tokens, "embedding": cached.get("embedding") if cached else None}

    all_conv_tokens = []
    for c, meta, _ in conv_data:
        cached = cache_map.get(c.conversation_id, {})
        lu_str = meta.get("last_updated", "")
        try:
            lu = datetime.strptime(lu_str, "%Y-%m-%d %H:%M:%S") if lu_str else now
        except ValueError:
            lu = now
        all_conv_tokens.append((c.conversation_id, cached.get("bm25_tokens", []), lu, cached.get("embedding")))

    archived_ids = []
    archived_convs = []
    # Pre-filter: only score conversations past grace/4 (same as incremental pass)
    for c, meta, msg_count in conv_data:
        lu_str = meta.get("last_updated", "")
        lo_str = meta.get("last_opened_at")
        try:
            lu = datetime.strptime(lu_str, "%Y-%m-%d %H:%M:%S") if lu_str else now
        except ValueError:
            lu = now
        lo = lu if lo_str is None else lu  # fall back to last_updated
        if lo_str:
            try:
                lo = datetime.strptime(lo_str, "%Y-%m-%d %H:%M:%S") if isinstance(lo_str, str) else lo_str
            except (ValueError, TypeError):
                lo = lu
        age = (now - max(lu, lo)).days
        if age <= grace_days / 4:
            continue
        is_stale, reason = compute_staleness(meta, msg_count, all_conv_tokens, cache_map, pinned_conv_ids, grace_days=grace_days, now=now)
        if is_stale:
            c._archived = True
            c._archive_source = "auto"
            archived_convs.append(c)
            archived_ids.append(c.conversation_id)
            logger.info("Mass auto-archived %s: %s", c.conversation_id, reason)

    for c in archived_convs:
        c.save_local()

    return jsonify({"success": True, "count": len(archived_ids), "archived_ids": archived_ids})


@conversations_bp.route("/pin_message/<conversation_id>/<message_id>", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def pin_message(conversation_id: str, message_id: str):
    email, _name, _loggedin = get_session_identity()
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    from database.pinned_messages import pin_message as db_pin, unpin_message as db_unpin, get_pinned_messages as db_get

    # Toggle: if already pinned, unpin
    existing = db_get(conversation_id=conversation_id, users_dir=state.users_dir)
    is_pinned = any(p["message_id"] == message_id for p in existing)

    if is_pinned:
        db_unpin(conversation_id=conversation_id, message_id=message_id, users_dir=state.users_dir)
        return jsonify({"success": True, "pinned": False}), 200

    # Get preview from conversation
    conversation = state.conversation_cache[conversation_id]
    preview = ""
    if conversation:
        for msg in conversation.conversation_history:
            if msg.get("message_id") == message_id:
                preview = (msg.get("text") or "")[:200]
                break

    db_pin(conversation_id=conversation_id, message_id=message_id, user_email=email, preview=preview, users_dir=state.users_dir)
    return jsonify({"success": True, "pinned": True}), 200


@conversations_bp.route("/get_pinned_messages/<conversation_id>", methods=["GET"])
@limiter.limit("100 per minute")
@login_required
def get_pinned_messages(conversation_id: str):
    email, _name, _loggedin = get_session_identity()
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    from database.pinned_messages import get_pinned_messages as db_get
    pins = db_get(conversation_id=conversation_id, users_dir=state.users_dir)
    return jsonify({"success": True, "pinned_messages": pins}), 200


def _create_conversation_simple(
    domain: str, workspace_id: str | None = None
) -> Conversation:
    """
    Create and persist a new conversation, then return the Conversation object.

    This mirrors legacy `server.py:create_conversation_simple`, but uses `AppState` for paths
    and passes `users_dir` explicitly into DB helpers.
    """

    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    from base import get_embedding_model

    state = get_state()
    conversation_id = (
        email + "_" + "".join(secrets.choice(_ALPHABET) for _ in range(36))
    )
    conversation = Conversation(
        email,
        openai_embed=get_embedding_model(keys),
        storage=state.conversation_folder,
        conversation_id=conversation_id,
        domain=domain,
    )
    conversation = attach_keys(conversation, keys)
    addConversation(
        email,
        conversation.conversation_id,
        workspace_id,
        domain,
        users_dir=state.users_dir,
    )
    conversation.save_local()
    # Cross-conversation search: new conversation created
    try:
        index = state.cross_conversation_index
        if index:
            index.update_metadata(conversation)
    except Exception:
        pass
    return conversation


@conversations_bp.route("/list_conversation_by_user/<domain>", methods=["GET"])
@limiter.limit("500 per minute")
@login_required
def list_conversation_by_user(domain: str):
    # TODO: sort by last_updated (legacy note)
    domain = domain.strip().lower()
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)

    state = get_state()
    _last_n_conversations = request.args.get(
        "last_n_conversations", 10
    )  # preserved; unused (legacy)

    conv_db = getCoversationsForUser(email, domain, users_dir=state.users_dir)
    conversation_ids = [c[1] for c in conv_db]
    conversations = []
    orphaned_ids = []
    for conversation_id in conversation_ids:
        try:
            conv = state.conversation_cache[conversation_id]
            conversations.append(conv)
        except Exception as _load_err:
            logger.warning(
                f"Skipping conversation {conversation_id!r} — failed to load: {_load_err}"
            )
            orphaned_ids.append(conversation_id)
    if orphaned_ids:
        try:
            cleanup_deleted_conversations(orphaned_ids, users_dir=state.users_dir, logger=logger)
            logger.info(f"Auto-cleaned {len(orphaned_ids)} orphaned conversation DB rows")
        except Exception as _cleanup_err:
            logger.warning(f"Failed to cleanup orphaned rows: {_cleanup_err}")
    conversation_id_to_workspace_id = {
        c[1]: {"workspace_id": c[4], "workspace_name": c[5]}
        for c in conv_db
        if c[4] is not None
    }

    # Grace period: only delete stateless conversations older than 5 minutes.
    # This prevents a race condition where a temporary conversation is deleted
    # while the UI is still trying to load it (e.g. multi-tab scenarios).
    GRACE_PERIOD_SECONDS = 300  # 5 minutes
    now_ts = time.time()
    stateless_conversations = [
        c for c in conversations if c is not None and c.stateless
    ]
    expired_stateless = []
    for conv in stateless_conversations:
        try:
            memory = conv.get_field("memory")
            last_updated_str = memory.get("last_updated", "")
            if last_updated_str:
                from datetime import datetime as _dt
                lu = _dt.strptime(str(last_updated_str), "%Y-%m-%d %H:%M:%S")
                age_seconds = now_ts - lu.timestamp()
                if age_seconds < GRACE_PERIOD_SECONDS:
                    continue  # Skip recently active stateless conversations
        except Exception:
            pass  # If we can't parse the date, delete it anyway
        expired_stateless.append(conv)

    deleted_temporary_ids = [c.conversation_id for c in expired_stateless]
    for conversation in expired_stateless:
        removeUserFromConversation(
            email, conversation.conversation_id, users_dir=state.users_dir
        )
        del state.conversation_cache[conversation.conversation_id]
        deleteConversationForUser(
            email, conversation.conversation_id, users_dir=state.users_dir
        )
        conversation.delete_conversation()

    none_conversation_ids: list[str] = []
    for conversation_id, conversation in zip(conversation_ids, conversations):
        if conversation is None:
            removeUserFromConversation(
                email, conversation_id, users_dir=state.users_dir
            )
            del state.conversation_cache[conversation_id]
            deleteConversationForUser(email, conversation_id, users_dir=state.users_dir)
            none_conversation_ids.append(conversation_id)

    cleanup_deleted_conversations(
        none_conversation_ids + deleted_temporary_ids,
        users_dir=state.users_dir,
        logger=logger,
    )

    conversations = [c for c in conversations if c is not None and c.domain == domain and c.conversation_id not in deleted_temporary_ids]

    # --- Auto-archival pass (throttled to once per hour) ---
    auto_archived_ids = []
    grace_days = 90
    from database.users import getUserFromUserDetailsTable
    _user_row = getUserFromUserDetailsTable(email, users_dir=state.users_dir, logger=logger)
    if _user_row and _user_row.get("user_preferences"):
        try:
            _uprefs = json.loads(_user_row["user_preferences"])
            if isinstance(_uprefs, dict):
                grace_days = _uprefs.get("auto_archive_grace_days", 90)
        except (json.JSONDecodeError, TypeError):
            pass

    if grace_days > 0 and (time.time() - _last_auto_archive_run) >= 3600:
        auto_archived_ids = _run_auto_archival(conversations, grace_days, state.users_dir)

    include_archived = request.args.get("include_archived", "false").lower() == "true"
    if not include_archived:
        conversations = [c for c in conversations if not c.archived]
    conversations = [set_keys_on_docs(c, keys) for c in conversations]
    data = [[c.get_metadata(), c] for c in conversations]
    for metadata, conversation in data:
        assert conversation.conversation_id in conversation_id_to_workspace_id, (
            f"Conversation {conversation.conversation_id} not found in conversation_id_to_workspace_id"
        )
        metadata["workspace_id"] = conversation_id_to_workspace_id[
            conversation.conversation_id
        ]["workspace_id"]
        metadata["workspace_name"] = conversation_id_to_workspace_id[
            conversation.conversation_id
        ]["workspace_name"]
        metadata["domain"] = conversation.domain

        # Lazy backfill: generate conversation_friendly_id for old conversations
        if not metadata.get("conversation_friendly_id"):
            try:
                from conversation_reference_utils import (
                    generate_conversation_friendly_id,
                )
                from database.conversations import (
                    setConversationFriendlyId,
                    conversationFriendlyIdExists,
                )

                title = metadata.get("title", "")
                last_updated = metadata.get("last_updated", "")
                if title and last_updated:
                    candidate = generate_conversation_friendly_id(title, last_updated)
                    # Simple collision check (no retry in backfill — keep it fast)
                    if conversationFriendlyIdExists(
                        users_dir=state.users_dir,
                        user_email=email,
                        conversation_friendly_id=candidate,
                    ):
                        candidate = generate_conversation_friendly_id(
                            title + conversation.conversation_id[:8], last_updated
                        )
                    # Store in conversation memory
                    memory = conversation.get_field("memory")
                    memory["conversation_friendly_id"] = candidate
                    if "created_at" not in memory:
                        memory["created_at"] = last_updated
                    conversation.set_field("memory", memory)
                    conversation.save_local()
                    # Store in DB
                    setConversationFriendlyId(
                        users_dir=state.users_dir,
                        user_email=email,
                        conversation_id=conversation.conversation_id,
                        conversation_friendly_id=candidate,
                    )
                    metadata["conversation_friendly_id"] = candidate
            except Exception:
                logger.exception(
                    "Failed to backfill conversation_friendly_id for %s",
                    metadata.get("conversation_id", "unknown"),
                )

    sorted_data_reverse = sorted(data, key=lambda x: x[0]["last_updated"], reverse=True)

    if (
        len(sorted_data_reverse) > 0
        and len(sorted_data_reverse[0][0]["summary_till_now"].strip()) > 0
    ):
        sorted_data_reverse = sorted(
            sorted_data_reverse, key=lambda x: len(x[0]["summary_till_now"].strip())
        )
        if (
            sorted_data_reverse[0][0]["summary_till_now"].strip() == ""
            and len(sorted_data_reverse[0][1].get_message_list()) == 0
        ):
            new_conversation = sorted_data_reverse[0][1]
            sorted_data_reverse = sorted_data_reverse[1:]
            sorted_data_reverse = sorted(
                sorted_data_reverse, key=lambda x: x[0]["last_updated"], reverse=True
            )
        else:
            new_conversation = _create_conversation_simple(domain)
        sorted_data_reverse.insert(
            0, [new_conversation.get_metadata(), new_conversation]
        )

    if len(sorted_data_reverse) == 0:
        new_conversation = _create_conversation_simple(domain)
        sorted_data_reverse.insert(
            0, [new_conversation.get_metadata(), new_conversation]
        )

    sorted_metadata_reverse = [sd[0] for sd in sorted_data_reverse]
    return jsonify({
        "conversations": sorted_metadata_reverse,
        "deleted_temporary_ids": deleted_temporary_ids,
        "auto_archived_ids": auto_archived_ids,
    })


@conversations_bp.route(
    "/create_conversation/<domain>/", defaults={"workspace_id": None}, methods=["POST"]
)
@conversations_bp.route(
    "/create_conversation/<domain>/<workspace_id>", methods=["POST"]
)
@limiter.limit("500 per minute")
@login_required
def create_conversation(domain: str, workspace_id: str | None = None):
    domain = domain.strip().lower()
    state = get_state()

    conversation = _create_conversation_simple(domain, workspace_id)
    data = conversation.get_metadata()
    data["workspace"] = getWorkspaceForConversation(
        users_dir=state.users_dir, conversation_id=conversation.conversation_id
    )
    return jsonify(data)


@conversations_bp.route("/create_temporary_conversation/<domain>", methods=["POST"])
@limiter.limit("500 per minute")
@login_required
def create_temporary_conversation(domain: str):
    """
    Atomically create a temporary (stateless) conversation and return
    the full workspace + conversation list in a single response.

    This replaces the old three-call dance:
        POST /create_conversation  →  GET /list_conversation_by_user  →  DELETE /make_conversation_stateless

    Ordering (critical for correctness):
        1. Clean up old stateless/orphaned conversations
        2. Create new conversation in specified workspace
        3. Mark it stateless
        4. Build fresh conversation + workspace lists
           (the new stateless conversation is included because
           cleanup already ran — it won't be deleted again until
           the next ``list_conversation_by_user`` call)

    Request JSON body
    -----------------
    workspace_id : str, optional
        Target workspace for the new conversation.  When omitted the
        conversation is placed in the user's default workspace.

    Returns
    -------
    JSON object with keys:
        conversation  : dict  – metadata of the newly created conversation
        conversations : list  – full conversation list for the domain
        workspaces    : list  – full workspace list for the domain
    """
    domain = domain.strip().lower()
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    state = get_state()

    body = request.get_json(silent=True) or {}
    workspace_id = body.get("workspace_id")

    # ------------------------------------------------------------------
    # Phase 1: Clean up old stateless and orphaned conversations
    # ------------------------------------------------------------------
    conv_db = getCoversationsForUser(email, domain, users_dir=state.users_dir)
    conversation_ids = [c[1] for c in conv_db]
    cached_conversations = []
    orphaned_ids = []
    for cid in conversation_ids:
        try:
            cached_conversations.append(state.conversation_cache[cid])
        except Exception:
            cached_conversations.append(None)
            orphaned_ids.append(cid)

    stale_ids: list[str] = list(orphaned_ids)
    GRACE_PERIOD_SECONDS = 300  # 5 minutes

    for conv in cached_conversations:
        if conv is not None and conv.stateless:
            # Respect grace period — don't delete recently active stateless convs
            try:
                memory = conv.get_field("memory")
                last_updated_str = memory.get("last_updated", "")
                if last_updated_str:
                    from datetime import datetime as _dt
                    lu = _dt.strptime(str(last_updated_str), "%Y-%m-%d %H:%M:%S")
                    if time.time() - lu.timestamp() < GRACE_PERIOD_SECONDS:
                        continue
            except Exception:
                pass
            stale_ids.append(conv.conversation_id)
            removeUserFromConversation(
                email, conv.conversation_id, users_dir=state.users_dir
            )
            del state.conversation_cache[conv.conversation_id]
            deleteConversationForUser(
                email, conv.conversation_id, users_dir=state.users_dir
            )
            conv.delete_conversation()

    for cid, conv in zip(conversation_ids, cached_conversations):
        if conv is None and cid not in orphaned_ids:
            stale_ids.append(cid)
            removeUserFromConversation(email, cid, users_dir=state.users_dir)
            if cid in state.conversation_cache:
                del state.conversation_cache[cid]
            deleteConversationForUser(email, cid, users_dir=state.users_dir)

    if stale_ids:
        cleanup_deleted_conversations(
            stale_ids, users_dir=state.users_dir, logger=logger
        )

    # ------------------------------------------------------------------
    # Phase 2: Create new conversation and mark stateless
    # ------------------------------------------------------------------
    new_conversation = _create_conversation_simple(domain, workspace_id)
    new_conversation.make_stateless()

    # Place in cache so subsequent accesses don't re-load from disk
    state.conversation_cache[new_conversation.conversation_id] = new_conversation

    new_conv_metadata = new_conversation.get_metadata()
    ws_info = getWorkspaceForConversation(
        users_dir=state.users_dir,
        conversation_id=new_conversation.conversation_id,
    )
    new_conv_metadata["workspace_id"] = (
        ws_info["workspace_id"] if ws_info else workspace_id
    )
    new_conv_metadata["workspace_name"] = ws_info.get("workspace_name", "") if ws_info else ""
    new_conv_metadata["domain"] = domain

    # ------------------------------------------------------------------
    # Phase 3: Build fresh conversation list
    # ------------------------------------------------------------------
    conv_db_fresh = getCoversationsForUser(email, domain, users_dir=state.users_dir)
    fresh_ids = [c[1] for c in conv_db_fresh]
    fresh_convs = [state.conversation_cache[cid] for cid in fresh_ids]
    fresh_ws_map = {
        c[1]: {"workspace_id": c[4], "workspace_name": c[5]}
        for c in conv_db_fresh
        if c[4] is not None
    }

    valid_convs = [c for c in fresh_convs if c is not None and c.domain == domain]
    valid_convs = [set_keys_on_docs(c, keys) for c in valid_convs]

    conv_list: list[dict] = []
    for conv in valid_convs:
        meta = conv.get_metadata()
        if conv.conversation_id in fresh_ws_map:
            meta["workspace_id"] = fresh_ws_map[conv.conversation_id]["workspace_id"]
            meta["workspace_name"] = fresh_ws_map[conv.conversation_id][
                "workspace_name"
            ]
        meta["domain"] = conv.domain
        conv_list.append(meta)

    conv_list.sort(key=lambda x: x.get("last_updated", ""), reverse=True)

    # ------------------------------------------------------------------
    # Phase 4: Workspace list
    # ------------------------------------------------------------------
    workspaces = load_workspaces_for_user(
        users_dir=state.users_dir, user_email=email, domain=domain
    )

    return jsonify(
        {
            "conversation": new_conv_metadata,
            "conversations": conv_list,
            "workspaces": workspaces,
        }
    )


@conversations_bp.route("/shared_chat/<conversation_id>", methods=["GET"])
@limiter.limit("100 per minute")
def shared_chat(conversation_id: str):
    state = get_state()
    conversation_ids = [
        c[1] for c in getConversationById(conversation_id, users_dir=state.users_dir)
    ]
    if conversation_id not in conversation_ids:
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation: Conversation = state.conversation_cache[conversation_id]
    data = conversation.get_metadata()
    messages = conversation.get_message_list()
    if conversation:
        docs: List[DocIndex] = conversation.get_uploaded_documents(readonly=True)
        docs = [d.get_short_info() for d in docs]
        return jsonify({"messages": messages, "documents": docs, "metadata": data})

    return jsonify({"messages": messages, "metadata": data, "documents": []})


@conversations_bp.route("/send_message/<conversation_id>", methods=["POST"])
@limiter.limit("50 per minute")
@login_required
def send_message(conversation_id: str):
    """
    Stream an assistant response for the provided user query payload.

    Preserves the legacy queue-based streaming behavior from `server.py`, but
    uses `AppState` and explicit `users_dir` for DB access.
    """

    keys = keyParser(session)
    email, _name, _loggedin = get_session_identity()
    state = get_state()

    user_details = getUserFromUserDetailsTable(
        email, users_dir=state.users_dir, logger=logger
    )

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    conversation: Conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )

    query = request.json

    # Detect extension source and apply sensible defaults.
    # The extension sends a simplified payload compared to the web UI; many
    # checkboxes/search/links fields may be missing.  Setting defaults here
    # prevents KeyError in Conversation.reply().
    if isinstance(query, dict) and query.get("source") == "extension":
        checkboxes = query.setdefault("checkboxes", {})
        checkboxes.setdefault("persist_or_not", True)
        checkboxes.setdefault("provide_detailed_answers", 2)
        checkboxes.setdefault("use_pkb", True)
        checkboxes.setdefault("enable_previous_messages", "10")
        checkboxes.setdefault("perform_web_search", False)
        checkboxes.setdefault("googleScholar", False)
        checkboxes.setdefault("ppt_answer", False)
        checkboxes.setdefault("preamble_options", [])
        query.setdefault("search", [])
        query.setdefault("links", [])

    logger.warning(
        "[send_message] received request | conv=%s | t=%.2fs",
        conversation_id,
        time.time(),
    )

    # Inject conversation-pinned claim IDs into the query (for Deliberate Memory Attachment)
    conv_pinned_ids = list(state.pinned_claims.get(conversation_id, set()))
    if conv_pinned_ids:
        query["conversation_pinned_claim_ids"] = conv_pinned_ids

    # Inject cross-conversation reference resolution dependencies
    query["_users_dir"] = state.users_dir
    query["_user_email"] = email
    query["_global_docs_dir"] = state.global_docs_dir
    query["_conversation_loader"] = lambda cid: state.conversation_cache[cid]
    query["_tool_response_waiter"] = wait_for_tool_response

    from queue import Queue
    from flask import copy_current_request_context

    response_queue: Queue = Queue()

    @copy_current_request_context
    def generate_response():
        logger.warning(
            "[send_message] generate_response start | conv=%s | t=%.2fs",
            conversation_id,
            time.time(),
        )
        # Capture message_id + answer text from the stream so we can create auto-takeaways
        # immediately after streaming completes (without waiting for async persistence).
        captured_response_message_id: str | None = None
        captured_answer_parts: list[str] = []
        answer_done = False

        logger.warning(
            "[send_message] starting Conversation.__call__ | conv=%s | t=%.2fs",
            conversation_id,
            time.time(),
        )
        try:
            for chunk in conversation(query, user_details):
                # `Conversation.__call__` yields JSON-lines: json.dumps(dict) + "\n"
                # We parse best-effort to extract `message_ids` and reconstruct the same answer
                # that gets persisted (i.e., stop collecting once status flips to "saving answer ...").
                try:
                    if isinstance(chunk, str):
                        parsed = json.loads(chunk.strip())
                        if isinstance(parsed, dict):
                            if not captured_response_message_id:
                                mids = parsed.get("message_ids") or {}
                                if isinstance(mids, dict) and isinstance(
                                    mids.get("response_message_id"), str
                                ):
                                    captured_response_message_id = mids[
                                        "response_message_id"
                                    ]

                            status = str(parsed.get("status", "") or "").lower()
                            if "saving answer" in status:
                                answer_done = True

                            if not answer_done:
                                txt = parsed.get("text", "")
                                if isinstance(txt, str) and txt:
                                    captured_answer_parts.append(txt)
                except Exception:
                    # Never let analytics/capture interfere with streaming.
                    pass

                response_queue.put(chunk)
        except Exception as gen_err:
            # The reply generator raised. Without this guard the END sentinel
            # below would never be queued and run_queue() would hang forever,
            # leaving the client stuck with no error. Surface it as a chunk.
            logger.error(
                "[send_message] reply generator failed | conv=%s | err=%s\n%s",
                conversation_id,
                gen_err,
                traceback.format_exc(),
            )
            try:
                response_queue.put(
                    json.dumps(
                        {
                            "text": f"\n\n**Error: response generation failed — {gen_err}**",
                            "status": "Error in response generation",
                        }
                    )
                    + "\n"
                )
            except Exception:
                pass
        logger.warning(
            "[send_message] Conversation.__call__ done | conv=%s | t=%.2fs",
            conversation_id,
            time.time(),
        )
        response_queue.put("<--END-->")
        conversation.clear_cancellation()
        # Post-stream background work (must never block streaming / user experience)
        try:
            persist_or_not = bool(
                query.get("checkboxes", {}).get("persist_or_not", True)
            )
            auto_doubts_enabled = bool(
                query.get("checkboxes", {}).get("auto_doubts_enabled", True)
            )
            if persist_or_not and auto_doubts_enabled:
                captured_answer_text = (
                    "".join(captured_answer_parts).strip()
                    if captured_answer_parts
                    else ""
                )
                _auto_doubt_kwargs = dict(
                    message=query["messageText"],
                    conversation=conversation,
                    conversation_id=conversation_id,
                    user_email=email,
                    users_dir=state.users_dir,
                    message_id=captured_response_message_id,
                    answer_text=captured_answer_text,
                )
                # Category → function mapping for selective auto-doubts
                _AUTO_DOUBT_DISPATCH = {
                    "takeaways": _create_auto_takeaways_doubt_for_last_assistant_message,
                    "maximize_learning": _create_maximize_learning_doubt,
                    "challenge_verify": _create_challenge_and_verify_doubt,
                    "foundations_practice": _create_foundations_and_practice_doubt,
                    "answer_questions": _create_answer_raised_questions_doubt,
                }
                # Read per-conversation setting; None means all
                _conv_settings = conversation.get_conversation_settings() or {}
                _enabled_categories = _conv_settings.get("auto_doubt_categories")
                for _cat, _func in _AUTO_DOUBT_DISPATCH.items():
                    if _enabled_categories is None or _cat in _enabled_categories:
                        get_async_future(_func, **_auto_doubt_kwargs)
        except Exception as e:
            logger.error(
                f"[send_message] Failed to schedule auto-doubts: {e}", exc_info=True
            )

    _future = get_async_future(generate_response)

    def run_queue():
        logger.warning(
            "[send_message] run_queue start | conv=%s | t=%.2fs",
            conversation_id,
            time.time(),
        )
        try:
            while True:
                chunk = response_queue.get()
                if chunk == "<--END-->":
                    logger.warning(
                        "[send_message] run_queue end sentinel | conv=%s | t=%.2fs",
                        conversation_id,
                        time.time(),
                    )
                    break
                yield chunk
        except GeneratorExit:
            # Client disconnected - we'll still finish our background task
            print("Client disconnected, but continuing background processing")

    return Response(run_queue(), content_type="text/plain")


def _extract_first_json_object(text: str) -> dict | None:
    """
    Best-effort extractor for a single JSON object from LLM output.

    Why this exists:
    - Models sometimes wrap JSON in code fences or add extra commentary.
    - Clarifications must be **fail-open**: parsing errors should not block sends.

    Returns
    -------
    dict | None
        Parsed JSON object if extraction+parsing succeeded, else None.
    """
    if not isinstance(text, str) or not text.strip():
        return None
    # Strip common code fences.
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = cleaned.strip("`").strip()
    start = cleaned.find("{")
    end = cleaned.rfind("}")
    if start == -1 or end == -1 or end <= start:
        return None
    try:
        obj = json.loads(cleaned[start : end + 1])
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def _normalize_clarifications_payload(raw: dict) -> dict:
    """
    Normalize and bound the clarifications payload to a safe, UI-friendly schema.

    Output schema (always safe):
    - needs_clarification: bool
    - questions: list[{id, prompt, options: list[{id, label}]}] (0..3 questions; 2..5 options each)
    """
    needs = bool(raw.get("needs_clarification", False))
    questions_in = (
        raw.get("questions", []) if isinstance(raw.get("questions", []), list) else []
    )

    questions_out: list[dict] = []
    for qi, q in enumerate(questions_in[:3], start=1):
        if not isinstance(q, dict):
            continue
        prompt = q.get("prompt") or q.get("question") or ""
        if not isinstance(prompt, str) or not prompt.strip():
            continue

        options_in = q.get("options", [])
        if not isinstance(options_in, list):
            options_in = []

        options_out: list[dict] = []
        for oi, opt in enumerate(options_in[:5], start=1):
            if isinstance(opt, dict):
                label = opt.get("label") or opt.get("text") or opt.get("value") or ""
            else:
                label = str(opt)
            if isinstance(label, str) and label.strip():
                options_out.append({"id": f"q{qi}_opt{oi}", "label": label.strip()})

        # Require at least 2 options to be a usable MCQ.
        if len(options_out) < 2:
            continue

        questions_out.append(
            {"id": f"q{qi}", "prompt": prompt.strip(), "options": options_out}
        )

    if not questions_out:
        needs = False

    return {"needs_clarification": needs, "questions": questions_out}




@conversations_bp.route("/tool_response/<conversation_id>/<tool_id>", methods=["POST"])
@limiter.limit("60 per minute")
@login_required
def submit_tool_response(conversation_id, tool_id):
    """Receive user's response for an interactive tool call.
    
    Called by the UI (ToolCallManager.submitToolResponse) when the user
    answers a tool's questions (e.g., clarification MCQ). The response
    unblocks the background thread running the agentic tool loop.
    
    Request body: {"response": { ... user's response data ... }}
    
    Returns 200 on success, 404 if no pending request for this tool_id,
    400 on malformed request.
    """
    try:
        data = request.get_json()
        if not data or "response" not in data:
            return jsonify({"error": "Missing 'response' field"}), 400
        
        response_data = data["response"]
        
        with _tool_response_lock:
            event = _tool_response_events.get(tool_id)
            if event is None:
                return jsonify({"error": f"No pending tool request for tool_id: {tool_id}"}), 404
            
            _tool_response_data[tool_id] = response_data
            event.set()  # Unblock the waiting background thread
        
        return jsonify({"status": "ok"}), 200
        
    except Exception as e:
        logger.error(f"Error in submit_tool_response: {e}")
        return jsonify({"error": str(e)}), 500


@conversations_bp.route("/clarify_intent/<conversation_id>", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def clarify_intent(conversation_id: str):
    """
    Return up to 3 MCQ-style clarification questions for a draft user message.

    Purpose
    -------
    This endpoint is called by the UI *before* sending a message, when the user
    clicks a manual “Clarify” button. It uses an LLM to propose 0–3 MCQs that
    clarify intent/objective when the message is ambiguous.

    Contract
    --------
    Request JSON:
    - messageText: str (required)
    - checkboxes: dict (optional)
    - links: list|str (optional)
    - search: list|str (optional)

    Response JSON:
    - needs_clarification: bool
    - questions: list[ {id, prompt, options: list[{id, label}]} ]  # length 0..3

    Failure behavior (important)
    ----------------------------
    Fail-open: on any LLM/parse error, we return `{needs_clarification:false, questions:[]}`.
    """
    keys = keyParser(session)
    email, _name, _loggedin = get_session_identity()
    state = get_state()

    payload = request.json if request.is_json and request.json else {}
    message_text = payload.get("messageText")
    if not isinstance(message_text, str) or not message_text.strip():
        return json_error("messageText is required", status=400, code="invalid_request")
    force_clarify = bool(payload.get("forceClarify", False))

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error(
            "Conversation not found", status=404, code="conversation_not_found"
        )

    # We include light context (summary + last turn) so the model can avoid asking
    # clarifications that are already obvious from the chat.
    conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )

    try:
        from call_llm import CallLLm
        from common import VERY_CHEAP_LLM

        # --- Conversation summary ---
        try:
            conversation_summary = (
                conversation.running_summary
                if hasattr(conversation, "running_summary")
                else ""
            )
        except Exception:
            conversation_summary = ""
        conversation_summary = (conversation_summary or "").strip()
        if not conversation_summary:
            conversation_summary = "(No summary available)"
        conversation_summary = conversation_summary[:10_000]
        # --- Recent history: last 3 user+assistant turns ---
        try:
            messages = conversation.get_message_list() or []
        except Exception:
            messages = []
        recent_turns = []
        try:
            pending_user = ""
            pending_asst = ""
            for msg in reversed(messages):
                if not isinstance(msg, dict):
                    continue
                if not pending_asst and msg.get("sender") == "model":
                    pending_asst = " ".join(str(msg.get("text", "") or "").split())[:8_000]
                elif not pending_user and msg.get("sender") == "user":
                    pending_user = " ".join(str(msg.get("text", "") or "").split())[:6_000]
                if pending_user and pending_asst:
                    recent_turns.append((pending_user, pending_asst))
                    pending_user = ""
                    pending_asst = ""
                if len(recent_turns) >= 3:
                    break
            recent_turns.reverse()  # chronological order for the prompt
        except Exception:
            recent_turns = []

        recent_turns_text = "(No recent turns)"
        if recent_turns:
            parts = []
            for i, (u, a) in enumerate(recent_turns, 1):
                parts.append(f"Turn {i}:\n  User: \"{u}\"\n  Assistant: \"{a}\"")
            recent_turns_text = "\n".join(parts)

        # --- PKB context (raw, no LLM summarization) ---
        # _get_pkb_context does its own exception handling and returns "" on any failure.
        pkb_context = ""
        try:
            state = get_state()
            pkb_context = conversation._get_pkb_context(
                user_email=email,
                query=message_text,
                conversation_summary=conversation_summary,
                k=8,
                conversation_id=conversation_id,
                users_dir=state.users_dir,
            )
        except Exception:
            pkb_context = ""
        pkb_context = (pkb_context or "").strip()

        # Build PKB section for prompt (omit entirely if empty to keep prompt clean).
        pkb_section = ""
        if pkb_context:
            pkb_section = (
                "\nPersonal knowledge base (facts about the user — use to personalise questions):\n"
                + pkb_context[:6_000]
            )
        prompt = (
            "You are an intent-clarification assistant. Given a user's draft message"
            " and conversation context, decide if clarifications are needed.\n"
            "\n"
            "Conversation summary:\n"
            f'\'\'\'{ conversation_summary }\'\'\'\n'
            "\n"
            "Recent conversation history (up to last 3 turns, chronological):\n"
            f"{ recent_turns_text }\n"
            f"{ pkb_section }\n"
            "\n"
            "Draft message:\n"
            f'\'\'\'{ message_text.strip() }\'\'\'\n'
            "\n"
            + "Rules:\n"
            + (
                "- The user has explicitly requested clarification questions. You MUST produce 1\u20133 questions.\n"
                "- Do NOT set needs_clarification=false. Always set it to true and always return at least 1 question.\n"
                "- If the draft already seems specific, ask questions that will improve depth or quality (e.g. tone, format, audience, scope).\n"
                if force_clarify else
                "- If the draft is already specific enough to answer, set needs_clarification=false and questions=[].\n"
                + "- Otherwise, propose up to 3 multiple-choice questions to clarify intent/objective.\n"
            )
            + "- Each question must have 2 to 5 options.\n"
            + "- The questions can be generic to clarify the intent of the user's message. Or specific to the conversation context and the user message.\n"
            + "- Use facts from the personal knowledge base to avoid asking things already known about the user.\n"
            + "- Keep questions short and practical.\n"
            + "- Do NOT ask about facts that are already answered by the conversation summary or recent history.\n"
            + "- Output MUST be STRICT JSON only (no markdown, no code fences, no extra text).\n"
            + '- For Free form text option input, Put the option as "Other (please specify)" which when checked will show a text input field to enter the free form text.\n'
            + "\n"
            + "JSON schema:\n"
            + '{\n'
            + '  "needs_clarification": true|false,\n'
            + '  "questions": [\n'
            + '    {\n'
            + '      "prompt": "question text",\n'
            + '      "options": ["option 1", "option 2"]\n'
            + '    }\n'
            + '  ]\n'
            + '}'
        ).strip()

        clarify_model = conversation.get_model_override("clarify_intent_model", VERY_CHEAP_LLM[0])
        llm = CallLLm(keys, model_name=clarify_model, use_gpt4=False, use_16k=False)
        raw = llm(
            prompt,
            images=[],
            temperature=0.2,
            stream=False,
            max_tokens=700,
            system="You produce strict JSON only. No extra commentary.",
        )

        parsed = _extract_first_json_object(raw)
        if not parsed:
            return jsonify({"needs_clarification": False, "questions": []})

        safe = _normalize_clarifications_payload(parsed)
        return jsonify(safe)
    except Exception as e:
        logger.error(f"[clarify_intent] Fail-open due to error: {e}", exc_info=True)
        return jsonify({"needs_clarification": False, "questions": []})


_DOUBT_SECTION_FMT = "\n\nFormat your answer in exactly 3 sections using these markers:\n<tldr>One-sentence summary of the answer</tldr>\n<explanation>Clear explanation (2-4 paragraphs)</explanation>\n<deep_dive>Detailed examples, edge cases, connections, and nuances</deep_dive>"


def _create_auto_takeaways_doubt_for_last_assistant_message(
    *,
    message: str,
    conversation: Conversation,
    conversation_id: str,
    user_email: str,
    users_dir: str,
    message_id: str | None = None,
    answer_text: str | None = None,
) -> None:
    """
    Generate and persist an automatic “Auto takeaways” root doubt for the last assistant message.

    This runs asynchronously after `/send_message` finishes streaming.
    It must be failure-isolated: errors are logged and never propagate.
    """
    try:
        from database.doubts import add_doubt, get_doubts_for_message
        from call_llm import CallLLm
        from common import VERY_CHEAP_LLM

        max_wait_seconds = 120

        # Fast path: if the caller already captured the `response_message_id` and the final
        # assistant answer text from the stream, we can create the doubt immediately (no waiting
        # for async persistence).
        if not (
            isinstance(message_id, str)
            and message_id.strip()
            and isinstance(answer_text, str)
            and answer_text.strip()
        ):
            # Fallback: Persist is async inside Conversation.reply(); wait for the persisted message to exist.
            #
            # Why we may need to wait:
            # - `Conversation.persist_current_turn()` does *multiple* async LLM calls (summary/title + next-question suggestions)
            #   and holds a lock while updating `messages`. On slower models or under load, this can exceed 15s.
            # - This runs in a background thread, so waiting here does not affect streaming UX.
            import time as _time

            message_id = None
            answer_text = None
            poll_interval_seconds = 0.5
            max_polls = int(max_wait_seconds / poll_interval_seconds)
            for _ in range(max_polls):
                try:
                    messages = conversation.get_field("messages") or []
                except Exception:
                    messages = []

                last_assistant = None
                for msg in reversed(messages):
                    if isinstance(msg, dict) and msg.get("sender") == "model":
                        last_assistant = msg
                        break

                if (
                    last_assistant
                    and last_assistant.get("message_id")
                    and last_assistant.get("text")
                ):
                    message_id = last_assistant.get("message_id")
                    answer_text = last_assistant.get("text")
                    break

                _time.sleep(poll_interval_seconds)

        if not message_id or not answer_text:
            logger.info(
                f"[auto_takeaways] Skipping (no persisted assistant message within {max_wait_seconds}s) "
                f"conv={conversation_id}"
            )
            return

        # Dedup: if a root doubt with the same marker exists, do nothing.
        try:
            existing = get_doubts_for_message(
                conversation_id=conversation_id,
                message_id=message_id,
                user_email=user_email,
                users_dir=users_dir,
                logger=logger,
            )
        except Exception:
            existing = []

        for d in existing:
            if isinstance(d, dict) and d.get("doubt_text") == "Auto takeaways":
                return

        answer_trimmed = " ".join(str(answer_text).split())
        answer_trimmed = answer_trimmed[:50_000]
        conversation_summary = (
            conversation.running_summary
            if hasattr(conversation, "running_summary")
            else ""
        )

        takeaways_prompt = f"""
Rewrite the following assistant answer into a short, crisp quick-reference.

Requirements:
- No preamble. Start directly with content.
- Stay strictly on-topic about what the user is asking for; ignore tangents.
- Target 120–250 words.
- Use markdown headings and bullet points.
- Structure:
  Key takeaways and learnings: (4–8 bullets)
  Actionables: (0–5 bullets; only if meaningful)
  Important facts/constraints: (optional; short)
- You can be flexible with the structure if needed.

Conversation context:
\"\"\"{conversation_summary}\"\"\"

User message:
\"\"\"{message}\"\"\"

Assistant answer:
\"\"\"{answer_trimmed}\"\"\"
""".strip()

        llm = CallLLm(
            conversation.get_api_keys(),
            model_name=conversation.get_model_override("auto_doubt_model", VERY_CHEAP_LLM[0]),
            use_gpt4=False,
            use_16k=False,
        )
        takeaways = llm(
            takeaways_prompt,
            images=[],
            temperature=0.2,
            stream=False,
            max_tokens=650,
            system="You write compact, actionable summaries with no preamble.",
        )

        if not isinstance(takeaways, str) or not takeaways.strip():
            return

        add_doubt(
            conversation_id=conversation_id,
            user_email=user_email,
            message_id=message_id,
            doubt_text="Auto takeaways",
            doubt_answer=takeaways.strip(),
            parent_doubt_id=None,
            users_dir=users_dir,
            logger=logger,
        )

        # --- Answer next-question suggestions as child doubts ---
        try:
            import time as _time

            # Wait for next_question_suggestions: initial 10s then check every 1s up to 60s
            suggestions = None
            _time.sleep(10)
            for _ in range(50):  # 50 checks × 1s = 50s more (60s total)
                suggestions = conversation.next_question_suggestions
                if suggestions and len(suggestions) > 0:
                    break
                _time.sleep(1)

            if not suggestions:
                return

            nq_model = conversation.get_model_override("auto_doubt_model", "gemini-flash-3.5-non-reasoning")
            nq_llm = CallLLm(
                conversation.get_api_keys(),
                model_name=nq_model,
                use_gpt4=False,
                use_16k=False,
            )

            # Get the root doubt_id for "Auto takeaways" to attach children
            root_doubts = get_doubts_for_message(
                conversation_id=conversation_id,
                message_id=message_id,
                user_email=user_email,
                users_dir=users_dir,
                logger=logger,
            )
            takeaways_doubt_id = None
            for d in root_doubts:
                if d.get("doubt_text") == "Auto takeaways":
                    takeaways_doubt_id = d.get("doubt_id")
                    break

            if not takeaways_doubt_id:
                return

            parent_id = takeaways_doubt_id
            selected_suggestions = suggestions[:4]

            # Generate all answers in parallel
            from concurrent.futures import ThreadPoolExecutor, as_completed

            def _answer_suggestion(suggestion):
                nq_prompt = f"""Answer the following question in detail based on the conversation context.

Provide:
- A thorough explanation with reasoning and intuition behind the answer
- Concrete examples or scenarios where relevant
- Non-obvious insights or surprising connections that deepen understanding
- Practical implications and how this knowledge connects to the bigger picture
- Where applicable, mention edge cases or caveats the reader should be aware of

Conversation context:
\"\"\"{conversation_summary}\"\"\"

Original user question:
\"\"\"{message}\"\"\"

Assistant answer:
\"\"\"{get_first_n_words(answer_trimmed, n=5000)}\"\"\"

Question to answer:
{suggestion}
"""
                return nq_llm(
                    nq_prompt,
                    images=[],
                    temperature=0.3,
                    stream=False,
                    max_tokens=1500,
                    system="Answer thoroughly in markdown with depth, practical insight, and nuance. Explain the 'why' behind things. No preamble." + _DOUBT_SECTION_FMT,
                )

            # Fire all LLM calls in parallel
            with ThreadPoolExecutor(max_workers=4) as executor:
                future_to_idx = {
                    executor.submit(_answer_suggestion, s): i
                    for i, s in enumerate(selected_suggestions)
                }
                results = [None] * len(selected_suggestions)
                for future in as_completed(future_to_idx):
                    idx = future_to_idx[future]
                    try:
                        results[idx] = future.result()
                    except Exception as nq_err:
                        logger.error(f"[auto_takeaways] Error answering next-Q: {nq_err}")

            # Chain results in order as child doubts
            for i, nq_answer in enumerate(results):
                try:
                    if isinstance(nq_answer, str) and nq_answer.strip():
                        new_doubt_id = add_doubt(
                            conversation_id=conversation_id,
                            user_email=user_email,
                            message_id=message_id,
                            doubt_text=selected_suggestions[i],
                            doubt_answer=nq_answer.strip(),
                            parent_doubt_id=parent_id,
                            users_dir=users_dir,
                            logger=logger,
                        )
                        parent_id = new_doubt_id
                except Exception as nq_err:
                    logger.error(f"[auto_takeaways] Error persisting next-Q '{selected_suggestions[i]}': {nq_err}")
        except Exception as nq_outer_err:
            logger.error(f"[auto_takeaways] Error in next-Q expansion: {nq_outer_err}", exc_info=True)

    except Exception as e:
        logger.error(
            f"[auto_takeaways] Error generating/persisting: {e}", exc_info=True
        )


def _create_maximize_learning_doubt(
    *,
    message: str,
    conversation: Conversation,
    conversation_id: str,
    user_email: str,
    users_dir: str,
    message_id: str | None = None,
    answer_text: str | None = None,
) -> None:
    """
    Generate a "Maximize Learning and Perspectives" root doubt that expands on critical
    concepts, plus a child doubt with diverse expert perspectives. Both LLM calls run in parallel.
    """
    try:
        from database.doubts import add_doubt, get_doubts_for_message
        from call_llm import CallLLm
        from concurrent.futures import ThreadPoolExecutor

        message_id, answer_text = _resolve_message_id_and_text(
            message_id, answer_text, conversation
        )
        if not message_id or not answer_text:
            return

        # Dedup
        try:
            existing = get_doubts_for_message(
                conversation_id=conversation_id,
                message_id=message_id,
                user_email=user_email,
                users_dir=users_dir,
                logger=logger,
            )
        except Exception:
            existing = []

        for d in existing:
            if isinstance(d, dict) and d.get("doubt_text") == "Maximize Learning and Perspectives":
                return

        answer_trimmed = " ".join(str(answer_text).split())[:50_000]
        conversation_summary = (
            conversation.running_summary
            if hasattr(conversation, "running_summary")
            else ""
        )

        learning_prompt = f"""Analyze the following assistant answer and identify 3-5 critical concepts, techniques, or facts that are:
- Important for deep understanding but likely less familiar to the reader
- Worth expanding on with additional context, examples, or caveats
- Not obvious from a surface reading

For each concept, provide:
- The concept name as a bold heading
- A detailed expansion with practical insight and concrete examples if needed
- Provide detailed explanation and intuition behind the concept
- Any common misconceptions or pitfalls, provide their detailed mitigation as well

Use markdown. No preamble.

Conversation context:
\"\"\"{conversation_summary}\"\"\"

User question:
\"\"\"{message}\"\"\"

Assistant answer:
\"\"\"{answer_trimmed}\"\"\"
"""

        perspectives_prompt = f"""Analyze the following question and answer from multiple expert perspectives. Each persona should offer their unique lens — what they'd focus on, what concerns them, what opportunities they see, and what non-obvious advice they'd give.

**Staff Engineer**
- Systemic implications: how does this interact with the broader system/codebase over time?
- Technical debt and maintainability trajectory
- What would you insist on before approving this in a design review?
- Cross-team dependencies or coordination risks

**Principal Engineer**
- What's the 3-year view? How does this decision compound?
- Architectural trade-offs being made implicitly
- What would you simplify or eliminate entirely?
- Where is accidental complexity being introduced?

**Experienced ML Engineer**
- Data assumptions and distribution shift risks
- Evaluation gaps — what's not being measured that should be?
- Reproducibility and experiment hygiene concerns
- Where will this break when inputs change or scale increases?

**Engineering Manager**
- Execution risk: what makes this hard to ship reliably?
- Team skill gaps or knowledge concentration risks
- Operational burden this creates for the on-call team

**Business/Product Manager**
- What user impact is being overlooked?
- Cost/benefit framing: is the juice worth the squeeze?
- What would you push back on or reprioritize?

For each perspective: lead with the single most surprising or non-obvious insight from that persona, then expand with detailed supporting points. Elaborate on the nuance — explain the reasoning chain behind each concern, describe the specific scenarios where it manifests, and articulate the trade-offs involved. Don't just state concerns — explain WHY they matter, what second-order effects they create, and what the persona would actually DO about it. Skip any perspective that has nothing meaningful to add for this specific topic.

Markdown with bold headings per persona. No preamble.

Conversation context:
\"\"\"{conversation_summary}\"\"\"

User question:
\"\"\"{message}\"\"\"

Assistant answer:
\"\"\"{answer_trimmed}\"\"\"
"""

        llm = CallLLm(
            conversation.get_api_keys(),
            model_name=conversation.get_model_override("auto_doubt_model", "gemini-flash-3.5-non-reasoning"),
            use_gpt4=False,
            use_16k=False,
        )

        # Run both LLM calls in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            learning_future = executor.submit(
                llm, learning_prompt, images=[], temperature=0.3, stream=False,
                max_tokens=1500,
                system="You identify and explain critical concepts that deepen understanding. Be precise and practical." + _DOUBT_SECTION_FMT,
            )
            perspectives_future = executor.submit(
                llm, perspectives_prompt, images=[], temperature=0.4, stream=False,
                max_tokens=2000,
                system="You inhabit multiple expert personas simultaneously. Each perspective is authentic — reflecting genuine concerns and priorities of that role, not generic platitudes. Surprise the reader with insights they wouldn't get from a single viewpoint." + _DOUBT_SECTION_FMT,
            )

            learning_content = learning_future.result()
            perspectives_content = perspectives_future.result()

        if not isinstance(learning_content, str) or not learning_content.strip():
            return

        root_id = add_doubt(
            conversation_id=conversation_id,
            user_email=user_email,
            message_id=message_id,
            doubt_text="Maximize Learning and Perspectives",
            doubt_answer=learning_content.strip(),
            parent_doubt_id=None,
            users_dir=users_dir,
            logger=logger,
        )

        # Add perspectives as child doubt
        if isinstance(perspectives_content, str) and perspectives_content.strip():
            add_doubt(
                conversation_id=conversation_id,
                user_email=user_email,
                message_id=message_id,
                doubt_text="Diverse Expert Perspectives",
                doubt_answer=perspectives_content.strip(),
                parent_doubt_id=root_id,
                users_dir=users_dir,
                logger=logger,
            )
    except Exception as e:
        logger.error(
            f"[maximize_learning] Error generating/persisting: {e}", exc_info=True
        )


def _create_challenge_and_verify_doubt(
    *,
    message: str,
    conversation: Conversation,
    conversation_id: str,
    user_email: str,
    users_dir: str,
    message_id: str | None = None,
    answer_text: str | None = None,
) -> None:
    """
    Create a 'Challenge & Verify' doubt thread with Devil's Advocate (root)
    + Common Mistakes (child). Both LLM calls run in parallel.
    """
    try:
        from database.doubts import add_doubt, get_doubts_for_message
        from call_llm import CallLLm
        from concurrent.futures import ThreadPoolExecutor

        message_id, answer_text = _resolve_message_id_and_text(
            message_id, answer_text, conversation
        )
        if not message_id or not answer_text:
            return

        # Dedup
        try:
            existing = get_doubts_for_message(
                conversation_id=conversation_id, message_id=message_id,
                user_email=user_email, users_dir=users_dir, logger=logger,
            )
        except Exception:
            existing = []
        for d in existing:
            if isinstance(d, dict) and d.get("doubt_text") == "Challenge & Verify":
                return

        answer_trimmed = " ".join(str(answer_text).split())[:50_000]
        conversation_summary = getattr(conversation, "running_summary", "") or ""

        llm = CallLLm(
            conversation.get_api_keys(),
            model_name=conversation.get_model_override("auto_doubt_model", "gemini-flash-3.5-non-reasoning"),
            use_gpt4=False, use_16k=False,
        )

        devils_prompt = f"""Critically analyze the following answer with depth. For each issue you identify, explain WHY it matters and HOW it manifests in practice.

Cover:
- Hidden assumptions that may not hold — explain what breaks when they don't hold and in what real scenarios this happens
- Edge cases or scenarios where this advice would fail — describe the failure mode in detail with a concrete example
- Counterarguments or alternative perspectives that challenge the main claims — explain the reasoning behind each alternative and when you'd prefer it
- Important nuance or context that was glossed over — explain why it matters and what changes when you account for it
- Surprising implications that a reader might miss on first reading — connect the dots to show non-obvious consequences

For each point, provide the intuition and reasoning chain, not just the conclusion. Help the reader build a mental model of WHY these issues exist.

Markdown. No preamble.

Conversation context:
\"\"\"{conversation_summary}\"\"\"

User question:
\"\"\"{message}\"\"\"

Assistant answer:
\"\"\"{answer_trimmed}\"\"\"
"""

        mistakes_prompt = f"""Based on the concepts in this answer, identify mistakes people make at multiple levels:

**Section 1: Common Implementation Mistakes**
- Subtle misunderstandings that lead to bugs — explain the flawed mental model that causes them
- Anti-patterns that arise from partial understanding — show what the code/design looks like and why it's wrong
- "Gotchas" that trip up even experienced practitioners — explain the surprising behavior and its root cause
- For each: explain WHY the mistake happens (the intuition gap), WHAT goes wrong (the failure mode), and HOW to fix it (the correct mental model + concrete fix)

**Section 2: Mistakes That Cascade at Scale / in Production**
Think like a staff engineer or principal engineer reviewing this for production readiness:
- What works fine locally but breaks at scale (concurrency, data volume, network partitions, thundering herds)? Explain the mechanics of WHY scale changes behavior.
- What appears correct in dev but causes cascading failures in production (retry storms, resource exhaustion, subtle race conditions, backpressure issues)? Trace the cascade chain.
- What monitoring/observability gaps would hide these issues until they explode? What metrics/alerts would catch them early?
- For each: explain the failure mechanism step by step, why local testing doesn't catch it (what's different about prod), and the production-grade mitigation with implementation details

Be detailed with concrete scenarios. Show the reasoning chain from root cause to visible symptom. Markdown. No preamble.

Conversation context:
\"\"\"{conversation_summary}\"\"\"

User question:
\"\"\"{message}\"\"\"

Assistant answer:
\"\"\"{get_first_n_words(answer_trimmed, n=8000)}\"\"\"
"""

        # Run both LLM calls in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            devils_future = executor.submit(
                llm, devils_prompt, images=[], temperature=0.3, stream=False, max_tokens=1500,
                system="You are a senior engineer and critical thinker. For every weakness you identify, explain the mechanism of failure and the intuition behind why it happens. Never be vague — always show the 'why' and trace the reasoning chain." + _DOUBT_SECTION_FMT,
            )
            mistakes_future = executor.submit(
                llm, mistakes_prompt, images=[], temperature=0.3, stream=False, max_tokens=2000,
                system="You are a principal engineer reviewing code and architecture for production readiness. You think in terms of failure modes at scale, cascading effects, and the gap between 'works on my machine' and 'works under load'. Trace each failure from root cause through propagation to visible symptom." + _DOUBT_SECTION_FMT,
            )

            devils_answer = devils_future.result()
            mistakes_answer = mistakes_future.result()

        if not isinstance(devils_answer, str) or not devils_answer.strip():
            return

        root_id = add_doubt(
            conversation_id=conversation_id, user_email=user_email,
            message_id=message_id, doubt_text="Challenge & Verify",
            doubt_answer=devils_answer.strip(), parent_doubt_id=None,
            users_dir=users_dir, logger=logger,
        )

        if isinstance(mistakes_answer, str) and mistakes_answer.strip():
            add_doubt(
                conversation_id=conversation_id, user_email=user_email,
                message_id=message_id, doubt_text="Common Mistakes",
                doubt_answer=mistakes_answer.strip(), parent_doubt_id=root_id,
                users_dir=users_dir, logger=logger,
            )
    except Exception as e:
        logger.error(f"[challenge_verify] Error: {e}", exc_info=True)


def _create_foundations_and_practice_doubt(
    *,
    message: str,
    conversation: Conversation,
    conversation_id: str,
    user_email: str,
    users_dir: str,
    message_id: str | None = None,
    answer_text: str | None = None,
) -> None:
    """
    Create a 'Foundations & Practice' doubt thread with Prerequisites Check (root)
    + Apply It (child). Both LLM calls run in parallel.
    """
    try:
        from database.doubts import add_doubt, get_doubts_for_message
        from call_llm import CallLLm
        from concurrent.futures import ThreadPoolExecutor

        message_id, answer_text = _resolve_message_id_and_text(
            message_id, answer_text, conversation
        )
        if not message_id or not answer_text:
            return

        # Dedup
        try:
            existing = get_doubts_for_message(
                conversation_id=conversation_id, message_id=message_id,
                user_email=user_email, users_dir=users_dir, logger=logger,
            )
        except Exception:
            existing = []
        for d in existing:
            if isinstance(d, dict) and d.get("doubt_text") == "Foundations & Practice":
                return

        answer_trimmed = " ".join(str(answer_text).split())[:50_000]
        conversation_summary = getattr(conversation, "running_summary", "") or ""

        llm = CallLLm(
            conversation.get_api_keys(),
            model_name=conversation.get_model_override("auto_doubt_model", "gemini-flash-3.5-non-reasoning"),
            use_gpt4=False, use_16k=False,
        )

        prereq_prompt = f"""What foundational knowledge does this answer assume the reader already has?

Identify and explain:
- Key concepts or terminology used without explanation — provide a clear, intuitive explanation of each (not just a definition, but WHY it works that way and how to think about it)
- Background knowledge required to fully understand the answer — explain the mental models or frameworks needed
- Prerequisite skills or experience assumed — describe what level of experience is expected and what gaps might exist
- Connections between prerequisites — show how these foundational concepts relate to each other and to the main answer

For each prerequisite, provide enough explanation that someone missing that knowledge can build the right mental model. Include analogies or concrete examples where helpful.

Markdown. No preamble.

Conversation context:
\"\"\"{conversation_summary}\"\"\"

User question:
\"\"\"{message}\"\"\"

Assistant answer:
\"\"\"{answer_trimmed}\"\"\"
"""

        apply_prompt = f"""Generate a practice exercise or thought experiment that tests deep comprehension of the key concepts in this answer.

Requirements:
- Should require genuine application of the concepts (not just recall)
- Should expose whether the reader truly understands the 'why' or just memorized the 'what'
- Include a scenario that has a non-obvious twist or subtlety that tests deeper understanding
- Provide: the exercise, a hint (that doesn't give it away), and a detailed solution with explanation of the reasoning
- The solution should explain common wrong answers and why they're wrong
- If applicable, include a follow-up variation that tests a related but different aspect

Make it engaging and thought-provoking. Markdown. No preamble.

Conversation context:
\"\"\"{conversation_summary}\"\"\"

User question:
\"\"\"{message}\"\"\"

Assistant answer:
\"\"\"{get_first_n_words(answer_trimmed, n=8000)}\"\"\"
"""

        # Run both LLM calls in parallel
        with ThreadPoolExecutor(max_workers=2) as executor:
            prereq_future = executor.submit(
                llm, prereq_prompt, images=[], temperature=0.3, stream=False, max_tokens=1500,
                system="You identify knowledge prerequisites and explain them with depth and intuition. Build mental models, not just definitions." + _DOUBT_SECTION_FMT,
            )
            apply_future = executor.submit(
                llm, apply_prompt, images=[], temperature=0.4, stream=False, max_tokens=1500,
                system="You create insightful practice exercises that reveal whether someone truly understands a concept or just memorized it. Design for 'aha moments'." + _DOUBT_SECTION_FMT,
            )

            prereq_answer = prereq_future.result()
            apply_answer = apply_future.result()

        if not isinstance(prereq_answer, str) or not prereq_answer.strip():
            return

        root_id = add_doubt(
            conversation_id=conversation_id, user_email=user_email,
            message_id=message_id, doubt_text="Foundations & Practice",
            doubt_answer=prereq_answer.strip(), parent_doubt_id=None,
            users_dir=users_dir, logger=logger,
        )

        if isinstance(apply_answer, str) and apply_answer.strip():
            add_doubt(
                conversation_id=conversation_id, user_email=user_email,
                message_id=message_id, doubt_text="Apply It",
                doubt_answer=apply_answer.strip(), parent_doubt_id=root_id,
                users_dir=users_dir, logger=logger,
            )
    except Exception as e:
        logger.error(f"[foundations_practice] Error: {e}", exc_info=True)


def _create_answer_raised_questions_doubt(
    *,
    message: str,
    conversation: Conversation,
    conversation_id: str,
    user_email: str,
    users_dir: str,
    message_id: str | None = None,
    answer_text: str | None = None,
) -> None:
    """
    Create an 'Answer Raised Questions' doubt that answers any questions the LLM
    posed in its response (e.g. from Deep Learn preamble's thought-provoking questions).
    """
    try:
        from database.doubts import add_doubt, get_doubts_for_message
        from call_llm import CallLLm

        message_id, answer_text = _resolve_message_id_and_text(
            message_id, answer_text, conversation
        )
        if not message_id or not answer_text:
            return

        # Dedup
        try:
            existing = get_doubts_for_message(
                conversation_id=conversation_id, message_id=message_id,
                user_email=user_email, users_dir=users_dir, logger=logger,
            )
        except Exception:
            existing = []
        for d in existing:
            if isinstance(d, dict) and d.get("doubt_text") == "Answer Raised Questions":
                return

        answer_trimmed = " ".join(str(answer_text).split())[:50_000]
        conversation_summary = getattr(conversation, "running_summary", "") or ""

        llm = CallLLm(
            conversation.get_api_keys(),
            model_name=conversation.get_model_override("auto_doubt_model", "gemini-flash-3.5-non-reasoning"),
            use_gpt4=False, use_16k=False,
        )

        # First extract questions, then answer them
        answer_prompt = f"""The following assistant response contains questions posed to the user (to stimulate thinking, guide exploration, or suggest next steps).

Your task:
1. Identify ALL questions the assistant asked in its response (look for question marks, rhetorical questions, "consider...", "what if...", "have you thought about..." patterns)
2. Answer each one thoroughly but concisely

Format: For each question, show the question as a bold heading then provide the answer (3-5 sentences each).

If the assistant did not ask any questions, respond with exactly: "No questions found in the response."

Markdown. No preamble.

Conversation context:
\"\"\"{conversation_summary}\"\"\"

User question:
\"\"\"{message}\"\"\"

Assistant response:
\"\"\"{answer_trimmed}\"\"\"
"""
        answers = llm(
            answer_prompt, images=[], temperature=0.3, stream=False, max_tokens=1500,
            system="You answer thought-provoking questions thoroughly and clearly to help the user learn." + _DOUBT_SECTION_FMT,
        )
        if not isinstance(answers, str) or not answers.strip():
            return
        if "no questions found" in answers.lower()[:100]:
            return

        add_doubt(
            conversation_id=conversation_id, user_email=user_email,
            message_id=message_id, doubt_text="Answer Raised Questions",
            doubt_answer=answers.strip(), parent_doubt_id=None,
            users_dir=users_dir, logger=logger,
        )
    except Exception as e:
        logger.error(f"[answer_raised_questions] Error: {e}", exc_info=True)


def _resolve_message_id_and_text(
    message_id: str | None,
    answer_text: str | None,
    conversation: Conversation,
    max_wait_seconds: int = 120,
) -> tuple[str | None, str | None]:
    """Shared helper: resolve message_id and answer_text, polling if needed."""
    if (
        isinstance(message_id, str) and message_id.strip()
        and isinstance(answer_text, str) and answer_text.strip()
    ):
        return message_id, answer_text

    import time as _time

    for _ in range(int(max_wait_seconds / 0.5)):
        try:
            messages = conversation.get_field("messages") or []
        except Exception:
            messages = []
        for msg in reversed(messages):
            if isinstance(msg, dict) and msg.get("sender") == "model":
                if msg.get("message_id") and msg.get("text"):
                    return msg["message_id"], msg["text"]
                break
        _time.sleep(0.5)
    return None, None


# ---------------------------------------------------------------------------
# Cross-conversation search endpoint
# ---------------------------------------------------------------------------


@conversations_bp.route("/search_conversations", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def search_conversations_endpoint():
    """Search across the user's conversations.

    Request body (JSON)::

        {
            "action": "search" | "list" | "summary",  // required
            "query": "search text",           // required for search
            "mode": "keyword" | "phrase" | "regex",  // default: keyword
            "deep": false,                     // search message content too
            "workspace_id": "ws_123",          // optional filter
            "domain": "default",              // optional filter
            "flag": "red",                     // optional filter
            "date_from": "2025-01-01",        // optional filter (ISO date)
            "date_to": "2026-03-04",          // optional filter (ISO date)
            "top_k": 20,                       // max results (default 20)
            "conversation_id": "conv_123",    // required for action=summary
            "sort_by": "last_updated",        // for list action
            "offset": 0,                       // pagination offset for list
            "limit": 50,                       // pagination limit for list
        }

    Returns::

        { "results": [...], "total": N, "query": "...", "action": "..." }
    """
    email, _name, _loggedin = get_session_identity()
    state = get_state()
    index = state.cross_conversation_index

    if not index:
        return json_error(
            "Cross-conversation search index not initialized.",
            status=503,
            code="index_not_ready",
        )

    data = request.get_json(force=True, silent=True) or {}
    action = data.get("action", "search")

    if action == "search":
        query = data.get("query", "").strip()
        if not query:
            return json_error("'query' is required for action=search.", status=400, code="missing_query")

        results = index.search(
            user_email=email,
            query=query,
            mode=data.get("mode", "keyword"),
            deep=bool(data.get("deep", False)),
            workspace_id=data.get("workspace_id") or None,
            domain=data.get("domain") or None,
            flag=data.get("flag") or None,
            date_from=data.get("date_from") or None,
            date_to=data.get("date_to") or None,
            sender_filter=data.get("sender_filter") or None,
            top_k=int(data.get("top_k", 20)),
        )
        return jsonify({"results": results, "total": len(results), "query": query, "action": "search"})

    elif action == "list":
        results = index.list_conversations(
            user_email=email,
            workspace_id=data.get("workspace_id") or None,
            domain=data.get("domain") or None,
            flag=data.get("flag") or None,
            date_from=data.get("date_from") or None,
            date_to=data.get("date_to") or None,
            sort_by=data.get("sort_by", "last_updated"),
            limit=int(data.get("limit", 50)),
            offset=int(data.get("offset", 0)),
        )
        return jsonify({"results": results, "total": len(results), "action": "list"})

    elif action == "summary":
        conversation_id = data.get("conversation_id", "").strip()
        if not conversation_id:
            return json_error(
                "'conversation_id' is required for action=summary.",
                status=400,
                code="missing_conversation_id",
            )

        result = index.get_summary(conversation_id, user_email=email)
        if result is None:
            return json_error(
                f"Conversation '{conversation_id}' not found in search index.",
                status=404,
                code="conversation_not_found",
            )
        return jsonify({"result": result, "action": "summary"})

    else:
        return json_error(
            f"Unknown action '{action}'. Use 'search', 'list', or 'summary'.",
            status=400,
            code="invalid_action",
        )
