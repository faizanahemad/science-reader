"""
Configuration constants for the OpenCode client library.

All configuration is driven by environment variables with sensible defaults.
This module centralizes config so other modules import from here rather than
reading os.environ directly.

Optional dependency note:
    ``sseclient-py`` can be used for SSE parsing, but this library implements
    SSE parsing manually with ``requests`` streaming to avoid the extra
    dependency.  The SSE wire format is simple (``event: ...\\ndata: ...\\n\\n``)
    and a hand-rolled parser is sufficient.
"""

import os
import logging

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# OpenCode server connection
# ---------------------------------------------------------------------------

OPENCODE_BASE_URL = os.environ.get("OPENCODE_BASE_URL", "http://localhost:4096")
"""Base URL for the ``opencode serve`` HTTP API."""

OPENCODE_SERVER_USERNAME = os.environ.get("OPENCODE_SERVER_USERNAME", "opencode")
"""HTTP Basic Auth username (default matches OpenCode default)."""

OPENCODE_SERVER_PASSWORD = os.environ.get("OPENCODE_SERVER_PASSWORD", "")
"""HTTP Basic Auth password.  Empty string disables auth."""

# ---------------------------------------------------------------------------
# Default model / provider
# ---------------------------------------------------------------------------

OPENCODE_DEFAULT_PROVIDER = os.environ.get("OPENCODE_DEFAULT_PROVIDER", "openrouter")
"""Provider ID used when no explicit provider is given."""

OPENCODE_DEFAULT_MODEL = os.environ.get("OPENCODE_DEFAULT_MODEL", "anthropic/claude-sonnet-4.5")
"""Model ID used when no explicit model is given."""


# Provider-to-model-ID mapping: how Flask model names map to OpenCode providerID/modelID.
# OpenCode expects {"providerID": "openrouter", "modelID": "anthropic/claude-sonnet-4.5"}
# while Flask uses "anthropic/claude-sonnet-4.5" or "openrouter/anthropic/claude-sonnet-4.5".
OPENROUTER_API_KEY = os.environ.get("OPENROUTER_API_KEY", "")
"""OpenRouter API key — used by both Flask direct LLM calls and OpenCode server."""

# ---------------------------------------------------------------------------
# Timeouts (seconds)
# ---------------------------------------------------------------------------

OPENCODE_SYNC_TIMEOUT = int(os.environ.get("OPENCODE_SYNC_TIMEOUT", "300"))
"""Timeout for synchronous LLM calls (POST /session/{id}/message)."""

OPENCODE_ASYNC_TIMEOUT = int(os.environ.get("OPENCODE_ASYNC_TIMEOUT", "10"))
"""Timeout for async prompt dispatch (POST /session/{id}/prompt_async)."""

OPENCODE_DEFAULT_TIMEOUT = int(os.environ.get("OPENCODE_DEFAULT_TIMEOUT", "30"))
"""Timeout for lightweight REST calls (list, get, delete, etc.)."""

OPENCODE_SSE_CONNECT_TIMEOUT = int(os.environ.get("OPENCODE_SSE_CONNECT_TIMEOUT", "15"))
"""Timeout for establishing the SSE connection."""

# ---------------------------------------------------------------------------
# SSE streaming
# ---------------------------------------------------------------------------

OPENCODE_SSE_RECONNECT_DELAY = float(
    os.environ.get("OPENCODE_SSE_RECONNECT_DELAY", "2.0")
)
"""Seconds to wait before reconnecting after an SSE drop."""

OPENCODE_SSE_MAX_RECONNECTS = int(os.environ.get("OPENCODE_SSE_MAX_RECONNECTS", "5"))
"""Maximum consecutive reconnection attempts for the SSE stream."""

# ---------------------------------------------------------------------------
# Permission auto-approve
# ---------------------------------------------------------------------------

OPENCODE_AUTO_APPROVE_PERMISSIONS = os.environ.get(
    "OPENCODE_AUTO_APPROVE_PERMISSIONS", "true"
).lower() in ("true", "1", "yes")
"""When True, automatically approve all tool-use permission requests."""

# ---------------------------------------------------------------------------
# Logging helper
# ---------------------------------------------------------------------------


def log_config_summary():
    """Log the active configuration (redacting the password)."""
    pw_display = "***" if OPENCODE_SERVER_PASSWORD else "(empty/disabled)"
    logger.info(
        "OpenCode client config: base_url=%s  user=%s  password=%s  "
        "provider=%s  model=%s  sync_timeout=%ss  sse_reconnect_delay=%ss",
        OPENCODE_BASE_URL,
        OPENCODE_SERVER_USERNAME,
        pw_display,
        OPENCODE_DEFAULT_PROVIDER,
        OPENCODE_DEFAULT_MODEL,
        OPENCODE_SYNC_TIMEOUT,
        OPENCODE_SSE_RECONNECT_DELAY,
    )
