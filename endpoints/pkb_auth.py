"""Dual-auth decorator for PKB endpoints.

Accepts EITHER:
- Flask session (existing login_required behavior)
- Bearer JWT token (for external agents/MCP/scripts)

Non-breaking: sits alongside existing @login_required and can be
swapped in per-route or globally when ready.
"""

import os
from functools import wraps

from flask import request, session, jsonify


MCP_JWT_SECRET = os.environ.get("MCP_JWT_SECRET", "")


def pkb_auth_required(f):
    """Accept either Flask session OR Bearer token for authentication."""
    @wraps(f)
    def decorated(*args, **kwargs):
        # Path 1: existing session auth
        if session.get("email"):
            request._pkb_email = session["email"]
            request._pkb_scopes = ["read", "write", "admin"]  # session = full access
            return f(*args, **kwargs)

        # Path 2: Bearer token
        auth_header = request.headers.get("Authorization", "")
        if auth_header.startswith("Bearer "):
            from mcp_server.auth import verify_jwt
            token = auth_header[7:]
            payload = verify_jwt(token, MCP_JWT_SECRET)
            if payload and "email" in payload:
                request._pkb_email = payload["email"]
                request._pkb_scopes = payload.get("scopes", ["read"])
                return f(*args, **kwargs)
            return jsonify({"error": "Invalid or expired token", "code": "invalid_token"}), 401

        # No auth
        return jsonify({"error": "Authentication required", "code": "unauthorized"}), 401
    return decorated


def get_pkb_email():
    """Get the authenticated user's email from either auth path."""
    return getattr(request, '_pkb_email', None)


def get_pkb_scopes():
    """Get the authenticated user's scopes."""
    return getattr(request, '_pkb_scopes', [])


def require_scope(scope):
    """Decorator to enforce a specific scope on a route."""
    def decorator(f):
        @wraps(f)
        def decorated(*args, **kwargs):
            scopes = get_pkb_scopes()
            if scope not in scopes:
                return jsonify({
                    "error": f"Insufficient scope: requires '{scope}'",
                    "code": "insufficient_scope"
                }), 403
            return f(*args, **kwargs)
        return decorated
    return decorator
