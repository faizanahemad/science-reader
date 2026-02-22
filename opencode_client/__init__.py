"""
opencode_client — Python HTTP client library for ``opencode serve``.

This package provides three main classes:

- :class:`OpencodeClient` — low-level HTTP wrapper for every REST endpoint.
- :class:`SSEBridge` — translates OpenCode SSE events to Flask streaming chunks.
- :class:`SessionManager` — maps Flask conversation IDs to OpenCode session IDs.

Quick start::

    from opencode_client import OpencodeClient, SSEBridge, SessionManager

Configuration is driven by environment variables.  See :mod:`opencode_client.config`
for all available settings.
"""

from opencode_client.client import OpencodeClient
from opencode_client.config import (
    OPENCODE_AUTO_APPROVE_PERMISSIONS,
    OPENCODE_BASE_URL,
    OPENCODE_DEFAULT_MODEL,
    OPENCODE_DEFAULT_PROVIDER,
    OPENCODE_DEFAULT_TIMEOUT,
    OPENCODE_SERVER_PASSWORD,
    OPENCODE_SERVER_USERNAME,
    OPENCODE_SSE_RECONNECT_DELAY,
)
from opencode_client.session_manager import SessionManager
from opencode_client.sse_bridge import SSEBridge

__all__ = [
    "OpencodeClient",
    "SSEBridge",
    "SessionManager",
    "OPENCODE_BASE_URL",
    "OPENCODE_SERVER_USERNAME",
    "OPENCODE_SERVER_PASSWORD",
    "OPENCODE_DEFAULT_PROVIDER",
    "OPENCODE_DEFAULT_MODEL",
    "OPENCODE_DEFAULT_TIMEOUT",
    "OPENCODE_SSE_RECONNECT_DELAY",
    "OPENCODE_AUTO_APPROVE_PERMISSIONS",
]
