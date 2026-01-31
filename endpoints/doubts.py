"""
Doubt-related endpoints.

This module extracts the "doubt clearing" API surface from `server.py` into a
Flask Blueprint.
"""

from __future__ import annotations

import json
import logging

from flask import Blueprint, Response, jsonify, request, session

from database.conversations import checkConversationExists
from database.doubts import (
    add_doubt,
    delete_doubt,
    get_doubt,
    get_doubt_history,
    get_doubts_for_message,
)
from endpoints.auth import login_required
from endpoints.request_context import attach_keys, get_state_and_keys
from endpoints.responses import json_error
from endpoints.session_utils import get_session_identity
from endpoints.state import get_state
from extensions import limiter
from common import EXPENSIVE_LLM
from Conversation import model_name_to_canonical_name


doubts_bp = Blueprint("doubts", __name__)
logger = logging.getLogger(__name__)


@doubts_bp.route("/clear_doubt/<conversation_id>/<message_id>", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def clear_doubt_route(conversation_id: str, message_id: str):
    """Clear a doubt for a specific message - streaming response."""

    email, _name, _loggedin = get_session_identity()
    state, keys = get_state_and_keys()

    doubt_text = (
        request.json.get("doubt_text") if request.is_json and request.json else None
    )
    parent_doubt_id = (
        request.json.get("parent_doubt_id")
        if request.is_json and request.json
        else None
    )
    reward_level = int(
        (request.json.get("reward_level", 0) if request.is_json and request.json else 0)
        or 0
    )

    try:
        if not checkConversationExists(
            email, conversation_id, users_dir=state.users_dir
        ):
            logger.warning(
                f"User {email} attempted to access conversation {conversation_id} without permission"
            )
            return json_error(
                "Conversation not found or access denied",
                status=404,
                code="conversation_not_found",
            )

        conversation = attach_keys(state.conversation_cache[conversation_id], keys)

        def generate_doubt_clearing_stream():
            accumulated_doubt_answer = ""
            try:
                yield (
                    json.dumps(
                        {
                            "text": "",
                            "status": "Analyzing message and clearing doubt...",
                            "conversation_id": conversation_id,
                            "message_id": message_id,
                            "type": "doubt_clearing",
                        }
                    )
                    + "\n"
                )

                doubt_history = []
                if parent_doubt_id:
                    try:
                        doubt_history = get_doubt_history(
                            doubt_id=parent_doubt_id,
                            users_dir=state.users_dir,
                            logger=logger,
                        )
                        logger.info(
                            f"Retrieved doubt history with {len(doubt_history)} entries for follow-up"
                        )
                    except Exception as history_error:
                        logger.error(
                            f"Error retrieving doubt history: {str(history_error)}"
                        )

                doubt_generator = conversation.clear_doubt(
                    message_id, doubt_text, doubt_history, reward_level
                )

                accumulated_text = ""
                doubt_id = None

                try:
                    for chunk in doubt_generator:
                        if chunk:
                            accumulated_text += chunk
                            accumulated_doubt_answer += chunk
                            yield (
                                json.dumps(
                                    {
                                        "text": chunk,
                                        "status": "Clearing doubt...",
                                        "conversation_id": conversation_id,
                                        "message_id": message_id,
                                        "type": "doubt_clearing",
                                        "accumulated_text": accumulated_text,
                                    }
                                )
                                + "\n"
                            )
                finally:
                    if accumulated_doubt_answer.strip():
                        try:
                            doubt_id = add_doubt(
                                conversation_id=conversation_id,
                                user_email=email,
                                message_id=message_id,
                                doubt_text=doubt_text
                                or "Please explain this message in more detail.",
                                doubt_answer=accumulated_doubt_answer,
                                parent_doubt_id=parent_doubt_id,
                                users_dir=state.users_dir,
                                logger=logger,
                            )
                            logger.info(
                                f"Doubt clearing data saved successfully with ID {doubt_id}: {len(accumulated_doubt_answer)} characters"
                            )
                        except Exception as save_error:
                            logger.error(
                                f"Error saving doubt clearing data: {str(save_error)}"
                            )
                            doubt_id = None

                final_text = f"<doubt_id>{doubt_id}</doubt_id>" if doubt_id else ""
                yield (
                    json.dumps(
                        {
                            "text": final_text,
                            "status": "Doubt cleared successfully!",
                            "conversation_id": conversation_id,
                            "message_id": message_id,
                            "type": "doubt_clearing",
                            "completed": True,
                            "accumulated_text": accumulated_text,
                            "doubt_id": doubt_id,
                        }
                    )
                    + "\n"
                )
            except Exception as e:
                logger.error(
                    f"Error in doubt clearing streaming for {conversation_id}, message {message_id}: {str(e)}"
                )
                yield (
                    json.dumps(
                        {
                            "text": "",
                            "status": f"Error: {str(e)}",
                            "conversation_id": conversation_id,
                            "message_id": message_id,
                            "type": "doubt_clearing",
                            "error": True,
                        }
                    )
                    + "\n"
                )

        return Response(generate_doubt_clearing_stream(), content_type="text/plain")
    except Exception as e:
        logger.error(
            f"Error clearing doubt for {conversation_id}, message {message_id}: {str(e)}"
        )
        return json_error(str(e), status=500, code="internal_error")


@doubts_bp.route("/temporary_llm_action", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def temporary_llm_action_route():
    """
    Execute an ephemeral LLM action without DB persistence (streaming).

    This preserves legacy behavior from `server.py:_legacy_temporary_llm_action`.
    """

    email, _name, _loggedin = get_session_identity()
    state, keys = get_state_and_keys()

    try:
        data = request.json or {}
        action_type = data.get("action_type", "explain")
        selected_text = data.get("selected_text", "")
        user_message = data.get("user_message", "")
        message_id = data.get("message_id")
        message_text = data.get("message_text", "")
        conversation_id = data.get("conversation_id")
        history = data.get("history", [])
        with_context = bool(data.get("with_context", False))

        logger.info(
            f"Temporary LLM action: {action_type} for user {email}, with_context: {with_context}"
        )

        conversation = None
        if conversation_id and checkConversationExists(
            email, conversation_id, users_dir=state.users_dir
        ):
            try:
                conversation = attach_keys(
                    state.conversation_cache[conversation_id], keys
                )
            except Exception as e:
                logger.warning(f"Could not load conversation {conversation_id}: {e}")
                conversation = None

        def generate_temporary_llm_stream():
            try:
                status_msg = f"Processing {action_type}..."
                if with_context:
                    status_msg = (
                        f"Processing {action_type} with conversation context..."
                    )

                yield (
                    json.dumps(
                        {"text": "", "status": status_msg, "type": "temporary_llm"}
                    )
                    + "\n"
                )

                if conversation:
                    response_generator = conversation.temporary_llm_action(
                        action_type=action_type,
                        selected_text=selected_text,
                        user_message=user_message,
                        message_context=message_text,
                        message_id=message_id,
                        history=history,
                        with_context=with_context,
                    )
                else:
                    # Fallback: direct call without conversation context.
                    from endpoints.llm_actions import direct_temporary_llm_action

                    model_name = EXPENSIVE_LLM[2]
                    if conversation is not None:
                        model_name = conversation.get_model_override(
                            "context_action_model", model_name
                        )
                    response_generator = direct_temporary_llm_action(
                        keys=keys,
                        action_type=action_type,
                        selected_text=selected_text,
                        user_message=user_message,
                        history=history,
                        model_name=model_name,
                        model_name_to_canonical=model_name_to_canonical_name,
                    )

                for chunk in response_generator:
                    if chunk:
                        yield (
                            json.dumps(
                                {
                                    "text": chunk,
                                    "status": f"Processing {action_type}...",
                                    "type": "temporary_llm",
                                }
                            )
                            + "\n"
                        )

                yield (
                    json.dumps(
                        {
                            "text": "",
                            "status": "Complete!",
                            "type": "temporary_llm",
                            "completed": True,
                        }
                    )
                    + "\n"
                )
                logger.info(f"Completed temporary LLM action: {action_type}")

            except Exception as e:
                logger.error(f"Error in temporary LLM streaming: {str(e)}")
                yield (
                    json.dumps(
                        {
                            "text": "",
                            "status": f"Error: {str(e)}",
                            "type": "temporary_llm",
                            "error": True,
                        }
                    )
                    + "\n"
                )

        return Response(generate_temporary_llm_stream(), content_type="text/plain")

    except Exception as e:
        logger.error(f"Error in temporary LLM action: {str(e)}")
        return json_error(str(e), status=500, code="internal_error")


@doubts_bp.route("/get_doubt/<doubt_id>", methods=["GET"])
@limiter.limit("100 per minute")
@login_required
def get_doubt_route(doubt_id: str):
    """Get a specific doubt clearing record by doubt_id."""

    email, _name, _loggedin = get_session_identity()
    state = get_state()

    try:
        doubt_record = get_doubt(
            doubt_id=doubt_id, users_dir=state.users_dir, logger=logger
        )
        if not doubt_record:
            return json_error(
                "No doubt clearing found with this ID",
                status=404,
                code="doubt_not_found",
                success=False,
            )

        if not checkConversationExists(
            email, doubt_record["conversation_id"], users_dir=state.users_dir
        ):
            logger.warning(
                f"User {email} attempted to access doubt {doubt_id} without permission"
            )
            return json_error(
                "Conversation not found or access denied",
                status=404,
                code="conversation_not_found",
            )

        return jsonify({"success": True, "doubt": doubt_record})
    except Exception as e:
        logger.error(f"Error getting doubt {doubt_id}: {str(e)}")
        return json_error(str(e), status=500, code="internal_error")


@doubts_bp.route("/delete_doubt/<doubt_id>", methods=["DELETE"])
@limiter.limit("50 per minute")
@login_required
def delete_doubt_route(doubt_id: str):
    """Delete a specific doubt clearing record by doubt_id."""

    email, _name, _loggedin = get_session_identity()
    state = get_state()

    try:
        doubt_record = get_doubt(
            doubt_id=doubt_id, users_dir=state.users_dir, logger=logger
        )
        if not doubt_record:
            return json_error(
                "No doubt clearing found with this ID",
                status=404,
                code="doubt_not_found",
                success=False,
            )

        if not checkConversationExists(
            email, doubt_record["conversation_id"], users_dir=state.users_dir
        ):
            logger.warning(
                f"User {email} attempted to delete doubt {doubt_id} without permission"
            )
            return json_error(
                "Conversation not found or access denied",
                status=404,
                code="conversation_not_found",
            )

        deleted = delete_doubt(
            doubt_id=doubt_id, users_dir=state.users_dir, logger=logger
        )
        if deleted:
            return jsonify(
                {"success": True, "message": "Doubt clearing deleted successfully"}
            )
        return json_error(
            "Failed to delete doubt clearing",
            status=500,
            code="internal_error",
            success=False,
        )
    except Exception as e:
        logger.error(f"Error deleting doubt {doubt_id}: {str(e)}")
        return json_error(str(e), status=500, code="internal_error")


@doubts_bp.route("/get_doubts/<conversation_id>/<message_id>", methods=["GET"])
@limiter.limit("100 per minute")
@login_required
def get_doubts_for_message_route(conversation_id: str, message_id: str):
    """Get all doubt clearing records for a specific message."""

    email, _name, _loggedin = get_session_identity()
    state = get_state()

    try:
        if not checkConversationExists(
            email, conversation_id, users_dir=state.users_dir
        ):
            logger.warning(
                f"User {email} attempted to access conversation {conversation_id} without permission"
            )
            return json_error(
                "Conversation not found or access denied",
                status=404,
                code="conversation_not_found",
            )

        doubts = get_doubts_for_message(
            conversation_id=conversation_id,
            message_id=message_id,
            user_email=email,
            users_dir=state.users_dir,
            logger=logger,
        )

        return jsonify({"success": True, "doubts": doubts, "count": len(doubts)})
    except Exception as e:
        logger.error(
            f"Error getting doubts for message {conversation_id}/{message_id}: {str(e)}"
        )
        return json_error(str(e), status=500, code="internal_error")
