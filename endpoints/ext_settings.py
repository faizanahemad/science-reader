"""
Extension settings endpoints.

Provides ``/ext/settings`` GET/PUT so the Chrome extension can persist
user-specific preferences (default model, prompt, history length, etc.)
in the main backend's ``UserDetails.user_preferences`` JSON under an
``"extension"`` key.

This avoids a separate ``ExtensionSettings`` table — settings live alongside
the main app's own preferences but in a dedicated namespace that won't
collide.

Endpoints
---------
- GET /ext/settings  — read extension settings
- PUT /ext/settings  — update extension settings
"""

from __future__ import annotations

import json
import logging

from flask import Blueprint, jsonify, request, session

from database.users import (
    getUserFromUserDetailsTable,
    updateUserInfoInUserDetailsTable,
)
from endpoints.ext_auth import auth_required
from endpoints.responses import json_error
from endpoints.state import get_state

ext_settings_bp = Blueprint("ext_settings", __name__)
logger = logging.getLogger(__name__)

# Default extension settings (returned when nothing stored yet).
_DEFAULTS = {
    "default_model": "google/gemini-2.5-flash",
    "default_prompt": "preamble_short",
    "history_length": 10,
    "auto_save": False,
}


def _get_extension_settings(user_email: str) -> dict:
    """
    Read the ``extension`` sub-key from ``user_preferences`` JSON.

    Returns merged result of defaults + stored values so callers always
    get a complete settings dict.
    """
    state = get_state()
    user = getUserFromUserDetailsTable(
        user_email, users_dir=state.users_dir, logger=logger
    )

    settings = dict(_DEFAULTS)

    if user and user.get("user_preferences"):
        try:
            prefs = json.loads(user["user_preferences"])
            ext = prefs.get("extension")
            if isinstance(ext, dict):
                settings.update(ext)
        except (json.JSONDecodeError, TypeError):
            pass  # Corrupt JSON — return defaults

    return settings


def _set_extension_settings(user_email: str, updates: dict) -> dict:
    """
    Merge *updates* into the ``extension`` sub-key of ``user_preferences``
    and persist to DB.  Returns the merged settings dict.
    """
    state = get_state()
    user = getUserFromUserDetailsTable(
        user_email, users_dir=state.users_dir, logger=logger
    )

    # Parse existing preferences (or start fresh)
    prefs: dict = {}
    if user and user.get("user_preferences"):
        try:
            prefs = json.loads(user["user_preferences"])
            if not isinstance(prefs, dict):
                prefs = {}
        except (json.JSONDecodeError, TypeError):
            prefs = {}

    # Merge into extension namespace
    ext = prefs.get("extension", {})
    if not isinstance(ext, dict):
        ext = {}
    ext.update(updates)
    prefs["extension"] = ext

    updateUserInfoInUserDetailsTable(
        user_email,
        user_preferences=json.dumps(prefs),
        users_dir=state.users_dir,
        logger=logger,
    )

    # Return merged with defaults
    result = dict(_DEFAULTS)
    result.update(ext)
    return result


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@ext_settings_bp.route("/ext/settings", methods=["GET"])
@auth_required
def get_settings():
    """Get extension settings for the authenticated user."""
    try:
        email = session.get("email")
        settings = _get_extension_settings(email)
        return jsonify({"settings": settings})
    except Exception:
        logger.exception("Error getting extension settings")
        return json_error("Failed to get settings", status=500)


@ext_settings_bp.route("/ext/settings", methods=["PUT"])
@auth_required
def update_settings():
    """Update extension settings for the authenticated user."""
    try:
        email = session.get("email")
        data = request.get_json() or {}
        if not data:
            return json_error("No settings provided", status=400)

        settings = _set_extension_settings(email, data)
        return jsonify({"settings": settings})
    except Exception:
        logger.exception("Error updating extension settings")
        return json_error("Failed to update settings", status=500)
