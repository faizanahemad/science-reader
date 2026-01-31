"""
Artefact-related endpoints.

Provides CRUD and LLM-assisted edit proposal/apply workflows for
conversation-scoped artefacts stored on disk.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import re
from difflib import unified_diff
from typing import Any, Dict, List, Tuple

from flask import Blueprint, jsonify, request, send_from_directory, session

from Conversation import Conversation
from call_llm import CallLLm
from common import EXPENSIVE_LLM
from database.conversations import checkConversationExists
from endpoints.auth import login_required
from endpoints.request_context import get_state_and_keys
from endpoints.responses import json_error
from endpoints.session_utils import get_session_identity
from extensions import limiter

artefacts_bp = Blueprint("artefacts", __name__)
logger = logging.getLogger(__name__)


def _get_conversation_or_404(
    conversation_id: str,
) -> Tuple[Conversation | None, Any | None, Any | None]:
    """
    Load a conversation with keys attached, returning an error response if missing.

    Returns
    -------
    tuple
        (conversation, keys, error_response)
    """
    state, keys = get_state_and_keys()
    email, _name, _logged_in = get_session_identity()
    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return (
            None,
            None,
            json_error(
                "Conversation not found", status=404, code="conversation_not_found"
            ),
        )
    conversation = state.conversation_cache[conversation_id]
    conversation.set_api_keys(keys)
    return conversation, keys, None


def _hash_content(content: str) -> str:
    """
    Return a stable hash for artefact content.

    Parameters
    ----------
    content : str
        File content to hash.

    Returns
    -------
    str
        Hex digest hash.
    """
    return hashlib.sha256((content or "").encode("utf-8")).hexdigest()


def _line_number_content(content: str) -> str:
    """
    Add 1-based line numbers to content for LLM context.

    Parameters
    ----------
    content : str
        File content.

    Returns
    -------
    str
        Line-numbered text.
    """
    if not content:
        return "(empty file)"
    lines = content.splitlines()
    return "\n".join(f"{i + 1}: {line}" for i, line in enumerate(lines))


def _read_lines(content: str, start: int, end: int) -> str:
    """
    Read a 1-indexed inclusive line range.

    Parameters
    ----------
    content : str
        File content.
    start : int
        Start line (1-indexed).
    end : int
        End line (1-indexed).

    Returns
    -------
    str
        Selected lines joined by newline.
    """
    lines = content.splitlines()
    if not lines:
        return ""
    start_idx = max(1, int(start)) - 1
    end_idx = max(start_idx, int(end) - 1)
    end_idx = min(end_idx, len(lines) - 1)
    return "\n".join(lines[start_idx : end_idx + 1])


def _grep(content: str, pattern: str) -> List[Dict[str, Any]]:
    """
    Grep a regex pattern over the content and return line matches.

    Parameters
    ----------
    content : str
        File content.
    pattern : str
        Regex pattern.

    Returns
    -------
    list
        List of {"line": int, "text": str} matches.
    """
    if not pattern:
        return []
    regex = re.compile(pattern)
    results = []
    for idx, line in enumerate(content.splitlines(), start=1):
        if regex.search(line):
            results.append({"line": idx, "text": line})
    return results


def _replace_range(content: str, start: int, end: int, text: str) -> str:
    """
    Replace a 1-indexed inclusive line range with the provided text.

    Parameters
    ----------
    content : str
        File content.
    start : int
        Start line (1-indexed).
    end : int
        End line (1-indexed).
    text : str
        Replacement text.

    Returns
    -------
    str
        Updated content.
    """
    lines = content.splitlines()
    start_idx = max(1, int(start)) - 1
    end_idx = max(start_idx, int(end) - 1)
    end_idx = min(end_idx, len(lines) - 1) if lines else -1
    new_lines = (text or "").splitlines()
    if start_idx > len(lines):
        lines.extend(new_lines)
    else:
        if end_idx < start_idx:
            end_idx = start_idx - 1
        lines[start_idx : end_idx + 1] = new_lines
    return "\n".join(lines)


def _insert_at(content: str, line: int, text: str) -> str:
    """
    Insert text before the given 1-indexed line.

    Parameters
    ----------
    content : str
        File content.
    line : int
        Line number to insert before (1-indexed).
    text : str
        Text to insert.

    Returns
    -------
    str
        Updated content.
    """
    lines = content.splitlines()
    insert_idx = max(1, int(line)) - 1
    insert_idx = min(insert_idx, len(lines))
    new_lines = (text or "").splitlines()
    lines[insert_idx:insert_idx] = new_lines
    return "\n".join(lines)


def _append_text(content: str, text: str) -> str:
    """
    Append text to the end of content.

    Parameters
    ----------
    content : str
        File content.
    text : str
        Text to append.

    Returns
    -------
    str
        Updated content.
    """
    if not content:
        return text or ""
    if not content.endswith("\n") and text:
        return content + "\n" + text
    return content + (text or "")


def _delete_range(content: str, start: int, end: int) -> str:
    """
    Delete a 1-indexed inclusive line range.

    Parameters
    ----------
    content : str
        File content.
    start : int
        Start line (1-indexed).
    end : int
        End line (1-indexed).

    Returns
    -------
    str
        Updated content.
    """
    lines = content.splitlines()
    if not lines:
        return ""
    start_idx = max(1, int(start)) - 1
    end_idx = max(start_idx, int(end) - 1)
    end_idx = min(end_idx, len(lines) - 1)
    if start_idx < len(lines):
        del lines[start_idx : end_idx + 1]
    return "\n".join(lines)


def _apply_ops(content: str, ops: List[Dict[str, Any]]) -> str:
    """
    Apply a list of edit operations to content.

    Parameters
    ----------
    content : str
        File content.
    ops : list
        List of operation dicts.

    Returns
    -------
    str
        Updated content.
    """
    updated = content
    for op in ops:
        op_type = op.get("op")
        if op_type == "replace_range":
            updated = _replace_range(
                updated, op.get("start_line"), op.get("end_line"), op.get("text", "")
            )
        elif op_type == "insert_at":
            updated = _insert_at(updated, op.get("start_line"), op.get("text", ""))
        elif op_type == "append":
            updated = _append_text(updated, op.get("text", ""))
        elif op_type == "delete_range":
            updated = _delete_range(updated, op.get("start_line"), op.get("end_line"))
        else:
            raise ValueError(f"Unsupported op: {op_type}")
    return updated


def _extract_json(text: str) -> Any:
    """
    Extract JSON object or list from model output.

    Parameters
    ----------
    text : str
        Raw model output.

    Returns
    -------
    Any
        Parsed JSON structure.
    """
    if not text:
        raise ValueError("Empty response from model")
    cleaned = text.strip()
    if cleaned.startswith("```"):
        cleaned = re.sub(r"^```[a-zA-Z]*", "", cleaned).rstrip("`").strip()
    first = min(
        [i for i in [cleaned.find("["), cleaned.find("{")] if i >= 0], default=-1
    )
    last = max(cleaned.rfind("]"), cleaned.rfind("}"))
    if first == -1 or last == -1:
        raise ValueError("No JSON object found in response")
    return json.loads(cleaned[first : last + 1])


def _parse_operations(payload: Any) -> List[Dict[str, Any]]:
    """
    Normalize model output into a list of operation dicts.

    Parameters
    ----------
    payload : Any
        Parsed JSON output.

    Returns
    -------
    list
        List of operations.
    """
    if isinstance(payload, dict) and "operations" in payload:
        ops = payload["operations"]
    elif isinstance(payload, list):
        ops = payload
    else:
        raise ValueError("Expected operations list or {operations: [...]}")
    if not isinstance(ops, list):
        raise ValueError("Operations must be a list")
    return ops


def _consume_llm_output(result: Any) -> str:
    """
    Convert LLM output (string or iterable) to string.

    Parameters
    ----------
    result : Any
        LLM return value.

    Returns
    -------
    str
        Full response text.
    """
    if isinstance(result, str):
        return result
    try:
        return "".join(chunk for chunk in result)
    except TypeError:
        return str(result)


def _format_recent_messages(messages: List[Dict[str, Any]], limit: int) -> str:
    """
    Format recent conversation messages for prompt context.

    Parameters
    ----------
    messages : list
        Conversation message list.
    limit : int
        Number of most recent messages to include.

    Returns
    -------
    str
        Formatted conversation excerpt.
    """
    if not messages:
        return ""
    limit = max(0, int(limit))
    recent = messages[-limit:] if limit > 0 else []
    lines = []
    for msg in recent:
        role = msg.get("sender") or msg.get("role") or "user"
        text = msg.get("text") or msg.get("content") or ""
        lines.append(f"{role}: {text}")
    return "\n".join(lines)


@artefacts_bp.route("/artefacts/<conversation_id>", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def list_artefacts_route(conversation_id: str):
    conversation, _keys, error = _get_conversation_or_404(conversation_id)
    if error:
        return error
    return jsonify(conversation.list_artefacts())


@artefacts_bp.route("/artefacts/<conversation_id>", methods=["POST"])
@limiter.limit("30 per minute")
@login_required
def create_artefact_route(conversation_id: str):
    conversation, _keys, error = _get_conversation_or_404(conversation_id)
    if error:
        return error
    payload = request.json if request.is_json and request.json else {}
    name = payload.get("name", "")
    file_type = payload.get("file_type", "txt")
    initial_content = payload.get("initial_content", "")
    try:
        artefact = conversation.create_artefact(
            name=name, file_type=file_type, initial_content=initial_content
        )
        return jsonify(artefact)
    except Exception as exc:
        logger.exception("Failed to create artefact")
        return json_error(str(exc), status=400, code="artefact_create_failed")


@artefacts_bp.route("/artefacts/<conversation_id>/<artefact_id>", methods=["GET"])
@limiter.limit("120 per minute")
@login_required
def get_artefact_route(conversation_id: str, artefact_id: str):
    conversation, _keys, error = _get_conversation_or_404(conversation_id)
    if error:
        return error
    try:
        return jsonify(conversation.get_artefact(artefact_id))
    except Exception as exc:
        logger.exception("Failed to fetch artefact")
        return json_error(str(exc), status=404, code="artefact_not_found")


@artefacts_bp.route("/artefacts/<conversation_id>/<artefact_id>", methods=["PUT"])
@limiter.limit("60 per minute")
@login_required
def update_artefact_route(conversation_id: str, artefact_id: str):
    conversation, _keys, error = _get_conversation_or_404(conversation_id)
    if error:
        return error
    payload = request.json if request.is_json and request.json else {}
    content = payload.get("content", "")
    try:
        updated = conversation.update_artefact_content(artefact_id, content)
        return jsonify(updated)
    except Exception as exc:
        logger.exception("Failed to update artefact")
        return json_error(str(exc), status=400, code="artefact_update_failed")


@artefacts_bp.route("/artefacts/<conversation_id>/<artefact_id>", methods=["DELETE"])
@limiter.limit("30 per minute")
@login_required
def delete_artefact_route(conversation_id: str, artefact_id: str):
    conversation, _keys, error = _get_conversation_or_404(conversation_id)
    if error:
        return error
    try:
        conversation.delete_artefact(artefact_id)
        return jsonify({"status": "deleted"})
    except Exception as exc:
        logger.exception("Failed to delete artefact")
        return json_error(str(exc), status=400, code="artefact_delete_failed")


@artefacts_bp.route(
    "/artefacts/<conversation_id>/<artefact_id>/download", methods=["GET"]
)
@limiter.limit("30 per minute")
@login_required
def download_artefact_route(conversation_id: str, artefact_id: str):
    conversation, _keys, error = _get_conversation_or_404(conversation_id)
    if error:
        return error
    try:
        artefact = conversation.get_artefact(artefact_id)
        file_name = artefact.get("file_name", "")
        if not file_name:
            return json_error(
                "Artefact missing file name", status=404, code="artefact_not_found"
            )
        return send_from_directory(
            conversation.artefacts_path, file_name, as_attachment=True
        )
    except Exception as exc:
        logger.exception("Failed to download artefact")
        return json_error(str(exc), status=404, code="artefact_not_found")


@artefacts_bp.route(
    "/artefacts/<conversation_id>/<artefact_id>/propose_edits", methods=["POST"]
)
@limiter.limit("30 per minute")
@login_required
def propose_artefact_edits_route(conversation_id: str, artefact_id: str):
    conversation, keys, error = _get_conversation_or_404(conversation_id)
    if error:
        return error
    payload = request.json if request.is_json and request.json else {}
    instruction = (payload.get("instruction") or "").strip()
    selection = payload.get("selection") or {}
    include_summary = bool(payload.get("include_summary"))
    include_messages = bool(payload.get("include_messages"))
    include_memory_pad = bool(payload.get("include_memory_pad"))
    history_count = int(payload.get("history_count", 10))

    if not instruction:
        return json_error(
            "Instruction is required", status=400, code="instruction_required"
        )

    try:
        artefact = conversation.get_artefact(artefact_id)
        content = artefact.get("content", "")
        base_hash = _hash_content(content)

        summary_text = conversation.running_summary if include_summary else ""
        message_text = (
            _format_recent_messages(
                conversation.get_message_list() or [], history_count
            )
            if include_messages
            else ""
        )
        memory_pad = (
            conversation.memory_pad
            if include_memory_pad and hasattr(conversation, "_memory_pad")
            else ""
        )

        selection_text = ""
        if (
            isinstance(selection, dict)
            and selection.get("start_line")
            and selection.get("end_line")
        ):
            selection_text = _read_lines(
                content, selection.get("start_line"), selection.get("end_line")
            )

        prompt = f"""You are editing a file. Produce ONLY JSON with edit operations.

Instruction:
{instruction}

File metadata:
- name: {artefact.get("name")}
- type: {artefact.get("file_type")}
- file_name: {artefact.get("file_name")}

Selection (if any):
{selection_text or "(none)"}

Conversation summary:
{summary_text or "(not included)"}

Recent messages:
{message_text or "(not included)"}

Memory pad:
{memory_pad or "(not included)"}

File content with line numbers:
{_line_number_content(content)}

Available tools (for reference only):
- read_lines(start_line, end_line)
- grep(pattern)
- replace_range(start_line, end_line, text)
- insert_at(start_line, text)
- append(text)
- delete_range(start_line, end_line)

Allowed operations schema:
[
  {{ "op": "replace_range", "start_line": 1, "end_line": 3, "text": "new text" }},
  {{ "op": "insert_at", "start_line": 2, "text": "inserted text" }},
  {{ "op": "append", "text": "text to append" }},
  {{ "op": "delete_range", "start_line": 4, "end_line": 6 }}
]
"""

        model_name = conversation.get_model_override(
            "artefact_propose_edits_model", EXPENSIVE_LLM[2]
        )
        llm = CallLLm(keys, model_name=model_name, use_gpt4=False, use_16k=False)
        response = llm(
            prompt,
            stream=False,
            temperature=0.2,
            max_tokens=2000,
            system="Return ONLY JSON.",
        )
        response_text = _consume_llm_output(response)
        parsed = _extract_json(response_text)
        ops = _parse_operations(parsed)

        new_content = _apply_ops(content, ops)
        diff_text = "\n".join(
            unified_diff(
                content.splitlines(),
                new_content.splitlines(),
                fromfile="before",
                tofile="after",
                lineterm="",
            )
        )
        return jsonify(
            {
                "proposed_ops": ops,
                "diff_text": diff_text,
                "base_hash": base_hash,
                "new_hash": _hash_content(new_content),
            }
        )
    except Exception as exc:
        logger.exception("Failed to propose artefact edits")
        return json_error(str(exc), status=400, code="artefact_propose_failed")


@artefacts_bp.route(
    "/artefacts/<conversation_id>/<artefact_id>/apply_edits", methods=["POST"]
)
@limiter.limit("30 per minute")
@login_required
def apply_artefact_edits_route(conversation_id: str, artefact_id: str):
    conversation, _keys, error = _get_conversation_or_404(conversation_id)
    if error:
        return error
    payload = request.json if request.is_json and request.json else {}
    base_hash = payload.get("base_hash")
    ops = payload.get("proposed_ops") or []
    try:
        artefact = conversation.get_artefact(artefact_id)
        current_content = artefact.get("content", "")
        current_hash = _hash_content(current_content)
        if base_hash and base_hash != current_hash:
            return json_error(
                "Artefact changed since proposal",
                status=409,
                code="artefact_stale_edit",
                data={"current_hash": current_hash},
            )

        new_content = _apply_ops(current_content, ops)
        updated = conversation.update_artefact_content(artefact_id, new_content)
        diff_text = "\n".join(
            unified_diff(
                current_content.splitlines(),
                new_content.splitlines(),
                fromfile="before",
                tofile="after",
                lineterm="",
            )
        )
        return jsonify(
            {
                "diff_text": diff_text,
                "updated_hash": _hash_content(new_content),
                "content": updated.get("content", ""),
                "metadata": {k: v for k, v in updated.items() if k != "content"},
            }
        )
    except Exception as exc:
        logger.exception("Failed to apply artefact edits")
        return json_error(str(exc), status=400, code="artefact_apply_failed")


@artefacts_bp.route("/artefacts/<conversation_id>/message_links", methods=["GET"])
@limiter.limit("60 per minute")
@login_required
def get_artefact_message_links_route(conversation_id: str):
    conversation, _keys, error = _get_conversation_or_404(conversation_id)
    if error:
        return error
    return jsonify(conversation.get_artefact_message_links())


@artefacts_bp.route("/artefacts/<conversation_id>/message_links", methods=["POST"])
@limiter.limit("60 per minute")
@login_required
def set_artefact_message_link_route(conversation_id: str):
    conversation, _keys, error = _get_conversation_or_404(conversation_id)
    if error:
        return error
    payload = request.json if request.is_json and request.json else {}
    message_id = payload.get("message_id")
    artefact_id = payload.get("artefact_id")
    message_index = payload.get("message_index")
    if not message_id or not artefact_id:
        return json_error(
            "message_id and artefact_id are required", status=400, code="link_required"
        )
    try:
        links = conversation.set_artefact_message_link(
            message_id=str(message_id),
            artefact_id=str(artefact_id),
            message_index=message_index,
        )
        return jsonify(links)
    except Exception as exc:
        logger.exception("Failed to set artefact message link")
        return json_error(str(exc), status=400, code="link_update_failed")


@artefacts_bp.route(
    "/artefacts/<conversation_id>/message_links/<message_id>", methods=["DELETE"]
)
@limiter.limit("60 per minute")
@login_required
def delete_artefact_message_link_route(conversation_id: str, message_id: str):
    conversation, _keys, error = _get_conversation_or_404(conversation_id)
    if error:
        return error
    try:
        links = conversation.delete_artefact_message_link(str(message_id))
        return jsonify(links)
    except Exception as exc:
        logger.exception("Failed to delete artefact message link")
        return json_error(str(exc), status=400, code="link_delete_failed")
