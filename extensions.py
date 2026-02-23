"""
Flask extension singletons.

Why this exists
--------------
Many route handlers in `server.py` use extension instances (e.g. Flask-Limiter)
at import-time via decorators like `@limiter.limit(...)`.

If endpoint modules import `server.py` to access those instances, we will
immediately create circular-import hazards once `server.py` starts importing
endpoints to register blueprints.

Instead, we keep extension singletons in a tiny, dependency-free module that
both `server.py` and endpoint modules can import safely.
"""

from __future__ import annotations

from flask import request, session
from flask_caching import Cache
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address


cache = Cache()


def limiter_key_func() -> str:
    """
    Rate-limit key function.

    Prefer per-user email when present (logged in), otherwise fall back to remote IP.
    """

    email = None
    if session:
        email = session.get("email")
    return email or get_remote_address()


limiter = Limiter(
    key_func=limiter_key_func,
    default_limits=["200 per hour", "10 per minute"],
)


@limiter.request_filter
def _exempt_websocket_requests():
    """Exempt WebSocket upgrade requests from rate limiting.

    WebSocket connections are long-lived and should not count against
    short-duration rate limits. The limiter's after_request hook would
    also corrupt WebSocket frames by injecting HTTP headers.
    """
    return request.headers.get('Upgrade', '').lower() == 'websocket'


