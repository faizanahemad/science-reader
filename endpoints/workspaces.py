"""
Workspace routes.

This Blueprint hosts endpoints for creating/listing/updating/deleting workspaces
and moving conversations between workspaces.

The underlying persistence operations live in `database.workspaces`.
"""

from __future__ import annotations

import secrets
import string

from flask import Blueprint, jsonify, request, session

from database.workspaces import (
    collapseWorkspaces,
    createWorkspace,
    deleteWorkspace,
    load_workspaces_for_user,
    moveConversationToWorkspace,
)
from endpoints.auth import login_required
from endpoints.responses import json_error
from endpoints.session_utils import get_session_identity
from endpoints.state import get_state
from extensions import limiter

alphabet = string.ascii_letters + string.digits

workspaces_bp = Blueprint("workspaces", __name__)

@workspaces_bp.route("/create_workspace/<domain>/<workspace_name>", methods=["POST"])
@limiter.limit("500 per minute")
@login_required
def create_workspace(domain: str, workspace_name: str):
    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    workspace_color = "primary"
    if request.is_json and request.json and "workspace_color" in request.json:
        workspace_color = request.json["workspace_color"]

    workspace_id = email + "_" + "".join(secrets.choice(alphabet) for _ in range(16))
    state = get_state()
    createWorkspace(
        users_dir=state.users_dir,
        user_email=email,
        workspace_id=workspace_id,
        domain=domain,
        workspace_name=workspace_name,
        workspace_color=workspace_color,
    )

    return jsonify(
        {
            "workspace_id": workspace_id,
            "workspace_name": workspace_name,
            "workspace_color": workspace_color,
        }
    )


@workspaces_bp.route("/list_workspaces/<domain>", methods=["GET"])
@limiter.limit("200 per minute")
@login_required
def list_workspaces(domain: str):
    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    state = get_state()
    all_workspaces = load_workspaces_for_user(users_dir=state.users_dir, user_email=email, domain=domain)
    return jsonify(all_workspaces)


@workspaces_bp.route("/update_workspace/<workspace_id>", methods=["PUT"])
@limiter.limit("500 per minute")
@login_required
def update_workspace(workspace_id: str):
    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    if not request.is_json or not request.json:
        return json_error("JSON body required", status=400, code="bad_request")

    workspace_name = request.json.get("workspace_name", None)
    workspace_color = request.json.get("workspace_color", None)
    expanded = request.json.get("expanded", None)
    if workspace_name is None and workspace_color is None and expanded is None:
        return json_error(
            "At least one of workspace_name or workspace_color or expanded must be provided.",
            status=400,
            code="bad_request",
        )

    from database.workspaces import updateWorkspace

    state = get_state()
    updateWorkspace(
        users_dir=state.users_dir,
        user_email=email,
        workspace_id=workspace_id,
        workspace_name=workspace_name,
        workspace_color=workspace_color,
        expanded=expanded,
    )
    return jsonify({"message": "Workspace updated successfully"})


@workspaces_bp.route("/collapse_workspaces", methods=["POST"])
@limiter.limit("500 per minute")
@login_required
def collapse_workspaces():
    _email, _name, _loggedin = get_session_identity()
    workspace_ids = request.json.get("workspace_ids", []) if request.is_json and request.json else []

    state = get_state()
    collapseWorkspaces(users_dir=state.users_dir, workspace_ids=workspace_ids)
    return jsonify({"message": "Workspaces collapsed successfully"})


@workspaces_bp.route("/delete_workspace/<domain>/<workspace_id>", methods=["DELETE"])
@limiter.limit("500 per minute")
@login_required
def delete_workspace(domain: str, workspace_id: str):
    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    try:
        state = get_state()
        deleteWorkspace(users_dir=state.users_dir, workspace_id=workspace_id, user_email=email, domain=domain)
        return jsonify({"message": "Workspace deleted and conversations moved to default workspace."}), 200
    except Exception:
        return json_error("Failed to delete workspace.", status=500, code="internal_error")


@workspaces_bp.route("/move_conversation_to_workspace/<conversation_id>", methods=["PUT"])
@limiter.limit("500 per minute")
@login_required
def move_conversation_to_workspace(conversation_id: str):
    email, _name, loggedin = get_session_identity()
    if not loggedin:
        return json_error("User not logged in", status=401, code="unauthorized")

    data = request.get_json()
    if not data or "workspace_id" not in data:
        return json_error("workspace_id is required in the request body.", status=400, code="bad_request")

    target_workspace_id = data["workspace_id"]

    try:
        state = get_state()
        moveConversationToWorkspace(
            users_dir=state.users_dir,
            user_email=email,
            conversation_id=conversation_id,
            workspace_id=target_workspace_id,
        )
        return jsonify({"message": f"Conversation {conversation_id} moved to workspace {target_workspace_id}."}), 200
    except Exception:
        return json_error("Failed to move conversation to workspace.", status=500, code="internal_error")


