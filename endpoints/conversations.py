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
import logging
import secrets
import string
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
from database.workspaces import getWorkspaceForConversation
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


@conversations_bp.route("/model_catalog", methods=["GET"])
@limiter.limit("300 per minute")
@login_required
def get_model_catalog():
    models = _dedupe_models(
        VERY_CHEAP_LLM
        + CHEAP_LLM
        + EXPENSIVE_LLM
        + CHEAP_LONG_CONTEXT_LLM
        + LONG_CONTEXT_LLM
    )
    defaults = {
        "summary_model": VERY_CHEAP_LLM[0],
        "tldr_model": CHEAP_LONG_CONTEXT_LLM[0],
        "artefact_propose_edits_model": EXPENSIVE_LLM[2],
        "doubt_clearing_model": EXPENSIVE_LLM[2],
        "context_action_model": EXPENSIVE_LLM[2],
        "doc_long_summary_model": CHEAP_LONG_CONTEXT_LLM[0],
        "doc_long_summary_v2_model": CHEAP_LONG_CONTEXT_LLM[0],
        "doc_short_answer_model": CHEAP_LONG_CONTEXT_LLM[0],
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
        "summary_model",
        "tldr_model",
        "artefact_propose_edits_model",
        "doubt_clearing_model",
        "context_action_model",
        "doc_long_summary_model",
        "doc_long_summary_v2_model",
        "doc_short_answer_model",
    }
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
            return json_error(
                f"Model name {value_str} not found in the list",
                status=400,
                code="invalid_model",
            )

    existing = conversation.get_conversation_settings()
    updated = dict(existing) if isinstance(existing, dict) else {}
    updated["model_overrides"] = normalized_overrides
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
    conversation.make_stateless()
    return jsonify({"message": f"Conversation {conversation_id} stateless now."})


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
        return jsonify({"message": "Flag cleared successfully"}), 200

    assert (
        flag is not None
        and len(flag.strip()) > 0
        and flag.strip().lower() in valid_colors
    )
    conversation.flag = flag.strip().lower()
    return jsonify({"message": "Flag set successfully"}), 200


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
    conversations = [
        state.conversation_cache[conversation_id]
        for conversation_id in conversation_ids
    ]
    conversation_id_to_workspace_id = {
        c[1]: {"workspace_id": c[4], "workspace_name": c[5]}
        for c in conv_db
        if c[4] is not None
    }

    stateless_conversations = [
        c for c in conversations if c is not None and c.stateless
    ]
    stateless_conversation_ids = [c.conversation_id for c in stateless_conversations]
    for conversation in stateless_conversations:
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
        none_conversation_ids + stateless_conversation_ids,
        users_dir=state.users_dir,
        logger=logger,
    )

    conversations = [c for c in conversations if c is not None and c.domain == domain]
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
    return jsonify(sorted_metadata_reverse)


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

    logger.warning(
        "[send_message] received request | conv=%s | t=%.2fs",
        conversation_id,
        time.time(),
    )

    # Inject conversation-pinned claim IDs into the query (for Deliberate Memory Attachment)
    conv_pinned_ids = list(state.pinned_claims.get(conversation_id, set()))
    if conv_pinned_ids:
        query["conversation_pinned_claim_ids"] = conv_pinned_ids

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
            if persist_or_not:
                captured_answer_text = (
                    "".join(captured_answer_parts).strip()
                    if captured_answer_parts
                    else ""
                )
                get_async_future(
                    _create_auto_takeaways_doubt_for_last_assistant_message,
                    message=query["messageText"],
                    conversation=conversation,
                    conversation_id=conversation_id,
                    user_email=email,
                    users_dir=state.users_dir,
                    message_id=captured_response_message_id,
                    answer_text=captured_answer_text,
                )
        except Exception as e:
            logger.error(
                f"[send_message] Failed to schedule auto-takeaways: {e}", exc_info=True
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

        # Context signals (bounded): summary + last turn.
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

        try:
            messages = conversation.get_message_list() or []
        except Exception:
            messages = []

        # Extract the most recent user+assistant pair (last turn).
        last_user_text = ""
        last_assistant_text = ""
        try:
            for msg in reversed(messages):
                if (
                    isinstance(msg, dict)
                    and not last_assistant_text
                    and msg.get("sender") == "model"
                ):
                    last_assistant_text = str(msg.get("text", "") or "")
                elif (
                    isinstance(msg, dict)
                    and not last_user_text
                    and msg.get("sender") == "user"
                ):
                    last_user_text = str(msg.get("text", "") or "")
                if last_user_text and last_assistant_text:
                    break
        except Exception:
            last_user_text = ""
            last_assistant_text = ""

        last_user_text = (
            " ".join(last_user_text.split())[:18_000] if last_user_text else "(none)"
        )
        last_assistant_text = (
            " ".join(last_assistant_text.split())[:22_000]
            if last_assistant_text
            else "(none)"
        )

        prompt = f"""
You are an intent-clarification assistant. Given a user's draft message and brief conversation context, decide if clarifications are needed.

Conversation summary:
\"\"\"{conversation_summary}\"\"\"

Last turn (most recent):
- Last user message: \"\"\"{last_user_text}\"\"\"
- Last assistant message: \"\"\"{last_assistant_text}\"\"\"

Draft message:
\"\"\"{message_text.strip()}\"\"\"

Rules:
- If the draft is already specific enough to answer, set needs_clarification=false and questions=[].
- Otherwise, propose up to 3 multiple-choice questions to clarify intent/objective.
- Each question must have 2 to 5 options.
- The questions can be generic to clarify the intent of the user's message. Or specific to the conversation context and the user message.
- Keep questions short and practical.
- Do NOT ask about facts that are already answered by the conversation summary or last turn.
- Output MUST be STRICT JSON only (no markdown, no code fences, no extra text).
- For Free form text option input, Put the option as "Other (please specify)" which when checked will show a text input field to enter the free form text. 

JSON schema:
{{
  "needs_clarification": true|false,
  "questions": [
    {{
      "prompt": "question text",
      "options": ["option 1", "option 2"]
    }}
  ]
}}
""".strip()

        llm = CallLLm(keys, model_name=VERY_CHEAP_LLM[0], use_gpt4=False, use_16k=False)
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
            model_name=VERY_CHEAP_LLM[0],
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
    except Exception as e:
        logger.error(
            f"[auto_takeaways] Error generating/persisting: {e}", exc_info=True
        )
