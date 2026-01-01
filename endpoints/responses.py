"""
Standard JSON response helpers.

Policy (important)
------------------
- We **do not** wrap successful list/array responses, to avoid breaking clients.
- We **do** standardize error responses to a canonical shape:

    {
      "status": "error",
      "error": "<message>",
      "message": "<message>",
      "code": "<optional_machine_code>",
      ... extra fields ...
    }
"""

from __future__ import annotations

from typing import Any, Optional

from flask import Response, jsonify


def json_error(
    message: str,
    *,
    status: int = 400,
    code: Optional[str] = None,
    **extra: Any,
) -> tuple[Response, int]:
    """
    Return a standardized JSON error response.
    """

    payload: dict[str, Any] = {"status": "error", "error": message, "message": message}
    if code:
        payload["code"] = code
    payload.update(extra)
    return jsonify(payload), status


def json_ok(
    payload: Optional[dict[str, Any]] = None,
    *,
    status: int = 200,
    **extra: Any,
) -> tuple[Response, int]:
    """
    Return a standardized JSON success response (for object-shaped payloads only).
    """

    body: dict[str, Any] = {"status": "success"}
    if payload:
        body.update(payload)
    body.update(extra)
    return jsonify(body), status


