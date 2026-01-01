"""
Authentication + session helpers and routes.

This module centralizes:
- `login_required` decorator
- remember-me token storage/verification
- auth-related routes (`/login`, `/logout`, `/get_user_info`)

Design notes
------------
We avoid importing `server.py` to prevent circular imports. Shared folders and
flags are obtained from `endpoints.state.get_state()`.
"""

from __future__ import annotations

import json
import os
import secrets
from datetime import datetime, timedelta
from functools import wraps
from hashlib import sha256
from typing import Optional

from flask import Blueprint, jsonify, redirect, render_template_string, request, session, url_for

from endpoints.state import get_state
from extensions import limiter

auth_bp = Blueprint("auth", __name__)


def login_required(f):
    """
    Require a logged-in session (email + name in session).

    Preserves the existing behavior in `server.py`: if session is missing,
    redirect to `/login`.
    """

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("email") is None or session.get("name") is None:
            return redirect("/login", code=302)
        return f(*args, **kwargs)

    return decorated_function


def check_credentials(username: str, password: str) -> bool:
    """
    Validate user credentials.

    Notes
    -----
    This currently preserves the simple password check in `server.py`.
    """

    return os.getenv("PASSWORD", "XXXX") == password


def _tokens_file() -> str:
    """Absolute path to the remember-me token store JSON file."""

    state = get_state()
    return os.path.join(state.users_dir, "remember_tokens.json")


def generate_remember_token(email: str) -> str:
    """
    Generate a secure remember-me token for the user.

    If a valid token already exists for this email, return it instead.

    Parameters
    ----------
    email:
        User email identifier.

    Returns
    -------
    str
        Token string.
    """

    tokens_file = _tokens_file()
    current_time = datetime.now()

    tokens: Optional[dict] = None
    if os.path.exists(tokens_file):
        with open(tokens_file, "r") as f:
            tokens = json.load(f)

        # Return an existing valid token for this email, if present.
        for token, data in tokens.items():
            if data.get("email") == email and datetime.fromisoformat(data["expires_at"]) > current_time:
                return token

    if not tokens:
        tokens = {}

    random_token = secrets.token_hex(32)
    combined = f"{email}:{random_token}:{int(current_time.timestamp())}"
    token = sha256(combined.encode()).hexdigest()

    tokens[token] = {
        "email": email,
        "created_at": current_time.isoformat(),
        "expires_at": (current_time + timedelta(days=30)).isoformat(),
    }

    with open(tokens_file, "w") as f:
        json.dump(tokens, f)

    return token


def verify_remember_token(token: str) -> Optional[str]:
    """
    Verify a remember-me token and return the associated email if valid.

    Returns
    -------
    Optional[str]
        Email if token is valid and not expired, else None.
    """

    tokens_file = _tokens_file()
    if not os.path.exists(tokens_file):
        return None

    try:
        with open(tokens_file, "r") as f:
            tokens = json.load(f)

        token_data = tokens.get(token)
        if not token_data:
            return None

        expires_at = datetime.fromisoformat(token_data["expires_at"])
        if datetime.now() > expires_at:
            # Remove this expired token only.
            del tokens[token]
            with open(tokens_file, "w") as f:
                json.dump(tokens, f)
            return None

        return token_data.get("email")
    except Exception:
        # Preserve server.py behavior: don't hard-fail requests due to token store issues.
        return None


def cleanup_tokens() -> None:
    """Remove expired tokens from the remember-me store."""

    tokens_file = _tokens_file()
    if not os.path.exists(tokens_file):
        return

    try:
        with open(tokens_file, "r") as f:
            tokens = json.load(f)

        current_time = datetime.now()
        expired = [
            token
            for token, data in tokens.items()
            if current_time > datetime.fromisoformat(data["expires_at"])
        ]
        for token in expired:
            del tokens[token]

        with open(tokens_file, "w") as f:
            json.dump(tokens, f)
    except Exception:
        return


@auth_bp.before_app_request
def check_remember_token():
    """Check for remember-me token if session is not active."""

    if "email" in session:
        return None

    remember_token = request.cookies.get("remember_token")
    if not remember_token:
        return None

    email = verify_remember_token(remember_token)
    if not email:
        return None

    session.permanent = True
    session["email"] = email
    session["name"] = email
    session["created_at"] = datetime.now().isoformat()
    session["user_agent"] = request.user_agent.string
    return None


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    error = None
    if request.method == "POST":
        email = request.form["email"]
        password = request.form["password"]
        remember = request.form.get("remember") == "on"

        if check_credentials(email, password):
            session.permanent = True
            # The interface route now lives under the static_routes blueprint.
            # Preserve old behavior by redirecting to the same URL path.
            response = redirect("/interface")

            if remember:
                response.set_cookie(
                    "remember_token",
                    value=generate_remember_token(email),
                    expires=datetime.now() + timedelta(days=30),
                    secure=True,
                    httponly=True,
                    samesite="Lax",
                )

            session["email"] = email
            session["name"] = email
            session["created_at"] = datetime.now().isoformat()
            session["user_agent"] = request.user_agent.string
            return response

        error = "Invalid credentials"

    return render_template_string(open("interface/login.html").read(), error=error)


@auth_bp.route("/logout")
@limiter.limit("10 per minute")
@login_required
def logout():
    session.pop("name", None)
    session.pop("email", None)
    return render_template_string(
        """
            <h1>Logged out</h1>
            <p><a href="{{ url_for('auth.login') }}">Click here</a> to log in again. You can now close this Tab/Window.</p>
        """
    )


@auth_bp.route("/get_user_info")
@limiter.limit("100 per minute")
@login_required
def get_user_info():
    if "email" in session and "name" in session:
        return jsonify(name=session["name"], email=session["email"])
    return "Not logged in", 401


