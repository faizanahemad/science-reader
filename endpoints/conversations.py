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

from Conversation import Conversation
from DocIndex import DocIndex
from common import COMMON_SALT_STRING
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

@conversations_bp.route("/list_messages_by_conversation/<conversation_id>", methods=["GET"])
@limiter.limit("1000 per minute")
@login_required
def list_messages_by_conversation(conversation_id: str):
    keys = keyParser(session)
    email, _name, _loggedin = get_session_identity()
    _last_n_messages = request.args.get("last_n_messages", 10)  # preserved; unused (legacy)

    if not checkConversationExists(email, conversation_id, users_dir=get_state().users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = get_conversation_with_keys(get_state(), conversation_id=conversation_id, keys=keys)
    messages = conversation.get_message_list()
    return jsonify(messages)


@conversations_bp.route("/list_messages_by_conversation_shareable/<conversation_id>", methods=["GET"])
@limiter.limit("100 per minute")
def list_messages_by_conversation_shareable(conversation_id: str):
    keys = keyParser(session)
    _email, _name, _loggedin = get_session_identity()

    conversation_ids = [c[1] for c in getAllCoversations(users_dir=get_state().users_dir)]
    if conversation_id not in conversation_ids:
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation: Conversation = get_conversation_with_keys(get_state(), conversation_id=conversation_id, keys=keys)

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
        if not checkConversationExists(user_email, conversation_id, users_dir=get_state().users_dir):
            return json_error("Conversation not found or access denied", status=404, code="conversation_not_found")

        # Use cached conversation + lock-clearing behavior already embedded in the cache loader.
        conversation: Conversation = get_state().conversation_cache[conversation_id]
        query = request.args.get("query", "")
        history_text = conversation.get_conversation_history(query)

        return jsonify({"conversation_id": conversation_id, "history": history_text, "timestamp": time.time()})
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
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)
    data = conversation.get_metadata()

    workspace_info = getWorkspaceForConversation(users_dir=state.users_dir, conversation_id=conversation_id)
    if not workspace_info:
        workspace_info = {"workspace_id": None}

    data["workspace"] = workspace_info
    return jsonify(data)


@conversations_bp.route("/make_conversation_stateless/<conversation_id>", methods=["DELETE"])
@limiter.limit("25 per minute")
@login_required
def make_conversation_stateless(conversation_id: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)

    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)
    conversation.make_stateless()
    return jsonify({"message": f"Conversation {conversation_id} stateless now."})


@conversations_bp.route("/make_conversation_stateful/<conversation_id>", methods=["PUT"])
@limiter.limit("25 per minute")
@login_required
def make_conversation_stateful(conversation_id: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)

    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)
    conversation.make_stateful()
    return jsonify({"message": f"Conversation {conversation_id} deleted"})


@conversations_bp.route("/edit_message_from_conversation/<conversation_id>/<message_id>/<index>", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def edit_message_from_conversation(conversation_id: str, message_id: str, index: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)

    message_text = request.json.get("text") if request.is_json and request.json else None

    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)
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
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)
    conversation.move_messages_up_or_down(message_ids, direction)
    return jsonify({"message": f"Messages {message_ids} moved {direction}"})


@conversations_bp.route("/get_next_question_suggestions/<conversation_id>", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def get_next_question_suggestions(conversation_id: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)

    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)
    suggestions = conversation.get_next_question_suggestions()
    return jsonify({"suggestions": suggestions})


@conversations_bp.route("/show_hide_message_from_conversation/<conversation_id>/<message_id>/<index>", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def show_hide_message_from_conversation(conversation_id: str, message_id: str, index: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)

    show_hide = request.json.get("show_hide") if request.is_json and request.json else None

    state = get_state()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)
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
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation: Conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)

    new_conversation: Conversation = conversation.clone_conversation()
    new_conversation.save_local()

    workspace_info = getWorkspaceForConversation(users_dir=state.users_dir, conversation_id=conversation_id)
    workspace_id = workspace_info.get("workspace_id") if workspace_info else None

    addConversation(
        email,
        new_conversation.conversation_id,
        workspace_id=workspace_id,
        domain=conversation.domain,
        users_dir=state.users_dir,
    )

    state.conversation_cache[new_conversation.conversation_id] = new_conversation

    return jsonify({"message": f"Conversation {conversation_id} cloned", "conversation_id": new_conversation.conversation_id})


@conversations_bp.route("/delete_conversation/<conversation_id>", methods=["DELETE"])
@limiter.limit("5000 per minute")
@login_required
def delete_conversation(conversation_id: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)

    del state.conversation_cache[conversation_id]
    conversation.delete_conversation()
    deleteConversationForUser(email, conversation_id, users_dir=state.users_dir)
    removeUserFromConversation(email, conversation_id, users_dir=state.users_dir)

    return jsonify({"message": f"Conversation {conversation_id} deleted"})


@conversations_bp.route("/delete_message_from_conversation/<conversation_id>/<message_id>/<index>", methods=["DELETE"])
@limiter.limit("300 per minute")
@login_required
def delete_message_from_conversation(conversation_id: str, message_id: str, index: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)
    conversation.delete_message(message_id, index)
    return jsonify({"message": f"Message {message_id} deleted"})


@conversations_bp.route("/delete_last_message/<conversation_id>", methods=["DELETE"])
@limiter.limit("30 per minute")
@login_required
def delete_last_message(conversation_id: str):
    message_id = 1  # preserved (legacy)
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation: Conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)
    conversation.delete_last_turn()
    return jsonify({"message": f"Message {message_id} deleted"})


@conversations_bp.route("/set_memory_pad/<conversation_id>", methods=["POST"])
@limiter.limit("25 per minute")
@login_required
def set_memory_pad(conversation_id: str):
    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)
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
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)
    memory_pad = conversation.memory_pad
    return jsonify({"text": memory_pad})


@conversations_bp.route(
    f"/get_conversation_output_docs/{COMMON_SALT_STRING}/<conversation_id>/<document_file_name>", methods=["GET"]
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
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    cancellation_requests[conversation_id] = {"cancelled": True, "timestamp": time.time()}
    logger.info(f"Cancellation requested for conversation {conversation_id} by user {email}")
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

    return jsonify({"message": f"Cleaned up {len(to_remove)} old cancellation requests"}), 200


@conversations_bp.route("/cancel_coding_hint/<conversation_id>", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def cancel_coding_hint(conversation_id: str):
    """Cancel an ongoing coding hint generation."""

    from base import coding_hint_cancellation_requests

    email, _name, _loggedin = get_session_identity()
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    coding_hint_cancellation_requests[conversation_id] = {"cancelled": True, "timestamp": time.time()}
    logger.info(f"Coding hint cancellation requested for conversation {conversation_id} by user {email}")
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
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    coding_solution_cancellation_requests[conversation_id] = {"cancelled": True, "timestamp": time.time()}
    logger.info(f"Coding solution cancellation requested for conversation {conversation_id} by user {email}")
    return jsonify({"message": "Coding solution cancellation requested successfully"}), 200


@conversations_bp.route("/get_coding_hint/<conversation_id>", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def get_coding_hint_endpoint(conversation_id: str):
    """Get a coding hint based on current context and code (streaming response)."""

    keys = keyParser(session)
    state = get_state()

    try:
        user_email = session.get("email")
        if not checkConversationExists(user_email, conversation_id, users_dir=state.users_dir):
            logger.warning(
                f"User {user_email} attempted to access conversation {conversation_id} without permission"
            )
            return json_error("Conversation not found or access denied", status=404, code="conversation_not_found")

        data = request.get_json() or {}
        current_code = data.get("current_code", "")
        context_text = data.get("context", "")

        conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)
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
        if not checkConversationExists(user_email, conversation_id, users_dir=state.users_dir):
            logger.warning(
                f"User {user_email} attempted to access conversation {conversation_id} without permission"
            )
            return json_error("Conversation not found or access denied", status=404, code="conversation_not_found")

        data = request.get_json() or {}
        current_code = data.get("current_code", "")
        context_text = data.get("context", "")

        conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)
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
                logger.error(f"Error in solution streaming for {conversation_id}: {str(e)}")
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
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    doubt_cancellation_requests[conversation_id] = {"cancelled": True, "timestamp": time.time()}
    logger.info(f"Doubt clearing cancellation requested for conversation {conversation_id} by user {email}")
    return jsonify({"message": "Doubt clearing cancellation requested successfully"}), 200


@conversations_bp.route("/set_flag/<conversation_id>/<flag>", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def set_flag(conversation_id: str, flag: str):
    email, _name, _loggedin = get_session_identity()
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation = state.conversation_cache[conversation_id]
    if conversation is None:
        return json_error("Conversation not found", status=404, code="conversation_not_found")

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

    assert flag is not None and len(flag.strip()) > 0 and flag.strip().lower() in valid_colors
    conversation.flag = flag.strip().lower()
    return jsonify({"message": "Flag set successfully"}), 200


def _create_conversation_simple(domain: str, workspace_id: str | None = None) -> Conversation:
    """
    Create and persist a new conversation, then return the Conversation object.

    This mirrors legacy `server.py:create_conversation_simple`, but uses `AppState` for paths
    and passes `users_dir` explicitly into DB helpers.
    """

    email, _name, _loggedin = get_session_identity()
    keys = keyParser(session)
    from base import get_embedding_model

    state = get_state()
    conversation_id = email + "_" + "".join(secrets.choice(_ALPHABET) for _ in range(36))
    conversation = Conversation(
        email,
        openai_embed=get_embedding_model(keys),
        storage=state.conversation_folder,
        conversation_id=conversation_id,
        domain=domain,
    )
    conversation = attach_keys(conversation, keys)
    addConversation(email, conversation.conversation_id, workspace_id, domain, users_dir=state.users_dir)
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
    _last_n_conversations = request.args.get("last_n_conversations", 10)  # preserved; unused (legacy)

    conv_db = getCoversationsForUser(email, domain, users_dir=state.users_dir)
    conversation_ids = [c[1] for c in conv_db]
    conversations = [state.conversation_cache[conversation_id] for conversation_id in conversation_ids]
    conversation_id_to_workspace_id = {
        c[1]: {"workspace_id": c[4], "workspace_name": c[5]} for c in conv_db if c[4] is not None
    }

    stateless_conversations = [c for c in conversations if c is not None and c.stateless]
    stateless_conversation_ids = [c.conversation_id for c in stateless_conversations]
    for conversation in stateless_conversations:
        removeUserFromConversation(email, conversation.conversation_id, users_dir=state.users_dir)
        del state.conversation_cache[conversation.conversation_id]
        deleteConversationForUser(email, conversation.conversation_id, users_dir=state.users_dir)
        conversation.delete_conversation()

    none_conversation_ids: list[str] = []
    for conversation_id, conversation in zip(conversation_ids, conversations):
        if conversation is None:
            removeUserFromConversation(email, conversation_id, users_dir=state.users_dir)
            del state.conversation_cache[conversation_id]
            deleteConversationForUser(email, conversation_id, users_dir=state.users_dir)
            none_conversation_ids.append(conversation_id)

    cleanup_deleted_conversations(
        none_conversation_ids + stateless_conversation_ids, users_dir=state.users_dir, logger=logger
    )

    conversations = [c for c in conversations if c is not None and c.domain == domain]
    conversations = [set_keys_on_docs(c, keys) for c in conversations]
    data = [[c.get_metadata(), c] for c in conversations]
    for metadata, conversation in data:
        assert (
            conversation.conversation_id in conversation_id_to_workspace_id
        ), f"Conversation {conversation.conversation_id} not found in conversation_id_to_workspace_id"
        metadata["workspace_id"] = conversation_id_to_workspace_id[conversation.conversation_id]["workspace_id"]
        metadata["workspace_name"] = conversation_id_to_workspace_id[conversation.conversation_id]["workspace_name"]
        metadata["domain"] = conversation.domain

    sorted_data_reverse = sorted(data, key=lambda x: x[0]["last_updated"], reverse=True)

    if len(sorted_data_reverse) > 0 and len(sorted_data_reverse[0][0]["summary_till_now"].strip()) > 0:
        sorted_data_reverse = sorted(sorted_data_reverse, key=lambda x: len(x[0]["summary_till_now"].strip()))
        if sorted_data_reverse[0][0]["summary_till_now"].strip() == "" and len(sorted_data_reverse[0][1].get_message_list()) == 0:
            new_conversation = sorted_data_reverse[0][1]
            sorted_data_reverse = sorted_data_reverse[1:]
            sorted_data_reverse = sorted(sorted_data_reverse, key=lambda x: x[0]["last_updated"], reverse=True)
        else:
            new_conversation = _create_conversation_simple(domain)
        sorted_data_reverse.insert(0, [new_conversation.get_metadata(), new_conversation])

    if len(sorted_data_reverse) == 0:
        new_conversation = _create_conversation_simple(domain)
        sorted_data_reverse.insert(0, [new_conversation.get_metadata(), new_conversation])

    sorted_metadata_reverse = [sd[0] for sd in sorted_data_reverse]
    return jsonify(sorted_metadata_reverse)


@conversations_bp.route("/create_conversation/<domain>/", defaults={"workspace_id": None}, methods=["POST"])
@conversations_bp.route("/create_conversation/<domain>/<workspace_id>", methods=["POST"])
@limiter.limit("500 per minute")
@login_required
def create_conversation(domain: str, workspace_id: str | None = None):
    domain = domain.strip().lower()
    state = get_state()

    conversation = _create_conversation_simple(domain, workspace_id)
    data = conversation.get_metadata()
    data["workspace"] = getWorkspaceForConversation(users_dir=state.users_dir, conversation_id=conversation.conversation_id)
    return jsonify(data)


@conversations_bp.route("/shared_chat/<conversation_id>", methods=["GET"])
@limiter.limit("100 per minute")
def shared_chat(conversation_id: str):
    state = get_state()
    conversation_ids = [c[1] for c in getConversationById(conversation_id, users_dir=state.users_dir)]
    if conversation_id not in conversation_ids:
        return json_error("Conversation not found", status=404, code="conversation_not_found")

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

    user_details = getUserFromUserDetailsTable(email, users_dir=state.users_dir, logger=logger)

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    conversation: Conversation = get_conversation_with_keys(state, conversation_id=conversation_id, keys=keys)

    query = request.json

    # Inject conversation-pinned claim IDs into the query (for Deliberate Memory Attachment)
    conv_pinned_ids = list(state.pinned_claims.get(conversation_id, set()))
    if conv_pinned_ids:
        query["conversation_pinned_claim_ids"] = conv_pinned_ids

    from queue import Queue
    from flask import copy_current_request_context

    response_queue: Queue = Queue()

    @copy_current_request_context
    def generate_response():
        for chunk in conversation(query, user_details):
            response_queue.put(chunk)
        response_queue.put("<--END-->")
        conversation.clear_cancellation()

    _future = get_async_future(generate_response)

    def run_queue():
        try:
            while True:
                chunk = response_queue.get()
                if chunk == "<--END-->":
                    break
                yield chunk
        except GeneratorExit:
            # Client disconnected - we'll still finish our background task
            print("Client disconnected, but continuing background processing")

    return Response(run_queue(), content_type="text/plain")


