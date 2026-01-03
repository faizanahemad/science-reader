"""
Flask application entrypoint.

This file is intentionally **thin**:
- Parse CLI args
- Initialize extensions (Limiter/Cache/Session/CORS)
- Initialize shared `AppState`
- Ensure DB schema exists
- Register endpoint blueprints
- Run the server (when executed as __main__)

All route handlers live in `endpoints/*`.
"""

from __future__ import annotations

import argparse
import logging
import os
import platform
import sys
from datetime import timedelta
from typing import Optional

from flask import Flask
from flask.json.provider import JSONProvider
from flask_cors import CORS
from flask_session import Session

from Conversation import Conversation
from common import DefaultDictQueue
from database.connection import create_tables
from endpoints import register_blueprints
from endpoints.state import init_state
from extensions import cache, limiter

sys.setrecursionlimit(sys.getrecursionlimit() * 16)

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class FlaskJSONProvider(JSONProvider):
    """JSON provider that uses stdlib `json` (keeps legacy behavior)."""

    def dumps(self, obj, **kwargs) -> str:  # type: ignore[override]
        import json

        return json.dumps(obj, **kwargs)

    def loads(self, s: str, **kwargs):  # type: ignore[override]
        import json

        return json.loads(s, **kwargs)


class OurFlask(Flask):
    json_provider_class = FlaskJSONProvider


def _parse_argv(argv: Optional[list[str]] = None) -> tuple[str, bool]:
    """
    Parse CLI args for running the server.

    Returns
    -------
    (folder, login_not_needed)
    """

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "--folder",
        help="The folder where the DocIndex files are stored",
        required=False,
        default=None,
    )
    parser.add_argument(
        "--login_not_needed",
        help="Whether we use google login or not.",
        action="store_true",
    )
    args = parser.parse_args(argv)
    folder = args.folder or "storage"
    return folder, bool(args.login_not_needed)


def check_environment() -> None:
    """Log basic runtime environment info (legacy helper)."""

    logger.info(f"Python version: {sys.version}")
    logger.info(f"Platform: {platform.platform()}")
    logger.info(f"CPU Architecture: {platform.machine()}")
    logger.info(f"System: {platform.system()}")


def load_conversation(conversation_id: str) -> Conversation:
    """
    Load a conversation from disk and clear common lockfiles.

    This mirrors the legacy `server.py` behavior and is used by the
    `DefaultDictQueue` cache factory.
    """

    path = os.path.join(conversation_folder, conversation_id)
    conversation: Conversation = Conversation.load_local(path)
    conversation.clear_lockfile("")
    conversation.clear_lockfile("all")
    conversation.clear_lockfile("message_operations")
    conversation.clear_lockfile("memory")
    conversation.clear_lockfile("messages")
    conversation.clear_lockfile("uploaded_documents_list")
    return conversation


# Populated in create_app()
folder: str = "storage"
login_not_needed: bool = False
cache_dir: str = ""
users_dir: str = ""
pdfs_dir: str = ""
locks_dir: str = ""
conversation_folder: str = ""


def create_app(argv: Optional[list[str]] = None) -> Flask:
    """
    Flask app factory.

    This is the canonical way to create the app for:
    - `python server.py`
    - tests (via `app = create_app([...])`)
    """

    global folder, login_not_needed, cache_dir, users_dir, pdfs_dir, locks_dir, conversation_folder

    folder, login_not_needed = _parse_argv(argv)
    check_environment()

    app = OurFlask(__name__)

    # Session config (legacy)
    app.config["SESSION_PERMANENT"] = True
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="Lax",
        SESSION_REFRESH_EACH_REQUEST=True,
        SESSION_COOKIE_NAME="session_id",
        SESSION_COOKIE_PATH="/",
        PERMANENT_SESSION_LIFETIME=timedelta(days=30),
    )
    app.config["SESSION_TYPE"] = "filesystem"

    # OAuth / secret config (legacy)
    app.config["GOOGLE_CLIENT_ID"] = os.environ.get("GOOGLE_CLIENT_ID")
    app.config["GOOGLE_CLIENT_SECRET"] = os.environ.get("GOOGLE_CLIENT_SECRET")
    app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
    app.secret_key = os.environ.get("SECRET_KEY")

    # Limiter config (legacy)
    app.config["RATELIMIT_STRATEGY"] = "moving-window"
    app.config["RATELIMIT_STORAGE_URL"] = "memory://"
    limiter.init_app(app)

    Session(app)
    CORS(
        app,
        resources={
            r"/get_conversation_output_docs/*": {
                "origins": [
                    "https://laingsimon.github.io",
                    "https://app.diagrams.net/",
                    "https://draw.io/",
                    "https://www.draw.io/",
                ]
            }
        },
    )

    # Storage layout
    os.makedirs(os.path.join(os.getcwd(), folder), exist_ok=True)
    cache_dir = os.path.join(os.getcwd(), folder, "cache")
    users_dir = os.path.join(os.getcwd(), folder, "users")
    pdfs_dir = os.path.join(os.getcwd(), folder, "pdfs")
    locks_dir = os.path.join(folder, "locks")
    conversation_folder = os.path.join(os.getcwd(), folder, "conversations")
    docs_folder = os.path.join(os.getcwd(), folder, "documents")

    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(users_dir, exist_ok=True)
    os.makedirs(pdfs_dir, exist_ok=True)
    os.makedirs(locks_dir, exist_ok=True)
    os.makedirs(conversation_folder, exist_ok=True)
    os.makedirs(docs_folder, exist_ok=True)

    # Clear locks on startup
    for file in os.listdir(locks_dir):
        os.remove(os.path.join(locks_dir, file))

    cache.init_app(
        app,
        config={
            "CACHE_TYPE": "filesystem",
            "CACHE_DIR": cache_dir,
            "CACHE_DEFAULT_TIMEOUT": 7 * 24 * 60 * 60,
        },
    )

    # Shared state for blueprints
    conversation_cache = DefaultDictQueue(maxsize=200, default_factory=load_conversation)
    pinned_claims: dict[str, set] = {}

    init_state(
        folder=os.path.dirname(users_dir),
        users_dir=users_dir,
        pdfs_dir=pdfs_dir,
        locks_dir=locks_dir,
        cache_dir=cache_dir,
        conversation_folder=conversation_folder,
        login_not_needed=login_not_needed,
        conversation_cache=conversation_cache,
        pinned_claims=pinned_claims,
        cache=cache,
        limiter=limiter,
    )

    # Ensure schema exists
    create_tables(users_dir=users_dir, logger=logger)

    # Register all endpoint groups
    register_blueprints(app)

    return app


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint for `python server.py`."""

    app = create_app(argv)

    # Best-effort token cleanup (legacy behavior)
    from endpoints.auth import cleanup_tokens

    cleanup_tokens()
    app.run(host="0.0.0.0", port=5000, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


