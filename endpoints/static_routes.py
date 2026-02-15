"""
Static + interface routes.

This module hosts routes that serve UI assets / basic infra endpoints:
- favicon/loader/static assets
- `/interface` (main UI)
- lock/session maintenance endpoints
- `/shared/<conversation_id>` shared view
- `/` redirect
"""

from __future__ import annotations

import logging
import os
from typing import Any

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    redirect,
    send_from_directory,
    stream_with_context,
    request,
    session,
)

from Conversation import Conversation
from database.conversations import checkConversationExists
from endpoints.auth import login_required
from endpoints.session_utils import get_session_identity
from endpoints.state import get_state
from extensions import cache, limiter

static_bp = Blueprint("static_routes", __name__)
logger = logging.getLogger(__name__)


def cached_get_file(file_url: str):
    """
    Retrieve a file from cache, disk, or remote URL and stream it as chunks.

    Notes
    -----
    - This preserves the behavior in `server.py`: always returns PDF bytes (by
      converting when needed).
    - Cache keys use the original URL/path.
    """

    from converters import convert_any_to_pdf
    import requests

    chunk_size = 1024
    file_data = cache.get(file_url)

    if file_data is not None:
        logger.info(f"cached_get_file for {file_url} found in cache")
        for chunk in file_data:
            yield chunk
        return

    if os.path.exists(file_url):
        try:
            pdf_file_url = convert_any_to_pdf(file_url)
            logger.info(
                f"cached_get_file: serving PDF file {pdf_file_url} (original: {file_url})"
            )
        except Exception as e:
            logger.error(f"cached_get_file: failed to convert {file_url} to PDF: {e}")
            pdf_file_url = file_url

        file_data = []
        with open(pdf_file_url, "rb") as f:
            while True:
                chunk = f.read(chunk_size)
                if chunk:
                    file_data.append(chunk)
                    yield chunk
                if not chunk:
                    break
        cache.set(file_url, file_data)
        return

    # Local path that doesn't exist — don't attempt requests.get() on it
    if file_url and (
        file_url.startswith("/") or (len(file_url) > 1 and file_url[1] == ":")
    ):
        logger.error(f"cached_get_file: local file not found: {file_url}")
        yield b""
        return

    file_data = []
    try:
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
            "(KHTML, like Gecko) Chrome/58.0.3029.110 Safari/537.36"
        }
        req = requests.get(file_url, stream=True, verify=False, headers=headers)
    except requests.exceptions.RequestException as e:
        logger.error(f"Failed to download file: {e}")
        req = requests.get(file_url, stream=True, verify=False)

    for chunk in req.iter_content(chunk_size=chunk_size):
        file_data.append(chunk)
        yield chunk
    cache.set(file_url, file_data)


def _load_conversation_for_lock_ops(conversation_id: str) -> Conversation:
    """
    Load a conversation and clear common lock files, mirroring server.py behavior.
    """

    state = get_state()
    path = os.path.join(state.conversation_folder, conversation_id)
    conversation: Conversation = Conversation.load_local(path)
    conversation.clear_lockfile("")
    conversation.clear_lockfile("all")
    conversation.clear_lockfile("message_operations")
    conversation.clear_lockfile("memory")
    conversation.clear_lockfile("messages")
    conversation.clear_lockfile("uploaded_documents_list")
    return conversation


@static_bp.route("/clear_session", methods=["GET"])
@limiter.limit("1000 per minute")
@login_required
def clear_session_route():
    """Clear the current Flask session."""

    session.clear()
    return jsonify({"result": "session cleared"})


@static_bp.route("/favicon.ico")
@limiter.limit("300 per minute")
def favicon():
    return send_from_directory(
        os.path.join(current_app.root_path, "static"),
        "favicon.ico",
        mimetype="image/vnd.microsoft.icon",
    )


@static_bp.route("/loader.gif")
@limiter.limit("100 per minute")
def loader():
    return send_from_directory(
        os.path.join(current_app.root_path, "static"),
        "gradient-loader.gif",
        mimetype="image/gif",
    )


@static_bp.route("/static/<path:filename>")
@limiter.limit("1000 per minute")
def static_files(filename: str):
    return send_from_directory(os.path.join(current_app.root_path, "static"), filename)


@static_bp.route("/clear_locks")
@limiter.limit("100 per minute")
@login_required
def clear_locks():
    """Clear all lock files in the locks directory."""

    state = get_state()
    for file in os.listdir(state.locks_dir):
        os.remove(os.path.join(state.locks_dir, file))
    return jsonify({"result": "locks cleared"})


@static_bp.route("/get_lock_status/<conversation_id>", methods=["GET"])
@limiter.limit("100 per minute")
@login_required
def get_lock_status(conversation_id: str):
    """Get comprehensive lock status for a conversation."""

    try:
        conversation = _load_conversation_for_lock_ops(conversation_id)
        status: Any = conversation.get_lock_status()
        return jsonify(status)
    except Exception as e:
        return (
            jsonify(
                {
                    "conversation_id": conversation_id,
                    "error": str(e),
                    "locks_status": {},
                    "any_locked": False,
                    "stale_locks": [],
                    "can_cleanup": False,
                }
            ),
            500,
        )


@static_bp.route("/ensure_locks_cleared/<conversation_id>", methods=["POST"])
@limiter.limit("50 per minute")
@login_required
def ensure_locks_cleared(conversation_id: str):
    """Safely clear locks for a conversation with verification."""

    try:
        conversation = _load_conversation_for_lock_ops(conversation_id)
        result = conversation.force_clear_all_locks()
        return jsonify(
            {
                "success": True,
                "cleared": result["cleared"],
                "message": f"{result['count']} locks cleared successfully",
            }
        )
    except Exception as e:
        return (
            jsonify({"success": False, "cleared": [], "message": str(e)}),
            500,
        )


@static_bp.route("/force_clear_locks/<conversation_id>", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def force_clear_locks(conversation_id: str):
    """Emergency endpoint to force clear all locks for a conversation."""

    try:
        conversation = _load_conversation_for_lock_ops(conversation_id)
        result = conversation.force_clear_all_locks()
        return jsonify(
            {
                "success": True,
                "cleared": result["cleared"],
                "warning": f"Force cleared {result['count']} locks. This may cause data corruption if locks were still in use.",
            }
        )
    except Exception as e:
        return (
            jsonify({"success": False, "cleared": [], "warning": str(e)}),
            500,
        )


@static_bp.route("/interface", strict_slashes=False)
@limiter.limit("200 per minute")
@login_required
def interface():
    """Serve the main UI shell."""

    return send_from_directory("interface", "interface.html", max_age=0)


# PWA assets that must be publicly accessible (browsers fetch these without cookies).
# These contain no sensitive data and are required for PWA installability checks.
PWA_PUBLIC_PATHS = {
    "manifest.json",
    "icons/app-icon.svg",
    "icons/maskable-icon.svg",
}
PWA_CACHE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30d to reduce repeated browser fetches.


@static_bp.route("/interface/<path:path>", strict_slashes=False)
@limiter.limit("1000 per minute")
def interface_combined_route(path: str):
    """
    Serve the UI shell for conversation paths and static interface assets.

    This preserves the bespoke logic previously implemented in
    `server.py:interface_combined`.

    Note: PWA manifest and icons are served without authentication because:
    1. Browsers fetch manifests without credentials for installability checks
    2. Service workers need these during initial install before session exists
    3. These files contain no sensitive user data
    """
    # Serve PWA assets (manifest.json and icons) without authentication.
    # Required for browser PWA installability checks which don't include cookies.
    if path in PWA_PUBLIC_PATHS:
        try:
            response = send_from_directory(
                "interface", path, max_age=PWA_CACHE_MAX_AGE_SECONDS
            )
            response.headers["Cache-Control"] = (
                f"public, max-age={PWA_CACHE_MAX_AGE_SECONDS}, immutable"
            )
            return response
        except FileNotFoundError:
            pass  # Fall through to normal handling

    state = get_state()
    email, _name, loggedin = get_session_identity()

    if not loggedin or email is None:
        return redirect("/login", code=302)

    if not path:
        return send_from_directory("interface", "interface.html", max_age=0)

    # If the interface is nested under a user email folder, strip it.
    if email is not None and path.startswith(email) and path.count("/") >= 2:
        path = "/".join(path.split("/")[1:])

    # If the first path segment is a conversation_id the user owns, serve UI.
    try:
        conversation_id = path.split("/")[0]
        if checkConversationExists(email, conversation_id, users_dir=state.users_dir):
            return send_from_directory("interface", "interface.html", max_age=0)
    except Exception as e:
        logger.error(f"Error checking conversation access: {str(e)}")

    try:
        return send_from_directory(
            "interface",
            path.replace("interface/", "").replace("interface/interface/", ""),
            max_age=0,
        )
    except FileNotFoundError:
        return "File not found", 404


def _is_missing_local_path(file_url):
    """Return True if file_url looks like a local filesystem path that doesn't exist."""
    if not file_url:
        return False
    return (
        file_url.startswith("/") or (len(file_url) > 1 and file_url[1] == ":")
    ) and not os.path.exists(file_url)


@static_bp.route("/proxy", methods=["GET"])
@login_required
def proxy_route():
    file_url = request.args.get("file")
    logger.debug(
        f"Proxying file {file_url}, exists on disk = {os.path.exists(file_url or '')}"
    )
    if _is_missing_local_path(file_url):
        return Response("File not found on disk", status=404)
    return Response(
        stream_with_context(cached_get_file(file_url)), mimetype="application/pdf"
    )


@static_bp.route("/proxy_shared", methods=["GET"])
def proxy_shared_route():
    file_url = request.args.get("file")
    logger.debug(
        f"Proxying file {file_url}, exists on disk = {os.path.exists(file_url or '')}"
    )
    if _is_missing_local_path(file_url):
        return Response("File not found on disk", status=404)
    return Response(
        stream_with_context(cached_get_file(file_url)), mimetype="application/pdf"
    )


@static_bp.route("/shared/<conversation_id>")
@limiter.limit("200 per minute")
def shared(conversation_id: str):
    """Serve the shared view page, embedding conversation_id into the HTML."""

    html_file_path = os.path.join("interface", "shared.html")
    with open(html_file_path, "r", encoding="utf-8") as file:
        html_content = file.read()

    div_element = f'<div id="conversation_id" data-conversation_id="{conversation_id}" style="display: none;"></div>'
    modified_html = html_content.replace("</body>", f"{div_element}</body>")
    return Response(modified_html, mimetype="text/html")


@static_bp.route("/")
@limiter.limit("200 per minute")
@login_required
def index():
    return redirect("/interface")
