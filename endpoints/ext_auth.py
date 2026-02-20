"""
Extension authentication endpoints.

Provides ``/ext/auth/login``, ``/ext/auth/verify``, and ``/ext/auth/logout``
so the Chrome extension can authenticate against the main backend using
session cookies (same mechanism as the web UI).

The ``auth_required`` decorator is also defined here for use on any ``/ext/*``
endpoint that needs a logged-in session but should return JSON 401 instead of
an HTML redirect.
"""

from __future__ import annotations

import logging
from datetime import datetime
from functools import wraps

from flask import Blueprint, jsonify, request, session

from endpoints.auth import check_credentials
from endpoints.responses import json_error
from extensions import limiter

ext_auth_bp = Blueprint("ext_auth", __name__)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Decorator
# ---------------------------------------------------------------------------


def auth_required(f):
    """Require an authenticated session, returning JSON 401 on failure.

    Identical check to ``login_required`` but returns a JSON error body
    instead of a 302 redirect, which is what API / extension callers expect.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("email") is None or session.get("name") is None:
            return json_error(
                "Authentication required", status=401, code="unauthorized"
            )
        return f(*args, **kwargs)

    return decorated_function


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@ext_auth_bp.route("/ext/auth/login", methods=["POST"])
@limiter.limit("10 per minute")
def ext_login():
    """Authenticate via email/password and create a Flask session.

    Returns
    -------
    JSON
        ``{"success": true, "email": ..., "name": ...}`` on success,
        or a JSON error on failure.
    """
    data = request.get_json(silent=True)
    if not data:
        return json_error("Missing request body", status=400)

    email = (data.get("email") or "").strip()
    password = data.get("password") or ""

    if not email or not password:
        return json_error("Email and password required", status=400)

    if not check_credentials(email, password):
        return json_error("Invalid credentials", status=401)

    session.permanent = True
    session["email"] = email
    session["name"] = email
    session["created_at"] = datetime.now().isoformat()
    session["user_agent"] = request.user_agent.string

    return jsonify(
        {
            "success": True,
            "email": email,
            "name": email.split("@")[0],
        }
    )


@ext_auth_bp.route("/ext/auth/verify", methods=["GET", "POST"])
@limiter.limit("100 per minute")
def ext_verify():
    """Return whether the current session is valid."""
    email = session.get("email")
    if email:
        return jsonify({"valid": True, "email": email})
    return jsonify({"valid": False}), 401


@ext_auth_bp.route("/ext/auth/logout", methods=["POST"])
@limiter.limit("10 per minute")
def ext_logout():
    """Clear the current session."""
    session.clear()
    return jsonify({"message": "Logged out successfully"})
