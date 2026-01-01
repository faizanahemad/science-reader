"""
Prompt management endpoints.

This module extracts the prompt CRUD routes from `server.py` into a Flask
Blueprint.
"""

from __future__ import annotations

import datetime
import logging

from flask import Blueprint, jsonify, request

from endpoints.auth import login_required
from endpoints.responses import json_error
from extensions import limiter


logger = logging.getLogger(__name__)
prompts_bp = Blueprint("prompts", __name__)


@prompts_bp.route("/get_prompts", methods=["GET"])
@limiter.limit("100 per minute")
@login_required
def get_prompts_route():
    """
    Get a list of all available prompt names with metadata.

    Returns
    -------
    flask.Response
        JSON response with prompt list and prompt metadata.
    """

    try:
        from prompts import manager

        prompt_names = manager.keys()

        prompts_with_metadata: list[dict] = []
        for name in prompt_names:
            try:
                prompt_metadata = manager.get_raw(name, as_dict=True)
                prompts_with_metadata.append(
                    {
                        "name": name,
                        "description": prompt_metadata.get("description", ""),
                        "category": prompt_metadata.get("category", ""),
                        "tags": prompt_metadata.get("tags", []),
                        "created_at": prompt_metadata.get("created_at", ""),
                        "updated_at": prompt_metadata.get(
                            "last_modified", datetime.datetime.now().isoformat()
                        ),
                        "version": prompt_metadata.get("version", ""),
                    }
                )
            except Exception:
                prompts_with_metadata.append(
                    {
                        "name": name,
                        "description": "",
                        "category": "",
                        "tags": [],
                        "created_at": "",
                        "updated_at": datetime.datetime.now().isoformat(),
                        "version": "",
                    }
                )

        return jsonify(
            {
                "status": "success",
                "prompts": prompt_names,  # backwards-compat
                "prompts_detailed": prompts_with_metadata,
                "count": len(prompt_names),
            }
        )
    except Exception as e:
        logger.error(f"Error getting prompts: {str(e)}")
        return json_error(str(e), status=500, code="internal_error")


@prompts_bp.route("/get_prompt_by_name/<prompt_name>", methods=["GET"])
@limiter.limit("100 per minute")
@login_required
def get_prompt_by_name_route(prompt_name: str):
    """
    Get the content and metadata of a specific prompt by name.
    """

    try:
        from prompts import manager

        if prompt_name not in manager:
            return json_error(f"Prompt '{prompt_name}' not found", status=404, code="prompt_not_found")

        prompt_content = manager[prompt_name]

        try:
            prompt_metadata = manager.get_raw(prompt_name, as_dict=True)
            return jsonify(
                {
                    "status": "success",
                    "name": prompt_name,
                    "content": prompt_content,
                    "raw_content": prompt_metadata.get("content", prompt_content),
                    "metadata": {
                        "description": prompt_metadata.get("description", ""),
                        "category": prompt_metadata.get("category", ""),
                        "tags": prompt_metadata.get("tags", []),
                        "version": prompt_metadata.get("version", ""),
                        "created_at": prompt_metadata.get("created_at", ""),
                        "updated_at": prompt_metadata.get("updated_at", ""),
                    },
                }
            )
        except Exception:
            return jsonify(
                {
                    "status": "success",
                    "name": prompt_name,
                    "content": prompt_content,
                    "raw_content": prompt_content,
                    "metadata": {},
                }
            )

    except Exception as e:
        logger.error(f"Error getting prompt '{prompt_name}': {str(e)}")
        return json_error(str(e), status=500, code="internal_error")


@prompts_bp.route("/create_prompt", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def create_prompt_route():
    """
    Create a new prompt.

    Expected JSON payload:
    {
        "name": "prompt_name",
        "content": "prompt content",
        "description": "optional description",
        "category": "optional category",
        "tags": ["optional", "tags"]
    }
    """

    try:
        from prompts import manager, prompt_cache

        data = request.json
        if not data:
            return json_error("No data provided", status=400, code="bad_request")

        prompt_name = data.get("name")
        if not prompt_name:
            return json_error("Prompt name is required", status=400, code="bad_request")

        if prompt_name in manager:
            return json_error(f"Prompt '{prompt_name}' already exists", status=409, code="conflict")

        content = data.get("content", "")
        manager[prompt_name] = content
        prompt_cache[prompt_name] = content

        if any(key in data for key in ["description", "category", "tags"]):
            try:
                edit_kwargs: dict = {}
                if "description" in data:
                    edit_kwargs["description"] = data["description"]
                if "category" in data:
                    edit_kwargs["category"] = data["category"]
                if "tags" in data:
                    edit_kwargs["tags"] = data["tags"]
                manager.edit(prompt_name, **edit_kwargs)
            except Exception as e:
                logger.warning(f"Could not update metadata for prompt '{prompt_name}': {str(e)}")

        return jsonify(
            {
                "status": "success",
                "message": f"Prompt '{prompt_name}' created successfully",
                "name": prompt_name,
                "content": content,
            }
        )

    except Exception as e:
        logger.error(f"Error creating prompt: {str(e)}")
        return json_error(str(e), status=500, code="internal_error")


@prompts_bp.route("/update_prompt", methods=["PUT"])
@limiter.limit("50 per minute")
@login_required
def update_prompt_route():
    """
    Update the content (and optionally metadata) of an existing prompt.
    """

    try:
        from prompts import manager, prompt_cache

        data = request.json
        if not data:
            return json_error("No data provided", status=400, code="bad_request")

        prompt_name = data.get("name")
        if not prompt_name:
            return json_error("Prompt name is required", status=400, code="bad_request")

        if prompt_name not in manager:
            return json_error(f"Prompt '{prompt_name}' not found", status=404, code="prompt_not_found")

        new_content = data.get("content")
        if new_content is None:
            return json_error("Content field is required for update", status=400, code="bad_request")

        manager[prompt_name] = new_content
        prompt_cache[prompt_name] = new_content

        if any(key in data for key in ["description", "category", "tags"]):
            try:
                edit_kwargs: dict = {}
                if "description" in data:
                    edit_kwargs["description"] = data["description"]
                if "category" in data:
                    edit_kwargs["category"] = data["category"]
                if "tags" in data:
                    edit_kwargs["tags"] = data["tags"]
                manager.edit(prompt_name, **edit_kwargs)
            except Exception as e:
                logger.warning(f"Could not update metadata for prompt '{prompt_name}': {str(e)}")

        return jsonify(
            {
                "status": "success",
                "message": f"Prompt '{prompt_name}' updated successfully",
                "name": prompt_name,
                "new_content": new_content,
            }
        )

    except Exception as e:
        logger.error(f"Error updating prompt: {str(e)}")
        return json_error(str(e), status=500, code="internal_error")


