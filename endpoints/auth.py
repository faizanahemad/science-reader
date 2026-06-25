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
    """Absolute path to the remember-me token store JSON file (legacy, for migration)."""

    state = get_state()
    return os.path.join(state.users_dir, "remember_tokens.json")


def _get_tokens_db():
    """Get a connection to users.db for remember_tokens table."""
    import sqlite3

    state = get_state()
    db_path = os.path.join(state.users_dir, "users.db")
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def _migrate_tokens_json_to_db():
    """One-time migration of remember_tokens.json → users.db RememberTokens table."""
    tokens_file = _tokens_file()
    if not os.path.exists(tokens_file):
        return
    try:
        with open(tokens_file, "r") as f:
            tokens = json.load(f)
        if not tokens:
            os.rename(tokens_file, tokens_file + ".migrated")
            return
        conn = _get_tokens_db()
        cur = conn.cursor()
        for token, data in tokens.items():
            cur.execute(
                "INSERT OR IGNORE INTO RememberTokens (token, email, created_at, expires_at) VALUES (?,?,?,?)",
                (token, data["email"], data["created_at"], data["expires_at"]),
            )
        conn.commit()
        conn.close()
        os.rename(tokens_file, tokens_file + ".migrated")
    except Exception:
        pass  # Non-fatal; will retry next time


def generate_remember_token(email: str) -> str:
    """
    Generate a secure remember-me token for the user.

    If a valid token already exists for this email, return it instead.
    """
    # One-time migration
    _migrate_tokens_json_to_db()

    conn = _get_tokens_db()
    current_time = datetime.now()

    # Check for existing valid token
    row = conn.execute(
        "SELECT token FROM RememberTokens WHERE email=? AND expires_at > ?",
        (email, current_time.isoformat()),
    ).fetchone()
    if row:
        conn.close()
        return row["token"]

    # Generate new token
    random_token = secrets.token_hex(32)
    combined = f"{email}:{random_token}:{int(current_time.timestamp())}"
    token = sha256(combined.encode()).hexdigest()

    conn.execute(
        "INSERT OR REPLACE INTO RememberTokens (token, email, created_at, expires_at) VALUES (?,?,?,?)",
        (token, email, current_time.isoformat(), (current_time + timedelta(days=30)).isoformat()),
    )
    conn.commit()
    conn.close()
    return token


def verify_remember_token(token: str) -> Optional[str]:
    """
    Verify a remember-me token and return the associated email if valid.
    """
    try:
        conn = _get_tokens_db()
        row = conn.execute(
            "SELECT email, expires_at FROM RememberTokens WHERE token=?", (token,)
        ).fetchone()
        if not row:
            conn.close()
            return None

        if datetime.now() > datetime.fromisoformat(row["expires_at"]):
            conn.execute("DELETE FROM RememberTokens WHERE token=?", (token,))
            conn.commit()
            conn.close()
            return None

        conn.close()
        return row["email"]
    except Exception:
        return None


def cleanup_tokens() -> None:
    """Remove expired tokens from the remember-me store."""
    try:
        conn = _get_tokens_db()
        conn.execute(
            "DELETE FROM RememberTokens WHERE expires_at < ?",
            (datetime.now().isoformat(),),
        )
        conn.commit()
        conn.close()
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
@limiter.limit("100 per minute")
@login_required
def logout():
    session.clear()
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


