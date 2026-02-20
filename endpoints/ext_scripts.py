"""
Extension custom-scripts endpoints.

Provides ``/ext/scripts/*`` routes for managing Tampermonkey-like user scripts
from the Chrome extension.  Ported from ``extension_server.py`` to run on the
main backend so the extension no longer needs a separate server.

Endpoints
---------
- GET    /ext/scripts              — list (with filters)
- POST   /ext/scripts              — create
- GET    /ext/scripts/for-url      — match URL
- POST   /ext/scripts/generate     — LLM generation
- POST   /ext/scripts/validate     — syntax check
- GET    /ext/scripts/<id>         — get one
- PUT    /ext/scripts/<id>         — update
- DELETE /ext/scripts/<id>         — delete
- POST   /ext/scripts/<id>/toggle  — toggle enabled
"""

from __future__ import annotations

import json
import logging
from typing import Any

from flask import Blueprint, jsonify, request, session

from database.ext_scripts import get_ext_scripts_db
from endpoints.ext_auth import auth_required
from endpoints.responses import json_error

ext_scripts_bp = Blueprint("ext_scripts", __name__)
logger = logging.getLogger(__name__)

# Model used for LLM-powered script generation.
SCRIPT_GEN_MODEL = "google/gemini-2.5-flash"

# ---------------------------------------------------------------------------
# LLM script-generation system prompt (identical to legacy extension_server.py)
# ---------------------------------------------------------------------------

_SCRIPT_GEN_SYSTEM_PROMPT = """You are an expert JavaScript developer specializing in browser userscripts (Tampermonkey-style).
Your task is to create custom scripts that augment web pages with useful functionality.

IMPORTANT RUNTIME CONSTRAINTS (follow strictly):
- The script runs in a sandboxed environment with **NO direct access to the page DOM**.
- Do NOT use `document`, `window.document`, `querySelector`, or any direct DOM access.
- Do NOT use `eval`, `new Function`, dynamic imports, or external libraries.
- To interact with the page, you MUST use the provided `aiAssistant.dom.*` functions (they execute in the content script).
- Keep scripts deterministic and safe: avoid infinite loops; keep operations small and targeted.

NOTE ABOUT `query/queryAll`:
- Do NOT rely on getting a live Element back from `aiAssistant.dom.query()` / `queryAll()`.
- Prefer `exists()`, `count()`, and action methods like `click()`, `setValue()`, `type()`, `hide()`, `remove()`, etc.

SCRIPT SHAPE REQUIREMENTS:
- Always create a handlers object: `const handlers = { ... }`
- Always export it: `window.__scriptHandlers = handlers;`
- Every action definition's `handler` field must match a function name in `handlers`.

The scripts you create will have access to an `aiAssistant` API with these methods:
- aiAssistant.dom.query(selector) - Returns first matching element
- aiAssistant.dom.queryAll(selector) - Returns array of matching elements
- aiAssistant.dom.exists(selector) - Returns true/false if element exists
- aiAssistant.dom.count(selector) - Returns number of matching elements
- aiAssistant.dom.getText(selector) - Gets text content
- aiAssistant.dom.getHtml(selector) - Gets innerHTML
- aiAssistant.dom.getAttr(selector, name) - Gets attribute value
- aiAssistant.dom.setAttr(selector, name, value) - Sets attribute value
- aiAssistant.dom.getValue(selector) - Gets value for inputs/textareas/selects
- aiAssistant.dom.waitFor(selector, timeout) - Waits for element to appear
- aiAssistant.dom.hide(selector) - Hides element(s)
- aiAssistant.dom.show(selector) - Shows element(s)
- aiAssistant.dom.setHtml(selector, html) - Sets innerHTML
- aiAssistant.dom.scrollIntoView(selector, behavior) - Scroll element into view
- aiAssistant.dom.focus(selector) - Focus element
- aiAssistant.dom.blur(selector) - Blur element
- aiAssistant.dom.click(selector) - Click element
- aiAssistant.dom.setValue(selector, value) - Set value + dispatch input/change
- aiAssistant.dom.type(selector, text, opts) - Type into element (opts: delayMs, clearFirst)
- aiAssistant.dom.remove(selector) - Remove matching elements (useful for ads)
- aiAssistant.dom.addClass(selector, className) - Add class to matching
- aiAssistant.dom.removeClass(selector, className) - Remove class from matching
- aiAssistant.dom.toggleClass(selector, className, force?) - Toggle class on matching
- aiAssistant.clipboard.copy(text) - Copies text to clipboard
- aiAssistant.clipboard.copyHtml(html) - Copies rich text
- aiAssistant.ui.showToast(message, type) - Shows notification ('success', 'error', 'info')
- aiAssistant.ui.showModal(title, content) - Shows modal dialog
- aiAssistant.ui.closeModal() - Closes modal
- aiAssistant.llm.ask(prompt) - Asks LLM a question, returns Promise<string>
- aiAssistant.storage.get(key) - Gets stored value
- aiAssistant.storage.set(key, value) - Stores value

Your script MUST:
1. Define handler functions as an object
2. Export handlers via: window.__scriptHandlers = handlers;
3. Each handler function should be a method that performs one action

Output your response as JSON with this structure:
{
  "name": "Script Name",
  "description": "What the script does",
  "match_patterns": ["*://example.com/*"],
  "script_type": "functional",
  "code": "const handlers = { actionName() { ... } }; window.__scriptHandlers = handlers;",
  "actions": [
    {
      "id": "action-id",
      "name": "Action Display Name",
      "description": "What this action does",
      "icon": "clipboard|copy|download|eye|trash|star|edit|settings|search|refresh",
      "exposure": "floating",
      "handler": "actionName"
    }
  ],
  "explanation": "Explanation of what the script does and how to use it"
}

Only output the JSON, no markdown code blocks."""


# ===================================================================
# Routes — order matters: literal paths before <script_id> catch-all
# ===================================================================


@ext_scripts_bp.route("/ext/scripts", methods=["GET"])
@auth_required
def list_scripts():
    """List user's custom scripts with optional filters."""
    try:
        email = session.get("email")
        enabled_only = request.args.get("enabled_only", "false").lower() == "true"
        script_type = request.args.get("script_type")
        limit = request.args.get("limit", 100, type=int)
        offset = request.args.get("offset", 0, type=int)

        db = get_ext_scripts_db()
        scripts = db.get_custom_scripts(
            email,
            enabled_only=enabled_only,
            script_type=script_type,
            limit=limit,
            offset=offset,
        )
        return jsonify({"scripts": scripts, "total": len(scripts)})
    except Exception:
        logger.exception("Error listing scripts")
        return json_error("Failed to list scripts", status=500)


@ext_scripts_bp.route("/ext/scripts", methods=["POST"])
@auth_required
def create_script():
    """Create a new custom script."""
    try:
        email = session.get("email")
        data = request.get_json() or {}

        name = (data.get("name") or "").strip()
        if not name:
            return json_error("Script name required", status=400)

        match_patterns = data.get("match_patterns", [])
        if not match_patterns or not isinstance(match_patterns, list):
            return json_error("At least one match pattern required", status=400)

        code = (data.get("code") or "").strip()
        if not code:
            return json_error("Script code required", status=400)

        db = get_ext_scripts_db()
        script = db.create_custom_script(
            user_email=email,
            name=name,
            match_patterns=match_patterns,
            code=code,
            description=data.get("description"),
            script_type=data.get("script_type", "functional"),
            match_type=data.get("match_type", "glob"),
            actions=data.get("actions"),
            conversation_id=data.get("conversation_id"),
            created_with_llm=data.get("created_with_llm", True),
        )
        return jsonify({"script": script})
    except Exception:
        logger.exception("Error creating script")
        return json_error("Failed to create script", status=500)


# --- Literal sub-paths (BEFORE <script_id>) ---


@ext_scripts_bp.route("/ext/scripts/for-url", methods=["GET"])
@auth_required
def get_scripts_for_url():
    """Get all enabled scripts matching a URL."""
    try:
        email = session.get("email")
        url = (request.args.get("url") or "").strip()
        if not url:
            return json_error("URL parameter required", status=400)

        db = get_ext_scripts_db()
        scripts = db.get_scripts_for_url(email, url)
        return jsonify({"scripts": scripts})
    except Exception:
        logger.exception("Error getting scripts for URL")
        return json_error("Failed to get scripts for URL", status=500)


@ext_scripts_bp.route("/ext/scripts/generate", methods=["POST"])
@auth_required
def generate_script():
    """Generate a script using an LLM based on description and page context."""
    try:
        from code_common.call_llm import call_llm
        from endpoints.utils import keyParser
    except ImportError:
        return json_error("LLM service not available", status=503)

    try:
        data = request.get_json() or {}
        description = (data.get("description") or "").strip()
        if not description:
            return json_error("Description required", status=400)

        page_url = data.get("page_url", "")
        page_html = data.get("page_html", "")
        refinement = data.get("refinement", "")

        # Truncate HTML if too long
        if len(page_html) > 50000:
            page_html = page_html[:50000] + "\n<!-- ... truncated ... -->"

        # Build user prompt
        user_prompt = f"Create a userscript based on this request:\n\n**Description:** {description}\n"
        if refinement:
            user_prompt += f"\n**Refinement/Additional requirements:** {refinement}\n"
        if page_url:
            user_prompt += f"\n**Target URL:** {page_url}\n"
        if page_html:
            user_prompt += (
                f"\n**Page HTML (for understanding structure):**\n"
                f"```html\n{page_html}\n```\n"
            )
        user_prompt += "\nGenerate the script JSON now:"

        keys = keyParser(session)
        response = call_llm(
            keys=keys,
            model_name=SCRIPT_GEN_MODEL,
            messages=[
                {"role": "system", "content": _SCRIPT_GEN_SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
            stream=False,
        )

        # Parse JSON response
        response_text = response.strip()
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            response_text = "\n".join(lines[1:-1] if lines[-1] == "```" else lines[1:])

        script_data = json.loads(response_text)
        explanation = script_data.pop("explanation", "Script generated successfully.")
        return jsonify({"script": script_data, "explanation": explanation})

    except json.JSONDecodeError as e:
        logger.warning("Failed to parse LLM response as JSON: %s", e)
        return json_error(
            "Failed to parse generated script",
            status=500,
        )
    except Exception:
        logger.exception("Error generating script")
        return json_error("Failed to generate script", status=500)


@ext_scripts_bp.route("/ext/scripts/validate", methods=["POST"])
@auth_required
def validate_script():
    """Basic bracket/paren/brace balance check on script code."""
    try:
        data = request.get_json() or {}
        code = data.get("code", "")
        if not code:
            return jsonify({"valid": False, "error": "No code provided"})

        # Balanced-bracket check (same algorithm as legacy extension_server.py)
        stack: list[str] = []
        pairs = {")": "(", "]": "[", "}": "{"}
        in_string = False
        string_char = None
        escaped = False

        for i, char in enumerate(code):
            if escaped:
                escaped = False
                continue
            if char == "\\":
                escaped = True
                continue
            if in_string:
                if char == string_char:
                    in_string = False
                    string_char = None
                continue
            if char in "\"'`":
                in_string = True
                string_char = char
                continue
            if char in "([{":
                stack.append(char)
            elif char in ")]}":
                if not stack or stack[-1] != pairs[char]:
                    return jsonify(
                        {"valid": False, "error": f"Unmatched {char} at position {i}"}
                    )
                stack.pop()

        if stack:
            return jsonify({"valid": False, "error": f"Unclosed {stack[-1]}"})
        if in_string:
            return jsonify({"valid": False, "error": "Unclosed string"})

        return jsonify({"valid": True})
    except Exception:
        logger.exception("Error validating script")
        return jsonify({"valid": False, "error": "Validation error"})


# --- Parameterised paths ---


@ext_scripts_bp.route("/ext/scripts/<script_id>", methods=["GET"])
@auth_required
def get_script(script_id: str):
    """Get a specific script by ID."""
    try:
        email = session.get("email")
        db = get_ext_scripts_db()
        script = db.get_custom_script(email, script_id)
        if not script:
            return json_error("Script not found", status=404)
        return jsonify({"script": script})
    except Exception:
        logger.exception("Error getting script %s", script_id)
        return json_error("Failed to get script", status=500)


@ext_scripts_bp.route("/ext/scripts/<script_id>", methods=["PUT"])
@auth_required
def update_script(script_id: str):
    """Update a custom script."""
    try:
        email = session.get("email")
        data = request.get_json() or {}
        db = get_ext_scripts_db()

        existing = db.get_custom_script(email, script_id)
        if not existing:
            return json_error("Script not found", status=404)

        success = db.update_custom_script(email, script_id, **data)
        if success:
            script = db.get_custom_script(email, script_id)
            return jsonify({"script": script})
        return json_error("Update failed", status=500)
    except Exception:
        logger.exception("Error updating script %s", script_id)
        return json_error("Failed to update script", status=500)


@ext_scripts_bp.route("/ext/scripts/<script_id>", methods=["DELETE"])
@auth_required
def delete_script(script_id: str):
    """Delete a custom script."""
    try:
        email = session.get("email")
        db = get_ext_scripts_db()
        success = db.delete_custom_script(email, script_id)
        if success:
            return jsonify({"message": "Deleted successfully"})
        return json_error("Script not found", status=404)
    except Exception:
        logger.exception("Error deleting script %s", script_id)
        return json_error("Failed to delete script", status=500)


@ext_scripts_bp.route("/ext/scripts/<script_id>/toggle", methods=["POST"])
@auth_required
def toggle_script(script_id: str):
    """Toggle a script's enabled status."""
    try:
        email = session.get("email")
        db = get_ext_scripts_db()

        script = db.get_custom_script(email, script_id)
        if not script:
            return json_error("Script not found", status=404)

        new_enabled = not script["enabled"]
        success = db.update_custom_script(email, script_id, enabled=new_enabled)
        if success:
            script = db.get_custom_script(email, script_id)
            return jsonify({"script": script, "enabled": new_enabled})
        return json_error("Toggle failed", status=500)
    except Exception:
        logger.exception("Error toggling script %s", script_id)
        return json_error("Failed to toggle script", status=500)
