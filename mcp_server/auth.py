"""
JWT authentication for the MCP web search server.

Provides:
- ``verify_jwt`` — decode and validate a JWT bearer token.
- ``generate_token`` — create a signed JWT for a given email / expiry.
- CLI entry-point (``python -m mcp_server.auth``) to mint tokens from
  the command line.

Tokens are signed with HS256 using the ``MCP_JWT_SECRET`` environment
variable.  Clients send the raw JWT string as a Bearer token; the
server decodes it on every request via Starlette middleware (see
``mcp_server.mcp_app``).

Dependencies: PyJWT (``pip install PyJWT``).
"""

from __future__ import annotations

import argparse
import logging
import os
import sys
from datetime import datetime, timedelta, timezone
from typing import Any

import jwt  # PyJWT

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Token verification
# ---------------------------------------------------------------------------


def verify_jwt(token: str, secret: str) -> dict[str, Any] | None:
    """Decode and validate a JWT token.

    Parameters
    ----------
    token:
        The raw JWT string (without the ``Bearer `` prefix).
    secret:
        The HS256 signing secret (``MCP_JWT_SECRET``).

    Returns
    -------
    dict | None
        The decoded payload on success, or ``None`` if the token is
        invalid, expired, or cannot be decoded.
    """
    try:
        payload: dict[str, Any] = jwt.decode(token, secret, algorithms=["HS256"])
        return payload
    except jwt.ExpiredSignatureError:
        logger.debug("JWT token has expired")
        return None
    except jwt.InvalidTokenError as exc:
        logger.debug("JWT validation failed: %s", exc)
        return None


# ---------------------------------------------------------------------------
# Token generation
# ---------------------------------------------------------------------------


def generate_token(
    secret: str,
    email: str,
    days: int = 365,
    scopes: list[str] | None = None,
) -> str:
    """Create a signed JWT bearer token.

    Parameters
    ----------
    secret:
        HS256 signing secret.
    email:
        Email embedded in the ``email`` claim — used as client identifier.
    days:
        Token lifetime in days (default 365).
    scopes:
        List of granted scopes (default ``["search"]``).

    Returns
    -------
    str
        The encoded JWT string, ready to use as ``Authorization: Bearer <token>``.
    """
    if scopes is None:
        scopes = ["search"]

    now = datetime.now(timezone.utc)
    payload: dict[str, Any] = {
        "email": email,
        "scopes": scopes,
        "iat": now,
        "exp": now + timedelta(days=days),
    }
    return jwt.encode(payload, secret, algorithm="HS256")


# ---------------------------------------------------------------------------
# CLI entry-point  (python -m mcp_server.auth)
# ---------------------------------------------------------------------------


def _cli_main() -> int:
    """Generate an MCP bearer token from the command line.

    Usage::

        MCP_JWT_SECRET=mysecret python -m mcp_server.auth \\
            --email user@example.com --days 365
    """
    parser = argparse.ArgumentParser(
        description="Generate a JWT bearer token for the MCP web search server.",
    )
    parser.add_argument(
        "--email",
        required=True,
        help="Email address to embed in the token (used as client id).",
    )
    parser.add_argument(
        "--days",
        type=int,
        default=365,
        help="Token lifetime in days (default: 365).",
    )
    parser.add_argument(
        "--secret",
        default=None,
        help=(
            "JWT signing secret.  Falls back to the MCP_JWT_SECRET "
            "environment variable if not provided."
        ),
    )
    args = parser.parse_args()

    secret = args.secret or os.getenv("MCP_JWT_SECRET", "")
    if not secret:
        print(
            "ERROR: No JWT secret provided.  Set MCP_JWT_SECRET env var "
            "or pass --secret.",
            file=sys.stderr,
        )
        return 1

    token = generate_token(secret=secret, email=args.email, days=args.days)
    expiry = datetime.now(timezone.utc) + timedelta(days=args.days)

    print(f"Generated MCP bearer token (expires: {expiry.strftime('%Y-%m-%d')}):")
    print(token)
    print()
    print("Use in client config:")
    print(f"  Authorization: Bearer {token}")
    return 0


if __name__ == "__main__":
    raise SystemExit(_cli_main())
