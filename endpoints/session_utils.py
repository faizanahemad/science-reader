"""
Session utilities shared across endpoint modules.

Why this exists
---------------
During the refactor, many endpoint modules carried a local `_check_login()`
helper copied from legacy `server.py`. This module provides a single canonical
implementation to avoid duplication.
"""

from __future__ import annotations

from typing import Optional, Tuple

from flask import session


def get_session_identity() -> Tuple[Optional[str], Optional[str], bool]:
    """
    Return `(email, name, loggedin)` from the current Flask session.

    Returns
    -------
    (email, name, loggedin)
        - email: session['email'] if present
        - name: session['name'] if present
        - loggedin: True iff both email and name are present
    """

    email = dict(session).get("email", None)
    name = dict(session).get("name", None)
    return email, name, email is not None and name is not None


