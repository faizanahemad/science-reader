"""
Code runner endpoints.

This module extracts the `/run_code_once` route from `server.py` into a Flask
Blueprint.
"""

from __future__ import annotations

import logging

from flask import Blueprint, request

from endpoints.auth import login_required
from extensions import limiter


logger = logging.getLogger(__name__)
code_runner_bp = Blueprint("code_runner", __name__)


@code_runner_bp.route("/run_code_once", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def run_code_once_route():
    """
    Run a single code string via the project's code runner.

    Expected JSON payload:
    {
        "code_string": "<python code>"
    }
    """

    code_string = (request.json or {}).get("code_string")
    from code_runner import run_code_once  # local import to avoid heavy import at startup

    return run_code_once(code_string)


