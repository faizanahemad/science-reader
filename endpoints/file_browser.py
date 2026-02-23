"""
File browser endpoints.

Provides REST endpoints for browsing, reading, writing, renaming, and
deleting files relative to the server root directory.  All paths are
resolved against SERVER_ROOT and validated to prevent directory-traversal
attacks.
"""

from __future__ import annotations

import logging
import os
import shutil

from flask import Blueprint, request

from endpoints.auth import login_required
from endpoints.responses import json_error, json_ok

file_browser_bp = Blueprint("file_browser", __name__)
logger = logging.getLogger(__name__)

SERVER_ROOT = os.path.realpath(
    os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _safe_resolve(relative_path: str) -> str | None:
    """Resolve a relative path to an absolute path, ensuring it stays within SERVER_ROOT.

    Parameters
    ----------
    relative_path : str
        Path relative to the server root directory.

    Returns
    -------
    str or None
        Absolute resolved path if safe, None if path escapes SERVER_ROOT.
    """
    resolved = os.path.realpath(os.path.join(SERVER_ROOT, relative_path))
    if not resolved.startswith(SERVER_ROOT + os.sep) and resolved != SERVER_ROOT:
        return None
    return resolved


# ---------------------------------------------------------------------------
# Endpoints
# ---------------------------------------------------------------------------


@file_browser_bp.route("/file-browser/tree")
@login_required
def tree():
    """List directory entries for the given path.

    Query Parameters
    ----------------
    path : str, optional
        Relative path to the directory (default ``"."`` for server root).

    Returns
    -------
    JSON
        ``{"path": "<relative>", "entries": [{"name": ..., "type": ...}, ...]}``
        Directories are listed first, then files, both sorted
        case-insensitively.
    """
    rel_path = request.args.get("path", ".")
    resolved = _safe_resolve(rel_path)
    if resolved is None:
        return json_error("Path escapes server root", status=403, code="path_forbidden")

    try:
        entries: list[dict] = []
        with os.scandir(resolved) as it:
            for entry in it:
                if entry.is_dir(follow_symlinks=False):
                    entries.append({"name": entry.name, "type": "dir"})
                else:
                    try:
                        size = entry.stat(follow_symlinks=False).st_size
                    except OSError:
                        size = 0
                    entries.append({"name": entry.name, "type": "file", "size": size})

        # Sort: directories first, then files, both alphabetical case-insensitive
        dirs = sorted(
            [e for e in entries if e["type"] == "dir"],
            key=lambda e: e["name"].lower(),
        )
        files = sorted(
            [e for e in entries if e["type"] == "file"],
            key=lambda e: e["name"].lower(),
        )
        return json_ok({"path": rel_path, "entries": dirs + files})
    except OSError:
        logger.exception("Failed to list directory: %s", resolved)
        return json_error("Failed to list directory", status=500, code="os_error")


@file_browser_bp.route("/file-browser/read")
@login_required
def read_file():
    """Read the contents of a file.

    Query Parameters
    ----------------
    path : str
        Relative path to the file.
    force : str, optional
        If ``"true"``, skip the 2 MB size guard.

    Returns
    -------
    JSON
        ``{"path": ..., "content": ..., "size": N, "extension": ..., "is_binary": bool}``.
        For binary files ``content`` is ``null``.  For oversized files
        ``too_large`` is ``true`` and ``content`` is ``null``.
    """
    rel_path = request.args.get("path", "")
    if not rel_path:
        return json_error("Missing 'path' parameter", status=400, code="missing_param")

    resolved = _safe_resolve(rel_path)
    if resolved is None:
        return json_error("Path escapes server root", status=403, code="path_forbidden")

    if not os.path.isfile(resolved):
        return json_error("File not found", status=404, code="not_found")

    try:
        size = os.path.getsize(resolved)
        extension = os.path.splitext(resolved)[1]

        # Binary check: look for null bytes in first 8 KB
        with open(resolved, "rb") as fh:
            chunk = fh.read(8192)
        if b"\x00" in chunk:
            return json_ok({
                "path": rel_path,
                "is_binary": True,
                "content": None,
                "size": size,
            })

        # Size guard (2 MB)
        force = request.args.get("force", "false").lower() == "true"
        if size > 2 * 1024 * 1024 and not force:
            return json_ok({
                "path": rel_path,
                "too_large": True,
                "size": size,
                "content": None,
            })

        with open(resolved, "r", encoding="utf-8", errors="replace") as fh:
            content = fh.read()

        return json_ok({
            "path": rel_path,
            "content": content,
            "size": size,
            "extension": extension,
            "is_binary": False,
        })
    except OSError:
        logger.exception("Failed to read file: %s", resolved)
        return json_error("Failed to read file", status=500, code="os_error")


@file_browser_bp.route("/file-browser/write", methods=["POST"])
@login_required
def write_file():
    """Write content to a file, creating parent directories as needed.

    Request Body (JSON)
    -------------------
    path : str
        Relative path to the target file.
    content : str
        Text content to write.

    Returns
    -------
    JSON
        ``json_ok`` with ``{"size": N}`` on success.
    """
    data = request.get_json(silent=True) or {}
    rel_path = data.get("path", "")
    content = data.get("content")

    if not rel_path or content is None:
        return json_error(
            "Missing 'path' and/or 'content' in request body",
            status=400,
            code="missing_fields",
        )

    resolved = _safe_resolve(rel_path)
    if resolved is None:
        return json_error("Path escapes server root", status=403, code="path_forbidden")

    try:
        parent = os.path.dirname(resolved)
        os.makedirs(parent, exist_ok=True)
        with open(resolved, "w", encoding="utf-8") as fh:
            fh.write(content)
        size = os.path.getsize(resolved)
        return json_ok({"size": size})
    except OSError:
        logger.exception("Failed to write file: %s", resolved)
        return json_error("Failed to write file", status=500, code="os_error")


@file_browser_bp.route("/file-browser/mkdir", methods=["POST"])
@login_required
def mkdir():
    """Create a directory (and any missing parents).

    Request Body (JSON)
    -------------------
    path : str
        Relative path of the directory to create.

    Returns
    -------
    JSON
        ``json_ok`` on success.
    """
    data = request.get_json(silent=True) or {}
    rel_path = data.get("path", "")

    if not rel_path:
        return json_error("Missing 'path' in request body", status=400, code="missing_fields")

    resolved = _safe_resolve(rel_path)
    if resolved is None:
        return json_error("Path escapes server root", status=403, code="path_forbidden")

    try:
        os.makedirs(resolved, exist_ok=True)
        return json_ok()
    except OSError:
        logger.exception("Failed to create directory: %s", resolved)
        return json_error("Failed to create directory", status=500, code="os_error")


@file_browser_bp.route("/file-browser/rename", methods=["POST"])
@login_required
def rename():
    """Rename or move a file or directory.

    Request Body (JSON)
    -------------------
    old_path : str
        Current relative path.
    new_path : str
        Desired relative path.

    Returns
    -------
    JSON
        ``json_ok`` on success.  Returns 404 if *old_path* does not exist,
        409 if *new_path* already exists.
    """
    data = request.get_json(silent=True) or {}
    old_rel = data.get("old_path", "")
    new_rel = data.get("new_path", "")

    if not old_rel or not new_rel:
        return json_error(
            "Missing 'old_path' and/or 'new_path' in request body",
            status=400,
            code="missing_fields",
        )

    old_resolved = _safe_resolve(old_rel)
    new_resolved = _safe_resolve(new_rel)

    if old_resolved is None or new_resolved is None:
        return json_error("Path escapes server root", status=403, code="path_forbidden")

    if not os.path.exists(old_resolved):
        return json_error("Source path not found", status=404, code="not_found")

    if os.path.exists(new_resolved):
        return json_error("Destination path already exists", status=409, code="conflict")

    try:
        os.rename(old_resolved, new_resolved)
        return json_ok()
    except OSError:
        logger.exception("Failed to rename %s -> %s", old_resolved, new_resolved)
        return json_error("Failed to rename", status=500, code="os_error")


@file_browser_bp.route("/file-browser/delete", methods=["POST"])
@login_required
def delete():
    """Delete a file or directory.

    Request Body (JSON)
    -------------------
    path : str
        Relative path of the item to delete.
    recursive : bool, optional
        If ``true``, non-empty directories are removed recursively
        (default ``false``).

    Returns
    -------
    JSON
        ``json_ok`` on success.  Returns 403 if attempting to delete
        SERVER_ROOT itself.
    """
    data = request.get_json(silent=True) or {}
    rel_path = data.get("path", "")
    recursive = data.get("recursive", False)

    if not rel_path:
        return json_error("Missing 'path' in request body", status=400, code="missing_fields")

    resolved = _safe_resolve(rel_path)
    if resolved is None:
        return json_error("Path escapes server root", status=403, code="path_forbidden")

    if resolved == SERVER_ROOT:
        return json_error("Cannot delete server root", status=403, code="path_forbidden")

    if not os.path.exists(resolved):
        return json_error("Path not found", status=404, code="not_found")

    try:
        if os.path.isfile(resolved) or os.path.islink(resolved):
            os.remove(resolved)
        elif os.path.isdir(resolved):
            if recursive:
                shutil.rmtree(resolved)
            else:
                try:
                    os.rmdir(resolved)
                except OSError:
                    return json_error(
                        "Directory is not empty; set 'recursive' to true",
                        status=400,
                        code="dir_not_empty",
                    )
        return json_ok()
    except OSError:
        logger.exception("Failed to delete: %s", resolved)
        return json_error("Failed to delete", status=500, code="os_error")
