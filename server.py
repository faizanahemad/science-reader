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
import requests as _requests

# Ensure local, sibling modules (e.g. `extensions.py`) are importable even when
# the server is launched from outside the repo root or imported via a package
# loader that doesn't put this directory on `sys.path`.
_THIS_DIR = os.path.dirname(os.path.abspath(__file__))
if _THIS_DIR not in sys.path:
    sys.path.insert(0, _THIS_DIR)

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

# --- OpenCode integration -------------------------------------------------
OPENCODE_AVAILABLE: bool = False

try:
    from opencode_client.config import OPENCODE_BASE_URL as _OPENCODE_BASE_URL
except Exception:
    _OPENCODE_BASE_URL = "http://localhost:4096"


def _check_opencode_health() -> bool:
    """
    Probe the OpenCode server health endpoint.

    Returns True if reachable, False otherwise.  Updates the module-level
    ``OPENCODE_AVAILABLE`` flag so other modules can check availability at
    import time.
    """
    global OPENCODE_AVAILABLE
    health_url = f"{_OPENCODE_BASE_URL.rstrip('/')}/global/health"
    try:
        resp = _requests.get(health_url, timeout=3)
        if resp.ok:
            logger.info("OpenCode server is available at %s", _OPENCODE_BASE_URL)
            OPENCODE_AVAILABLE = True
            return True
    except Exception:
        pass
    logger.warning(
        "OpenCode server not available at %s — OpenCode features will be disabled",
        _OPENCODE_BASE_URL,
    )
    OPENCODE_AVAILABLE = False
    return False


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
    conversation.clear_lockfile("artefacts")
    return conversation


# Populated in create_app()
folder: str = "storage"
login_not_needed: bool = False
cache_dir: str = ""
users_dir: str = ""
pdfs_dir: str = ""
locks_dir: str = ""
conversation_folder: str = ""



def _run_global_docs_migration(*, global_docs_dir: str, users_dir: str) -> None:
    """
    One-time idempotent migration: move existing flat global docs into their
    correct folder subdirectories based on DB folder assignments, and create
    real OS directories for all GlobalDocFolders rows.

    Safe to call on every startup — docs already in the correct location are
    skipped. Old flat directories are removed after a successful copy.
    """
    import hashlib
    import json
    import shutil
    import sqlite3
    from datetime import datetime

    db_path = os.path.join(users_dir, "users.db")
    if not os.path.exists(db_path):
        return  # DB not initialised yet; tables will be created right after

    def _md5(s: str) -> str:
        return hashlib.md5(s.encode()).hexdigest()

    def _folder_parts(conn, user_email, folder_id):
        parts, current, visited = [], folder_id, set()
        while current:
            if current in visited:
                logger.warning("Global docs migration: cycle in folder hierarchy at %s", current)
                break
            visited.add(current)
            row = conn.execute(
                "SELECT name, parent_id FROM GlobalDocFolders WHERE folder_id=? AND user_email=?",
                (current, user_email),
            ).fetchone()
            if not row:
                break
            parts.append(row[0])
            current = row[1]
        parts.reverse()
        return parts

    try:
        conn = sqlite3.connect(db_path)

        # Step 1 — create OS directories for all folders
        for folder_id, user_email in conn.execute(
            "SELECT folder_id, user_email FROM GlobalDocFolders"
        ).fetchall():
            user_root = os.path.join(global_docs_dir, _md5(user_email))
            parts = _folder_parts(conn, user_email, folder_id)
            if parts:
                os.makedirs(os.path.join(user_root, *parts), exist_ok=True)

        # Step 2 — move docs that are in wrong location
        docs = conn.execute(
            "SELECT doc_id, user_email, doc_storage, folder_id FROM GlobalDocuments"
        ).fetchall()

        updates = []
        for doc_id, user_email, old_storage, folder_id in docs:
            user_root = os.path.join(global_docs_dir, _md5(user_email))
            if folder_id:
                parts = _folder_parts(conn, user_email, folder_id)
                if not parts:
                    continue
                new_storage = os.path.join(user_root, *parts, doc_id)
            else:
                new_storage = os.path.join(user_root, doc_id)

            if old_storage == new_storage:
                continue
            if not os.path.isdir(old_storage):
                continue
            if os.path.exists(new_storage):
                continue

            try:
                os.makedirs(os.path.dirname(new_storage), exist_ok=True)
                shutil.copytree(old_storage, new_storage)
                # Patch _storage in index.json if present
                idx_path = os.path.join(new_storage, "index.json")
                if os.path.exists(idx_path):
                    with open(idx_path) as f:
                        data = json.load(f)
                    if "_storage" in data:
                        data["_storage"] = new_storage
                        with open(idx_path, "w") as f:
                            json.dump(data, f, indent=2)
                updates.append((doc_id, user_email, new_storage, old_storage))
            except Exception as exc:
                logger.error("Global docs migration: failed to move %s: %s", doc_id, exc)

        # Step 3 — update DB and delete old flat dirs
        if updates:
            now = datetime.now().isoformat()
            for doc_id, user_email, new_storage, old_storage in updates:
                conn.execute(
                    "UPDATE GlobalDocuments SET doc_storage=?, updated_at=? WHERE doc_id=? AND user_email=?",
                    (new_storage, now, doc_id, user_email),
                )
                shutil.rmtree(old_storage, ignore_errors=True)
            conn.commit()
            logger.info("Global docs migration: moved %d doc(s) into folder subdirectories.", len(updates))
        else:
            logger.info("Global docs migration: nothing to migrate.")

        conn.close()
    except Exception as exc:
        logger.error("Global docs migration failed (non-fatal): %s", exc)


def create_app(argv: Optional[list[str]] = None) -> Flask:
    """
    Flask app factory.

    This is the canonical way to create the app for:
    - `python server.py`
    - tests (via `app = create_app([...])`)
    """

    global \
        folder, \
        login_not_needed, \
        cache_dir, \
        users_dir, \
        pdfs_dir, \
        locks_dir, \
        conversation_folder

    folder, login_not_needed = _parse_argv(argv)
    check_environment()

    app = OurFlask(__name__)

    # Session config (legacy)
    app.config["SESSION_PERMANENT"] = True
    app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
    app.config.update(
        SESSION_COOKIE_SECURE=True,
        SESSION_COOKIE_HTTPONLY=True,
        SESSION_COOKIE_SAMESITE="None",
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

    _ext_cors_origins = [
        r"chrome-extension://[a-z]{32}",
        r"chrome-extension://[a-zA-Z]{32}",
        r"http://localhost:\d+",
        r"http://127\.0\.0\.1:\d+",
    ]

    CORS(
        app,
        resources={
            r"/ext/*": {
                "origins": _ext_cors_origins,
                "supports_credentials": True,
                "methods": ["GET", "POST", "PUT", "DELETE", "OPTIONS"],
                "allow_headers": ["Content-Type", "X-Requested-With"],
            },
            r"/login": {
                "origins": _ext_cors_origins,
                "supports_credentials": True,
                "methods": ["POST", "OPTIONS"],
                "allow_headers": ["Content-Type"],
            },
            r"/transcribe": {
                "origins": _ext_cors_origins,
                "supports_credentials": True,
                "methods": ["POST", "OPTIONS"],
                "allow_headers": ["Content-Type"],
            },
            r"/send_message/*": {
                "origins": _ext_cors_origins,
                "supports_credentials": True,
                "methods": ["POST", "OPTIONS"],
                "allow_headers": ["Content-Type"],
            },
            r"/create_temporary_conversation/*": {
                "origins": _ext_cors_origins,
                "supports_credentials": True,
                "methods": ["POST", "OPTIONS"],
                "allow_headers": ["Content-Type"],
            },
            r"/list_conversation_by_user/*": {
                "origins": _ext_cors_origins,
                "supports_credentials": True,
                "methods": ["GET", "OPTIONS"],
                "allow_headers": ["Content-Type"],
            },
            r"/list_messages_by_conversation/*": {
                "origins": _ext_cors_origins,
                "supports_credentials": True,
                "methods": ["GET", "OPTIONS"],
                "allow_headers": ["Content-Type"],
            },
            r"/get_conversation_details/*": {
                "origins": _ext_cors_origins,
                "supports_credentials": True,
                "methods": ["GET", "OPTIONS"],
                "allow_headers": ["Content-Type"],
            },
            r"/delete_conversation/*": {
                "origins": _ext_cors_origins,
                "supports_credentials": True,
                "methods": ["DELETE", "OPTIONS"],
                "allow_headers": ["Content-Type"],
            },
            r"/make_conversation_stateful/*": {
                "origins": _ext_cors_origins,
                "supports_credentials": True,
                "methods": ["PUT", "OPTIONS"],
                "allow_headers": ["Content-Type"],
            },
            r"/list_workspaces/*": {
                "origins": _ext_cors_origins,
                "supports_credentials": True,
                "methods": ["GET", "OPTIONS"],
                "allow_headers": ["Content-Type"],
            },
            r"/create_workspace/*": {
                "origins": _ext_cors_origins,
                "supports_credentials": True,
                "methods": ["POST", "OPTIONS"],
                "allow_headers": ["Content-Type"],
            },
            r"/model_catalog": {
                "origins": _ext_cors_origins,
                "supports_credentials": True,
                "methods": ["GET", "OPTIONS"],
                "allow_headers": ["Content-Type"],
            },
            r"/get_prompts": {
                "origins": _ext_cors_origins,
                "supports_credentials": True,
                "methods": ["GET", "OPTIONS"],
                "allow_headers": ["Content-Type"],
            },
            r"/get_prompt_by_name/*": {
                "origins": _ext_cors_origins,
                "supports_credentials": True,
                "methods": ["GET", "OPTIONS"],
                "allow_headers": ["Content-Type"],
            },
            r"/pkb/*": {
                "origins": _ext_cors_origins,
                "supports_credentials": True,
                "methods": ["GET", "POST", "OPTIONS"],
                "allow_headers": ["Content-Type"],
            },
            r"/get_conversation_output_docs/*": {
                "origins": [
                    "https://laingsimon.github.io",
                    "https://app.diagrams.net/",
                    "https://draw.io/",
                    "https://www.draw.io/",
                ]
            },
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
    global_docs_dir = os.path.join(os.getcwd(), folder, "global_docs")

    os.makedirs(cache_dir, exist_ok=True)
    os.makedirs(users_dir, exist_ok=True)
    os.makedirs(pdfs_dir, exist_ok=True)
    os.makedirs(locks_dir, exist_ok=True)
    os.makedirs(conversation_folder, exist_ok=True)
    os.makedirs(docs_folder, exist_ok=True)
    os.makedirs(global_docs_dir, exist_ok=True)

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
    conversation_cache = DefaultDictQueue(
        maxsize=200, default_factory=load_conversation
    )
    pinned_claims: dict[str, set] = {}

    init_state(
        folder=os.path.dirname(users_dir),
        users_dir=users_dir,
        pdfs_dir=pdfs_dir,
        locks_dir=locks_dir,
        cache_dir=cache_dir,
        conversation_folder=conversation_folder,
        global_docs_dir=global_docs_dir,
        login_not_needed=login_not_needed,
        conversation_cache=conversation_cache,
        pinned_claims=pinned_claims,
        cache=cache,
        limiter=limiter,
    )

    # Ensure schema exists
    create_tables(users_dir=users_dir, logger=logger)

    # One-time migration: move existing flat global docs into folder subdirectories.
    # Safe to run on every startup — skips docs already in the correct location.
    _run_global_docs_migration(global_docs_dir=global_docs_dir, users_dir=users_dir)

    # Register all endpoint groups
    register_blueprints(app)


    return app


def main(argv: Optional[list[str]] = None) -> int:
    """CLI entrypoint for `python server.py`."""

    app = create_app(argv)

    # Best-effort token cleanup (legacy behavior)
    from endpoints.auth import cleanup_tokens

    cleanup_tokens()

    from mcp_server import (
        start_mcp_server,
        start_pkb_mcp_server,
        start_docs_mcp_server,
        start_artefacts_mcp_server,
        start_conversation_mcp_server,
        start_prompts_actions_mcp_server,
        start_code_runner_mcp_server,
    )

    start_mcp_server()
    start_pkb_mcp_server()
    start_docs_mcp_server()
    start_artefacts_mcp_server()
    start_conversation_mcp_server()
    start_prompts_actions_mcp_server()
    start_code_runner_mcp_server()


    # Check OpenCode server availability (non-blocking, just logs status)
    _check_opencode_health()
    app.run(host="0.0.0.0", port=5000, threaded=True)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
