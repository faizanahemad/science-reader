"""
Authentication for the restart server.

Reuses the same PASSWORD-based auth pattern from the main application's
``endpoints/auth.py``, but redirects to the restart dashboard (``/``)
instead of ``/interface``.

Environment variables
---------------------
PASSWORD : str
    Shared password used for all logins (same as the main server).
"""

from __future__ import annotations

import os
from datetime import datetime
from functools import wraps

from flask import Blueprint, redirect, render_template, request, session

auth_bp = Blueprint("auth", __name__)


def login_required(f):
    """Decorator: redirect to ``/login`` when the session has no email."""

    @wraps(f)
    def decorated_function(*args, **kwargs):
        if session.get("email") is None:
            return redirect("/login", code=302)
        return f(*args, **kwargs)

    return decorated_function


def check_credentials(email: str, password: str) -> bool:
    """Validate credentials against the ``PASSWORD`` env var."""
    expected = os.getenv("PASSWORD", "XXXX")
    return expected == password


@auth_bp.route("/login", methods=["GET", "POST"])
def login():
    """Render the login form (GET) or validate credentials (POST)."""
    error = None
    if request.method == "POST":
        email = request.form.get("email", "")
        password = request.form.get("password", "")

        if check_credentials(email, password):
            session.permanent = True
            session["email"] = email
            session["name"] = email
            session["created_at"] = datetime.now().isoformat()
            return redirect("/")

        error = "Invalid credentials"

    return render_template("login.html", error=error)


@auth_bp.route("/logout")
@login_required
def logout():
    """Clear the session and redirect to the login page."""
    session.clear()
    return redirect("/login")
