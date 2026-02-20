"""
Extension workflow endpoints.

Provides ``/ext/workflows/*`` routes for managing multi-step prompt workflows
from the Chrome extension.  Ported from ``extension_server.py``.

Endpoints
---------
- GET    /ext/workflows              — list
- POST   /ext/workflows              — create
- GET    /ext/workflows/<id>         — get one
- PUT    /ext/workflows/<id>         — update
- DELETE /ext/workflows/<id>         — delete
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from flask import Blueprint, jsonify, request, session

from database.ext_workflows import get_ext_workflows_db
from endpoints.ext_auth import auth_required
from endpoints.responses import json_error

ext_workflows_bp = Blueprint("ext_workflows", __name__)
logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Validation helper
# ---------------------------------------------------------------------------


def _validate_workflow_steps(steps: Any) -> Optional[str]:
    """
    Validate workflow steps payload.

    Parameters
    ----------
    steps : any
        Expected list of dicts with ``{title, prompt}``.

    Returns
    -------
    str or None
        Error message if invalid, None if valid.
    """
    if not isinstance(steps, list) or len(steps) == 0:
        return "Workflow steps must be a non-empty list."
    for idx, step in enumerate(steps):
        if not isinstance(step, dict):
            return f"Step {idx + 1} must be an object."
        title = (step.get("title") or "").strip()
        prompt = (step.get("prompt") or "").strip()
        if not title:
            return f"Step {idx + 1} title is required."
        if not prompt:
            return f"Step {idx + 1} prompt is required."
    return None


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@ext_workflows_bp.route("/ext/workflows", methods=["GET"])
@auth_required
def list_workflows():
    """List workflows for the authenticated user."""
    try:
        email = session.get("email")
        db = get_ext_workflows_db()
        workflows = db.list_workflows(email)
        return jsonify({"workflows": workflows})
    except Exception:
        logger.exception("Error listing workflows")
        return json_error("Failed to list workflows", status=500)


@ext_workflows_bp.route("/ext/workflows", methods=["POST"])
@auth_required
def create_workflow():
    """Create a new workflow."""
    try:
        email = session.get("email")
        data = request.get_json() or {}

        name = (data.get("name") or "").strip()
        if not name:
            return json_error("Workflow name is required", status=400)

        steps = data.get("steps")
        steps_error = _validate_workflow_steps(steps)
        if steps_error:
            return json_error(steps_error, status=400)

        db = get_ext_workflows_db()
        workflow = db.create_workflow(email, name, steps)
        return jsonify({"workflow": workflow})
    except Exception:
        logger.exception("Error creating workflow")
        return json_error("Failed to create workflow", status=500)


@ext_workflows_bp.route("/ext/workflows/<workflow_id>", methods=["GET"])
@auth_required
def get_workflow(workflow_id: str):
    """Get a workflow by ID."""
    try:
        email = session.get("email")
        db = get_ext_workflows_db()
        workflow = db.get_workflow(email, workflow_id)
        if not workflow:
            return json_error("Workflow not found", status=404)
        return jsonify({"workflow": workflow})
    except Exception:
        logger.exception("Error getting workflow %s", workflow_id)
        return json_error("Failed to get workflow", status=500)


@ext_workflows_bp.route("/ext/workflows/<workflow_id>", methods=["PUT"])
@auth_required
def update_workflow(workflow_id: str):
    """Update a workflow."""
    try:
        email = session.get("email")
        data = request.get_json() or {}

        name = (data.get("name") or "").strip()
        if not name:
            return json_error("Workflow name is required", status=400)

        steps = data.get("steps")
        steps_error = _validate_workflow_steps(steps)
        if steps_error:
            return json_error(steps_error, status=400)

        db = get_ext_workflows_db()
        success = db.update_workflow(email, workflow_id, name, steps)
        if not success:
            return json_error("Workflow not found", status=404)

        workflow = db.get_workflow(email, workflow_id)
        return jsonify({"workflow": workflow})
    except Exception:
        logger.exception("Error updating workflow %s", workflow_id)
        return json_error("Failed to update workflow", status=500)


@ext_workflows_bp.route("/ext/workflows/<workflow_id>", methods=["DELETE"])
@auth_required
def delete_workflow(workflow_id: str):
    """Delete a workflow."""
    try:
        email = session.get("email")
        db = get_ext_workflows_db()
        success = db.delete_workflow(email, workflow_id)
        if not success:
            return json_error("Workflow not found", status=404)
        return jsonify({"message": "Workflow deleted"})
    except Exception:
        logger.exception("Error deleting workflow %s", workflow_id)
        return json_error("Failed to delete workflow", status=500)
