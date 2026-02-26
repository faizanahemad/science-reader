"""
Document folder management endpoints.

Provides CRUD operations for user-scoped document folders that enable
hierarchical organisation of global documents. Folders can be nested via
parent_id and documents can be assigned to exactly one folder at a time.
"""

from __future__ import annotations

import logging

from flask import Blueprint, jsonify, request, session

from endpoints.auth import login_required
from endpoints.request_context import get_state_and_keys
from endpoints.responses import json_error
from extensions import limiter

from database.doc_folders import (
    create_folder,
    rename_folder,
    move_folder,
    delete_folder,
    list_folders,
    get_folder,
    assign_doc_to_folder,
    get_docs_in_folder,
)
from database.global_docs import delete_global_doc


doc_folders_bp = Blueprint("doc_folders", __name__)
logger = logging.getLogger(__name__)


def _get_user_context():
    """Extract user_email and users_dir from request context.

    Returns (users_dir, user_email) or raises a tuple (error_response, None)
    that callers can check.
    """
    state, keys = get_state_and_keys()
    email = session.get("email", "")
    users_dir = state.users_dir if state else None
    return users_dir, email


# ---------------------------------------------------------------------------
# LIST all folders
# ---------------------------------------------------------------------------


@doc_folders_bp.route("/doc_folders", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def list_folders_route():
    """List all folders for the authenticated user."""
    users_dir, email = _get_user_context()
    if not email or not users_dir:
        return json_error("Not authenticated", 401)

    folders = list_folders(users_dir=users_dir, user_email=email)
    return jsonify({"status": "ok", "folders": folders})


# ---------------------------------------------------------------------------
# CREATE folder
# ---------------------------------------------------------------------------


@doc_folders_bp.route("/doc_folders", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def create_folder_route():
    """Create a new folder. Body: {name: str, parent_id?: str}."""
    users_dir, email = _get_user_context()
    if not email or not users_dir:
        return json_error("Not authenticated", 401)

    data = request.get_json(force=True) or {}
    name = (data.get("name") or "").strip()
    if not name:
        return json_error("Folder name is required", 400)

    parent_id = data.get("parent_id") or None

    folder_id = create_folder(
        users_dir=users_dir, user_email=email, name=name, parent_id=parent_id
    )
    if not folder_id:
        return json_error("Failed to create folder", 500)

    return jsonify({"status": "ok", "folder_id": folder_id})


# ---------------------------------------------------------------------------
# RENAME / REPARENT folder
# ---------------------------------------------------------------------------


@doc_folders_bp.route("/doc_folders/<folder_id>", methods=["PATCH"])
@limiter.limit("100 per minute")
@login_required
def update_folder_route(folder_id: str):
    """Rename or reparent a folder. Body: {name?: str, parent_id?: str}."""
    users_dir, email = _get_user_context()
    if not email or not users_dir:
        return json_error("Not authenticated", 401)

    folder = get_folder(users_dir=users_dir, user_email=email, folder_id=folder_id)
    if folder is None:
        return json_error("Folder not found", 404)

    data = request.get_json(force=True) or {}
    new_name = data.get("name")
    new_parent_id = data.get("parent_id")

    if new_name is not None:
        new_name = new_name.strip()
        if not new_name:
            return json_error("Folder name cannot be empty", 400)
        rename_folder(
            users_dir=users_dir,
            user_email=email,
            folder_id=folder_id,
            new_name=new_name,
        )

    if "parent_id" in data:
        move_folder(
            users_dir=users_dir,
            user_email=email,
            folder_id=folder_id,
            new_parent_id=new_parent_id,
        )

    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# DELETE folder
# ---------------------------------------------------------------------------


@doc_folders_bp.route("/doc_folders/<folder_id>", methods=["DELETE"])
@limiter.limit("100 per minute")
@login_required
def delete_folder_route(folder_id: str):
    """Delete a folder.

    Query params:
        action: 'move_to_parent' (default) — moves docs and child folders to
                the deleted folder's parent.
                'delete_docs' — deletes docs in the direct folder, moves
                sub-folder orphans to parent, then deletes the folder.
    """
    users_dir, email = _get_user_context()
    if not email or not users_dir:
        return json_error("Not authenticated", 401)

    folder = get_folder(users_dir=users_dir, user_email=email, folder_id=folder_id)
    if folder is None:
        return json_error("Folder not found", 404)

    action = request.args.get("action", "move_to_parent")
    parent_id = folder.get("parent_id")  # may be None (root)

    if action == "move_to_parent":
        # Move direct docs to parent folder
        direct_doc_ids = get_docs_in_folder(
            users_dir=users_dir, user_email=email, folder_id=folder_id, recursive=False
        )
        for doc_id in direct_doc_ids:
            assign_doc_to_folder(
                users_dir=users_dir,
                user_email=email,
                doc_id=doc_id,
                folder_id=parent_id,
            )

        # Move direct child folders to parent
        all_folders = list_folders(users_dir=users_dir, user_email=email)
        child_folders = [f for f in all_folders if f["parent_id"] == folder_id]
        for child in child_folders:
            move_folder(
                users_dir=users_dir,
                user_email=email,
                folder_id=child["folder_id"],
                new_parent_id=parent_id,
            )

    elif action == "delete_docs":
        # Delete docs in the direct folder only
        direct_doc_ids = get_docs_in_folder(
            users_dir=users_dir, user_email=email, folder_id=folder_id, recursive=False
        )
        for doc_id in direct_doc_ids:
            delete_global_doc(users_dir=users_dir, user_email=email, doc_id=doc_id)

        # Move sub-folder orphans to parent
        all_folders = list_folders(users_dir=users_dir, user_email=email)
        child_folders = [f for f in all_folders if f["parent_id"] == folder_id]
        for child in child_folders:
            move_folder(
                users_dir=users_dir,
                user_email=email,
                folder_id=child["folder_id"],
                new_parent_id=parent_id,
            )
    else:
        return json_error(f"Unknown action: {action}", 400)

    delete_folder(users_dir=users_dir, user_email=email, folder_id=folder_id)
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# ASSIGN doc to folder
# ---------------------------------------------------------------------------


@doc_folders_bp.route("/doc_folders/<folder_id>/assign", methods=["POST"])
@limiter.limit("100 per minute")
@login_required
def assign_doc_route(folder_id: str):
    """Assign a document to a folder. Body: {doc_id: str}.

    Special case: folder_id == 'root' means unfile the doc (folder_id=None).
    """
    users_dir, email = _get_user_context()
    if not email or not users_dir:
        return json_error("Not authenticated", 401)

    data = request.get_json(force=True) or {}
    doc_id = data.get("doc_id")
    if not doc_id:
        return json_error("doc_id is required", 400)

    target_folder_id = None if folder_id == "root" else folder_id

    # Validate folder exists (unless unfiling)
    if target_folder_id is not None:
        folder = get_folder(
            users_dir=users_dir, user_email=email, folder_id=target_folder_id
        )
        if folder is None:
            return json_error("Folder not found", 404)

    assign_doc_to_folder(
        users_dir=users_dir, user_email=email, doc_id=doc_id, folder_id=target_folder_id
    )
    return jsonify({"status": "ok"})


# ---------------------------------------------------------------------------
# LIST docs in folder
# ---------------------------------------------------------------------------


@doc_folders_bp.route("/doc_folders/<folder_id>/docs", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def list_docs_in_folder_route(folder_id: str):
    """List doc_ids in a folder. ?recursive=true to include sub-folders."""
    users_dir, email = _get_user_context()
    if not email or not users_dir:
        return json_error("Not authenticated", 401)

    recursive = request.args.get("recursive", "false").lower() == "true"
    target_folder_id = None if folder_id == "root" else folder_id

    doc_ids = get_docs_in_folder(
        users_dir=users_dir,
        user_email=email,
        folder_id=target_folder_id,
        recursive=recursive,
    )
    return jsonify({"status": "ok", "doc_ids": doc_ids})


# ---------------------------------------------------------------------------
# AUTOCOMPLETE folder names
# ---------------------------------------------------------------------------


@doc_folders_bp.route("/doc_folders/autocomplete", methods=["GET"])
@limiter.limit("30 per minute")
@login_required
def autocomplete_folders_route():
    """Autocomplete folder names for #folder: syntax. ?prefix=Re."""
    users_dir, email = _get_user_context()
    if not email or not users_dir:
        return json_error("Not authenticated", 401)

    prefix = request.args.get("prefix", "").lower()
    folders = list_folders(users_dir=users_dir, user_email=email)
    matched = [
        {"name": f["name"], "folder_id": f["folder_id"]}
        for f in folders
        if not prefix or f["name"].lower().startswith(prefix)
    ]
    return jsonify({"status": "ok", "folders": matched})
