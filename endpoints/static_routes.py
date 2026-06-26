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

import hashlib
import logging
import os
import re
from typing import Any

from flask import (
    Blueprint,
    Response,
    current_app,
    jsonify,
    make_response,
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

# ---------------------------------------------------------------------------
# Asset hash registry (Task 1)
# ---------------------------------------------------------------------------
# At server startup, compute SHA-256 content hashes for all JS/CSS files in
# the interface/ directory.  Used for cache-busting URLs (?h=<hash>) and
# dynamic CACHE_VERSION injection into the service worker.

_asset_hashes: dict[str, str] = {}   # "filename" -> "8-char hex hash"
_composite_hash: str = ""             # hash of all hashes, for CACHE_VERSION


def compute_asset_hashes() -> None:
    """Compute content hashes for all interface JS/CSS assets.

    Call once at app startup (during blueprint registration or app factory),
    before any requests are served.  Flask's ``use_reloader=True`` restarts
    the process on file changes, so hashes stay fresh in dev mode.
    """
    global _composite_hash
    _asset_hashes.clear()

    interface_dir = os.path.join(os.path.dirname(__file__), "..", "interface")
    interface_dir = os.path.normpath(interface_dir)

    # Skip third-party bundles with internal relative references
    skip_dirs = {"pdf.js", "node_modules"}

    for root, dirs, files in os.walk(interface_dir):
        dirs[:] = [d for d in dirs if d not in skip_dirs]
        for f in files:
            if f.endswith((".js", ".css")):
                filepath = os.path.join(root, f)
                relpath = os.path.relpath(filepath, interface_dir).replace("\\", "/")
                with open(filepath, "rb") as fh:
                    content_hash = hashlib.sha256(fh.read()).hexdigest()[:8]
                _asset_hashes[relpath] = content_hash

    # Composite hash for dynamic CACHE_VERSION (Task 8)
    all_hashes = "|".join(f"{k}={v}" for k, v in sorted(_asset_hashes.items()))
    _composite_hash = hashlib.sha256(all_hashes.encode()).hexdigest()[:8]
    logger.info(
        "Asset hash registry: %d files, composite=%s", len(_asset_hashes), _composite_hash
    )


# ---------------------------------------------------------------------------
# HTML hash injection (Task 2)
# ---------------------------------------------------------------------------

# Regex matches src="interface/foo.js" or href="/interface/foo.css?v=123" etc.
# Captures: (attr_prefix)(optional_slash + interface/)(filename.ext) — strips ?v=N
_ASSET_REF_RE = re.compile(
    r'((?:src|href)=["\'])(/?interface/)([\w\-./]+\.(?:js|css))(?:\?v=\d+)?'
)

_html_cache: dict[str, tuple[str, float]] = {}  # filename -> (processed_html, mtime)


def _inject_asset_hashes(html_content: str) -> str:
    """Replace interface/foo.js(?v=N) with interface/foo.js?h=<hash> in HTML."""

    def _replace(match: re.Match) -> str:
        prefix = match.group(1)      # 'src="' or 'href="'
        iface_path = match.group(2)  # 'interface/' or '/interface/'
        filename = match.group(3)    # 'common.js' or 'style.css'
        h = _asset_hashes.get(filename, "")
        if h:
            return f"{prefix}{iface_path}{filename}?h={h}"
        return match.group(0)  # no hash available, leave as-is

    return _ASSET_REF_RE.sub(_replace, html_content)


def _serve_html_with_hashes(filename: str, extra_transform=None) -> Response:
    """Read an HTML file, inject asset hashes, apply optional transform, return response.

    Parameters
    ----------
    filename : str
        Filename relative to the ``interface/`` directory (e.g. ``"interface.html"``).
    extra_transform : callable, optional
        A ``str -> str`` function applied *after* hash injection (e.g. to embed
        a conversation-id div for shared pages).
    """
    is_nocache = bool(current_app.config.get("SW_CACHE_NONCE"))
    html_path = os.path.join("interface", filename)
    current_mtime = os.path.getmtime(html_path)

    cached = _html_cache.get(filename)
    if (
        cached
        and cached[1] == current_mtime
        and not current_app.debug
        and not is_nocache
        and extra_transform is None
    ):
        html = cached[0]
    else:
        with open(html_path, "r", encoding="utf-8") as f:
            html = f.read()

        # In --no-cache mode, skip hash injection (Task 7)
        if not is_nocache:
            html = _inject_asset_hashes(html)

        if extra_transform is not None:
            html = extra_transform(html)

        # Only cache when there's no dynamic transform and not in debug/nocache mode
        if extra_transform is None and not current_app.debug and not is_nocache:
            _html_cache[filename] = (html, current_mtime)

    response = make_response(html)
    response.headers["Content-Type"] = "text/html; charset=utf-8"
    response.headers["Cache-Control"] = "no-cache"
    return response


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
    """Serve the main UI shell (with injected asset hashes for cache busting)."""
    return _serve_html_with_hashes("interface.html")


@static_bp.route("/interface/service-worker.js")
@limiter.limit("200 per minute")
def service_worker_js():
    """Serve service-worker.js with a dynamic CACHE_VERSION.

    Normal mode: CACHE_VERSION is replaced with a composite content hash
    of all interface assets.  Any file change produces a new hash, which
    triggers a SW reinstall and cache purge — no manual version bumping.

    ``--no-cache`` mode: CACHE_VERSION is replaced with a startup-time nonce
    that forces reinstall and cache purge on every server restart.
    """
    sw_path = os.path.join("interface", "service-worker.js")
    nonce = current_app.config.get("SW_CACHE_NONCE")

    with open(sw_path, "r", encoding="utf-8") as f:
        content = f.read()

    if nonce:
        # --no-cache mode: unique nonce per server start
        version_string = f"nocache-{nonce}"
        cache_control = "no-store"
    else:
        # Normal mode: composite hash of all interface assets (Task 8)
        version_string = f"v-{_composite_hash}" if _composite_hash else "v50"
        cache_control = "no-cache"

    content = re.sub(
        r'const CACHE_VERSION\s*=\s*"[^"]*"',
        f'const CACHE_VERSION = "{version_string}"',
        content,
        count=1,
    )

    return Response(content, mimetype="application/javascript", headers={
        "Cache-Control": cache_control,
        "Service-Worker-Allowed": "/interface/",
    })


@static_bp.route("/clear-sw-cache", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def clear_sw_cache():
    """Signal the client to clear all service worker caches.

    This endpoint doesn't clear caches server-side (SW caches are
    browser-local).  Instead it returns a success response that the
    client JS uses as confirmation to run the cache-clearing logic.
    """
    return jsonify({"success": True, "message": "Client should clear SW caches now."})

# PWA assets that must be publicly accessible (browsers fetch these without cookies).
# These contain no sensitive data and are required for PWA installability checks.
PWA_PUBLIC_PATHS = {
    "manifest.json",
    "icons/app-icon.svg",
    "icons/maskable-icon.svg",
}
PWA_CACHE_MAX_AGE_SECONDS = 60 * 60 * 24 * 30  # 30d to reduce repeated browser fetches.

# Static asset extensions that contain no user data and should return 403
# (not 302 redirect) when accessed without authentication.  This prevents
# cache poisoning of immutable hashed asset URLs.
_STATIC_ASSET_EXTENSIONS = frozenset({
    "js", "css", "svg", "png", "jpg", "jpeg", "gif", "ico",
    "woff", "woff2", "ttf", "eot", "map",
})


def _is_static_asset(path: str) -> bool:
    """Check if path is a static asset (not a conversation URL or HTML page)."""
    ext = path.rsplit(".", 1)[-1].lower() if "." in path else ""
    return ext in _STATIC_ASSET_EXTENSIONS


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
        # For static assets, return 403 with no-store to prevent cache poisoning
        # of immutable hashed URLs (a 302 redirect could be cached by the browser
        # under the original ?h= URL, breaking subsequent loads).
        if _is_static_asset(path):
            resp = make_response("Forbidden", 403)
            resp.headers["Cache-Control"] = "no-store"
            return resp
        return redirect("/login", code=302)

    if not path:
        return _serve_html_with_hashes("interface.html")

    # If the interface is nested under a user email folder, strip it.
    if email is not None and path.startswith(email) and path.count("/") >= 2:
        path = "/".join(path.split("/")[1:])

    # If the first path segment is a conversation_id the user owns, serve UI.
    try:
        conversation_id = path.split("/")[0]
        if checkConversationExists(email, conversation_id, users_dir=state.users_dir):
            return _serve_html_with_hashes("interface.html")
    except Exception as e:
        logger.error(f"Error checking conversation access: {str(e)}")

    # Serve static assets.  If the request has ?h=<hash>, the URL is
    # content-addressed — cache aggressively (Task 3).
    actual_path = path.replace("interface/", "").replace("interface/interface/", "")
    try:
        has_hash = request.args.get("h")
        if has_hash:
            resp = send_from_directory("interface", actual_path, max_age=31536000)
            resp.headers["Cache-Control"] = "public, max-age=31536000, immutable"
            return resp
        else:
            return send_from_directory("interface", actual_path, max_age=0)
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

    div_element = f'<div id="conversation_id" data-conversation_id="{conversation_id}" style="display: none;"></div>'

    def _embed_conversation_id(html: str) -> str:
        return html.replace("</body>", f"{div_element}</body>")

    return _serve_html_with_hashes("shared.html", extra_transform=_embed_conversation_id)


@static_bp.route("/")
@limiter.limit("200 per minute")
@login_required
def index():
    return redirect("/interface")
