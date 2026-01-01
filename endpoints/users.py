"""
User-related endpoints (preferences + memory).

This module extracts user preference/memory endpoints from `server.py` into a
Flask Blueprint.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request, session

from database.users import getUserFromUserDetailsTable, updateUserInfoInUserDetailsTable
from endpoints.auth import login_required
from endpoints.responses import json_error
from endpoints.session_utils import get_session_identity
from endpoints.state import get_state
from extensions import limiter


users_bp = Blueprint("users", __name__)
logger = logging.getLogger(__name__)

@users_bp.route("/get_user_detail", methods=["GET"])
@limiter.limit("25 per minute")
@login_required
def get_user_detail_route():
    """
    GET API endpoint to retrieve user memory/details.

    Returns:
        JSON with the user's memory information.
    """

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    state = get_state()
    user_details = getUserFromUserDetailsTable(email, users_dir=state.users_dir, logger=logger)
    if user_details is None:
        return jsonify({"text": ""})

    return jsonify({"text": user_details.get("user_memory", "")})


@users_bp.route("/get_user_preference", methods=["GET"])
@limiter.limit("25 per minute")
@login_required
def get_user_preference_route():
    """
    GET API endpoint to retrieve user preferences.

    Returns:
        JSON with the user's preference information.
    """

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    state = get_state()
    user_details = getUserFromUserDetailsTable(email, users_dir=state.users_dir, logger=logger)
    if user_details is None:
        return jsonify({"text": ""})

    return jsonify({"text": user_details.get("user_preferences", "")})


@users_bp.route("/modify_user_detail", methods=["POST"])
@limiter.limit("15 per minute")
@login_required
def modify_user_detail_route():
    """
    POST API endpoint to update user memory/details.

    Expects:
        JSON with "text" field containing the new user memory data
    """

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        memory_text = request.json.get("text") if request.is_json and request.json else None
        if memory_text is None:
            return json_error("Missing 'text' field in request", status=400, code="bad_request")

        state = get_state()
        success = updateUserInfoInUserDetailsTable(email, user_memory=memory_text, users_dir=state.users_dir, logger=logger)
        if success:
            return jsonify({"message": "User details updated successfully"})
        return json_error("Failed to update user details", status=500, code="internal_error")
    except Exception as e:
        logger.error(f"Error in modify_user_detail: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


@users_bp.route("/modify_user_preference", methods=["POST"])
@limiter.limit("15 per minute")
@login_required
def modify_user_preference_route():
    """
    POST API endpoint to update user preferences.

    Expects:
        JSON with "text" field containing the new user preferences data
    """

    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        preferences_text = request.json.get("text") if request.is_json and request.json else None
        if preferences_text is None:
            return json_error("Missing 'text' field in request", status=400, code="bad_request")

        state = get_state()
        success = updateUserInfoInUserDetailsTable(
            email, user_preferences=preferences_text, users_dir=state.users_dir, logger=logger
        )
        if success:
            return jsonify({"message": "User preferences updated successfully"})
        return json_error("Failed to update user preferences", status=500, code="internal_error")
    except Exception as e:
        logger.error(f"Error in modify_user_preference: {e}")
        return json_error(f"An error occurred: {str(e)}", status=500, code="internal_error")


