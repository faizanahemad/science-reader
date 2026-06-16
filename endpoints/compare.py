"""
Response Diffing endpoint — replay a turn with a different model/temperature.

Streams an alternative response for a given assistant message without persisting
it. The frontend uses this for side-by-side comparison.
"""

from __future__ import annotations

import json
import logging

from flask import Blueprint, Response, request, session, stream_with_context

from Conversation import Conversation
from database.conversations import checkConversationExists
from endpoints.auth import login_required
from endpoints.request_context import get_conversation_with_keys
from endpoints.responses import json_error
from endpoints.session_utils import get_session_identity
from endpoints.state import get_state
from endpoints.utils import keyParser
from extensions import limiter

compare_bp = Blueprint("compare", __name__)
logger = logging.getLogger(__name__)


@compare_bp.route("/rerun_message/<conversation_id>/<message_id>", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def rerun_message(conversation_id: str, message_id: str):
    """
    Replay the user turn preceding the given assistant message with different
    model/temperature. Streams the new response without persisting.

    Request JSON:
        model (str): target model name (e.g. "anthropic/claude-opus-latest")
        temperature (float, optional): 0.0–2.0, default 0.7
        system_prompt_override (str, optional): extra steering instruction
    """
    keys = keyParser(session)
    email, _name, _loggedin = get_session_identity()
    state = get_state()

    if not checkConversationExists(email, conversation_id, users_dir=state.users_dir):
        return json_error("Conversation not found", status=404, code="conversation_not_found")

    body = request.json or {}
    target_model = body.get("model")
    temperature = float(body.get("temperature", 0.7))
    system_override = body.get("system_prompt_override", "").strip()
    preamble_options = body.get("preamble_options", [])

    if not target_model:
        return json_error("model is required", status=400, code="missing_model")

    conversation: Conversation = get_conversation_with_keys(
        state, conversation_id=conversation_id, keys=keys
    )

    # Find the assistant message and the preceding user message
    messages = conversation.get_field("messages") or []
    target_index = None
    for i, msg in enumerate(messages):
        if msg.get("message_id") == message_id:
            target_index = i
            break

    if target_index is None:
        return json_error("Message not found", status=404, code="message_not_found")

    if messages[target_index].get("sender") != "model":
        return json_error("Can only rerun assistant messages", status=400, code="not_assistant_message")

    # Search backward for the nearest preceding user message
    user_msg = None
    for i in range(target_index - 1, -1, -1):
        if messages[i].get("sender") == "user":
            user_msg = messages[i]
            break

    if user_msg is None:
        return json_error("No preceding user message found", status=400, code="no_user_message")

    user_text = user_msg.get("text", "").strip()
    if not user_text:
        return json_error("Preceding user message is empty", status=400, code="empty_user_message")

    def generate_comparison():
        """Stream a re-run using call_llm directly — no persistence."""
        from code_common.call_llm import call_llm
        from common import get_first_last_parts

        try:
            yield json.dumps({"text": "", "status": "Starting comparison...", "type": "compare"}) + "\n"

            # Get preamble from conversation settings (same as normal reply)
            system_prompt = ""
            try:
                preamble_text, _ = conversation.get_preamble(
                    preamble_options or [], None, False
                )
                if preamble_text:
                    system_prompt = preamble_text
            except Exception:
                system_prompt = "You are a helpful assistant."

            if not system_prompt:
                system_prompt = "You are a helpful assistant."
            if system_override:
                system_prompt += f"\n\nAdditional instruction: {system_override}"

            # Build context: running_summary + messages up to (but not including) the target
            summary = getattr(conversation, 'running_summary', '') or ''
            if not summary:
                try:
                    memory = conversation.get_field("memory") or {}
                    rs = memory.get("running_summary", [])
                    summary = rs[-1] if rs else ''
                except Exception:
                    summary = ''
            context_messages = messages[:target_index - 1]  # everything before the user msg
            context_parts = []
            if summary:
                context_parts.append(f"Conversation summary so far:\n{summary}")
            # Include last few messages for immediate context (up to 6), each truncated to 4K tokens
            recent = context_messages[-6:]
            for m in recent:
                role = "User" if m.get("sender") == "user" else "Assistant"
                text = get_first_last_parts(m.get('text', ''), first_n=2000, last_n=2000)
                context_parts.append(f"{role}: {text}")

            context_text = "\n\n".join(context_parts)
            truncated_user_text = get_first_last_parts(user_text, first_n=2000, last_n=2000)
            full_prompt = f"{context_text}\n\nUser: {truncated_user_text}" if context_text else truncated_user_text

            accumulated = ""
            for chunk in call_llm(keys, target_model, full_prompt, temperature=temperature, stream=True, system=system_prompt):
                if chunk:
                    accumulated += chunk
                    yield json.dumps({"text": chunk, "type": "compare", "accumulated_text": accumulated}) + "\n"

            yield json.dumps({
                "text": "", "type": "compare", "completed": True,
                "accumulated_text": accumulated, "model": target_model,
            }) + "\n"

        except Exception as e:
            logger.error(f"[rerun_message] error | conv={conversation_id} | err={e}")
            yield json.dumps({"text": f"\n\n**Error:** {e}", "type": "compare", "error": True}) + "\n"

    return Response(stream_with_context(generate_comparison()), content_type="text/plain")


@compare_bp.route("/generate_comparison_diff", methods=["POST"])
@limiter.limit("20 per minute")
@login_required
def generate_comparison_diff():
    """
    Generate a semantic diff between two response texts using the same
    LLM-based comparison as the multi-model tab diff feature.

    Request JSON:
        original_text (str): the original assistant response
        new_text (str): the new response from a different model
        original_model (str): name of the original model
        new_model (str): name of the new model
    """
    keys = keyParser(session)
    body = request.json or {}
    original_text = body.get("original_text", "").strip()
    new_text = body.get("new_text", "").strip()
    original_model = body.get("original_model", "Original")
    new_model = body.get("new_model", "New")

    if not original_text or not new_text:
        return json_error("Both original_text and new_text are required", status=400, code="missing_text")

    from common import generate_model_diff
    diff_json = generate_model_diff(keys, original_model, original_text, new_model, new_text)

    return Response(diff_json, content_type="application/json")
