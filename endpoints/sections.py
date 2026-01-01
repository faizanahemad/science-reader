"""
Section-related endpoints.

This module extracts the "section hidden details" API surface from `server.py`
into a Flask Blueprint.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request, session

from database.conversations import checkConversationExists
from database.sections import bulk_update_section_hidden_detail, get_section_hidden_details
from endpoints.auth import login_required
from endpoints.responses import json_error
from endpoints.session_utils import get_session_identity
from endpoints.state import get_state
from extensions import limiter


sections_bp = Blueprint("sections", __name__)
logger = logging.getLogger(__name__)

@sections_bp.route("/get_section_hidden_details", methods=["GET"])
@limiter.limit("100 per minute")
@login_required
def get_section_hidden_details_route():
    conversation_id = request.args.get("conversation_id")
    section_ids = request.args.get("section_ids")

    section_ids = (section_ids or "").split(",")
    section_ids = [str(section_id) for section_id in section_ids if str(section_id).strip() != ""]

    state = get_state()
    section_hidden_details = get_section_hidden_details(
        conversation_id=conversation_id,
        section_ids=section_ids,
        users_dir=state.users_dir,
        logger=logger,
    )
    return jsonify({"section_details": section_hidden_details})


@sections_bp.route("/update_section_hidden_details", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def update_section_hidden_details_route():
    """
    Update or create section hidden details for multiple sections in bulk.

    Expected JSON payload:
    {
        "conversation_id": "conv_123",
        "section_details": {
            "section_1": {"hidden": true},
            "section_2": {"hidden": false}
        }
    }
    """

    try:
        data = request.get_json()
        if not data:
            return json_error("No JSON data provided", status=400, code="bad_request")

        conversation_id = data.get("conversation_id")
        section_details = data.get("section_details", {})

        if not conversation_id:
            return json_error("conversation_id is required", status=400, code="bad_request")

        if not section_details:
            return json_error(
                "section_details is required and must be a non-empty dictionary",
                status=400,
                code="bad_request",
            )

        if not isinstance(section_details, dict):
            return json_error("section_details must be a dictionary", status=400, code="bad_request")

        email, _name, _loggedin = get_session_identity()
        state = get_state()
        if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
            return json_error("Conversation not found or access denied", status=404, code="conversation_not_found")

        validated_updates: dict[str, bool] = {}
        validation_errors: list[str] = []

        for section_id, details in section_details.items():
            if not isinstance(details, dict):
                validation_errors.append(f"Section {section_id}: details must be a dictionary")
                continue
            if "hidden" not in details:
                validation_errors.append(f"Section {section_id}: 'hidden' field is required")
                continue
            hidden_state = details["hidden"]
            if not isinstance(hidden_state, bool):
                validation_errors.append(f"Section {section_id}: 'hidden' must be a boolean value")
                continue
            validated_updates[str(section_id)] = hidden_state

        if validation_errors:
            return json_error(
                "Validation failed",
                status=400,
                code="bad_request",
                validation_errors=validation_errors,
            )

        bulk_update_section_hidden_detail(
            conversation_id=conversation_id,
            section_updates=validated_updates,
            users_dir=state.users_dir,
            logger=logger,
        )

        updated_sections = {
            section_id: {"hidden": hidden_state, "status": "updated"} for section_id, hidden_state in validated_updates.items()
        }
        logger.info(f"Bulk updated section hidden details for conversation {conversation_id}: {len(updated_sections)} sections")
        return jsonify(
            {
                "status": "success",
                "message": f"Updated {len(updated_sections)} sections successfully",
                "updated_sections": updated_sections,
                "conversation_id": conversation_id,
            }
        )
    except Exception as e:
        logger.error(f"Error updating section hidden details: {str(e)}")
        return json_error(str(e), status=500, code="internal_error")


