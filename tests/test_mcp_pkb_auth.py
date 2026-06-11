"""Security regression tests for the PKB MCP server's identity scoping.

Covers the M1 fix from `pkb_external_access_ui_mcp_rest_auth.plan.md`: every PKB
MCP tool MUST scope data access to the JWT-authenticated identity (stored by
`JWTAuthMiddleware` in the `_mcp_request_context` thread-local), NOT to the
client-supplied `user_email` argument. Otherwise a holder of any valid token
could read/modify another user's PKB (broken object-level authorization / IDOR).
"""
import logging
import re
from pathlib import Path

import pytest

from mcp_server.pkb import _effective_email
from mcp_server.mcp_app import _mcp_request_context

PKB_SRC = Path(__file__).resolve().parents[1] / "mcp_server" / "pkb.py"


@pytest.fixture(autouse=True)
def _reset_request_context():
    """Isolate the per-request thread-local between tests."""
    old = getattr(_mcp_request_context, "user_email", None)
    try:
        yield
    finally:
        if old is None:
            if hasattr(_mcp_request_context, "user_email"):
                del _mcp_request_context.user_email
        else:
            _mcp_request_context.user_email = old


def test_effective_email_overrides_spoofed_supplied(caplog):
    """A token for user A must win over a spoofed user_email for user B."""
    _mcp_request_context.user_email = "alice@example.com"
    with caplog.at_level(logging.WARNING, logger="mcp_server.pkb"):
        result = _effective_email("attacker_victim@example.com")
    assert result == "alice@example.com"
    assert any("ignoring client-supplied" in r.message for r in caplog.records)


def test_effective_email_allows_matching_supplied(caplog):
    _mcp_request_context.user_email = "alice@example.com"
    with caplog.at_level(logging.WARNING, logger="mcp_server.pkb"):
        result = _effective_email("alice@example.com")
    assert result == "alice@example.com"
    # No spoof => no warning.
    assert not any("ignoring client-supplied" in r.message for r in caplog.records)


def test_effective_email_empty_supplied_uses_token(caplog):
    _mcp_request_context.user_email = "alice@example.com"
    with caplog.at_level(logging.WARNING, logger="mcp_server.pkb"):
        assert _effective_email("") == "alice@example.com"
    assert not any("ignoring client-supplied" in r.message for r in caplog.records)


def test_effective_email_fails_closed_when_unauthenticated():
    """No verified identity on the request => refuse, never trust the argument."""
    if hasattr(_mcp_request_context, "user_email"):
        del _mcp_request_context.user_email
    with pytest.raises(PermissionError):
        _effective_email("anybody@example.com")


def test_effective_email_fails_closed_on_unknown():
    _mcp_request_context.user_email = "unknown"
    with pytest.raises(PermissionError):
        _effective_email("anybody@example.com")


def test_no_tool_scopes_to_raw_user_email():
    """Source guard: every `.for_user(...)` in a tool must route through
    `_effective_email`, so a newly-added tool cannot reintroduce the IDOR bug."""
    src = PKB_SRC.read_text()
    # The raw, unscoped pattern must never appear.
    assert ".for_user(user_email)" not in src
    # Every for_user call that passes user_email must wrap it in _effective_email.
    bad = [
        m.group(0)
        for m in re.finditer(r"\.for_user\([^)]*\)", src)
        if "user_email" in m.group(0) and "_effective_email(user_email)" not in m.group(0)
    ]
    assert not bad, f"unscoped for_user call sites found: {bad}"
