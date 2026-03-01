"""
Image generation endpoint.

Uses OpenRouter's chat completions API with modalities=["image","text"]
to generate images via models like Nano Banana 2 (google/gemini-3.1-flash-image-preview).

Optionally runs an intermediate "better context" LLM call that takes the
raw user prompt + conversation context and produces a refined, image-
generation-optimised prompt before sending it to the image model.
"""

from __future__ import annotations

import base64
import logging
import os
import re
import time
from typing import Any, Dict, Optional

import requests as http_requests
from flask import Blueprint, request, session

from Conversation import Conversation
from call_llm import CallLLm
from common import CHEAP_LLM
from database.conversations import checkConversationExists
from endpoints.auth import login_required
from endpoints.llm_edit_utils import consume_llm_output, gather_conversation_context
from endpoints.request_context import get_state_and_keys
from endpoints.responses import json_error, json_ok
from endpoints.session_utils import get_session_identity
from extensions import limiter

logger = logging.getLogger(__name__)

image_gen_bp = Blueprint("image_gen", __name__)

# Default model for image generation via OpenRouter
DEFAULT_IMAGE_MODEL = "google/gemini-3.1-flash-image-preview"

# Models known to support image output via OpenRouter chat completions
# Naming: OpenRouter community names -> actual model IDs
SUPPORTED_IMAGE_MODELS = [
    "google/gemini-3.1-flash-image-preview",   # Nano Banana 2
    "google/gemini-2.5-flash-image",            # Nano Banana (original)
    "google/gemini-3-pro-image-preview",        # Nano Banana Pro
    "openai/gpt-5-image-mini",
    "openai/gpt-5-image",
]

# ---------------------------------------------------------------------------
# Better-context prompt refinement
# ---------------------------------------------------------------------------

BETTER_CONTEXT_SYSTEM = (
    "You are an expert image-prompt engineer. The user wants to generate an "
    "image using an AI image generator. You are given:\n"
    "1. The user's raw image prompt.\n"
    "2. Optional conversation context (summary, recent messages, memory pad, "
    "extracted context) from an ongoing conversation.\n\n"
    "Your job is to produce a SINGLE refined image-generation prompt that:\n"
    "- Incorporates relevant details from the conversation context into the "
    "image description (characters, settings, themes, facts mentioned).\n"
    "- Is concrete and visual — describe what should be SEEN in the image.\n"
    "- Specifies style, mood, lighting, composition if the user's prompt is "
    "vague.\n"
    "- Removes any conversational noise that would confuse an image model.\n"
    "- Is between 1-4 sentences. Do NOT write paragraphs.\n\n"
    "Return ONLY the refined prompt text. No explanations, no preamble, no "
    "quotes around it."
)


def _build_image_prompt(
    prompt: str,
    context_parts: Optional[Dict[str, str]] = None,
) -> str:
    """Build the image generation prompt with optional conversation context."""
    parts = []

    if context_parts:
        if context_parts.get("summary"):
            parts.append(f"## Conversation Summary\n{context_parts['summary']}")
        if context_parts.get("recent_messages"):
            parts.append(f"## Recent Messages\n{context_parts['recent_messages']}")
        if context_parts.get("memory_pad"):
            parts.append(f"## Memory Pad\n{context_parts['memory_pad']}")
        if context_parts.get("extracted_context"):
            parts.append(f"## Extracted Context\n{context_parts['extracted_context']}")

    if parts:
        parts.append(f"## Image Generation Request\n{prompt}")
        return "\n\n".join(parts)
    return prompt


def _refine_prompt_with_llm(
    raw_prompt: str,
    context_parts: Optional[Dict[str, str]],
    keys: dict,
) -> str:
    """Use a cheap LLM to massage the raw prompt + context into an optimised
    image-generation prompt.

    Falls back to the raw concatenated prompt on any failure.
    """
    # Build the user message that includes both context and the raw prompt
    user_msg_parts = []
    if context_parts:
        if context_parts.get("summary"):
            user_msg_parts.append(f"## Conversation Summary\n{context_parts['summary']}")
        if context_parts.get("recent_messages"):
            user_msg_parts.append(f"## Recent Messages\n{context_parts['recent_messages']}")
        if context_parts.get("memory_pad"):
            user_msg_parts.append(f"## Memory Pad\n{context_parts['memory_pad']}")
        if context_parts.get("extracted_context"):
            user_msg_parts.append(f"## Extracted Context\n{context_parts['extracted_context']}")

    user_msg_parts.append(f"## User's Image Prompt\n{raw_prompt}")
    user_msg = "\n\n".join(user_msg_parts)

    try:
        model_name = CHEAP_LLM[0]
        logger.info("Better-context: refining prompt with %s", model_name)
        llm = CallLLm(keys, model_name=model_name, use_gpt4=False, use_16k=False)
        response = llm(
            user_msg,
            stream=False,
            temperature=0.4,
            max_tokens=500,
            system=BETTER_CONTEXT_SYSTEM,
        )
        refined = consume_llm_output(response).strip()
        if refined:
            logger.info("Better-context: refined prompt len=%d", len(refined))
            return refined
        logger.warning("Better-context: LLM returned empty, falling back")
    except Exception:
        logger.warning("Better-context: LLM call failed, falling back", exc_info=True)

    # Fallback: plain concatenation
    return _build_image_prompt(raw_prompt, context_parts)


# ---------------------------------------------------------------------------
# Reusable image generation function (called by Conversation.py /image cmd)
# ---------------------------------------------------------------------------

def generate_image_from_prompt(
    prompt: str,
    keys: dict,
    model: str = DEFAULT_IMAGE_MODEL,
    referer: str = "https://localhost",
) -> Dict[str, Any]:
    """Generate an image via OpenRouter. Returns dict with 'images', 'text', 'error'.

    This function is intended to be called from Conversation.reply() for the
    /image command, as well as from the modal endpoint.

    Parameters
    ----------
    prompt : str
        The (optionally pre-refined) image generation prompt.
    keys : dict
        API keys dict (must contain OPENROUTER_API_KEY).
    model : str
        OpenRouter model ID.
    referer : str
        HTTP-Referer header value.

    Returns
    -------
    dict
        ``{"images": [data_uri, ...], "text": str, "error": str|None}``
    """
    api_key = keys.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return {"images": [], "text": "", "error": "OpenRouter API key not configured."}

    try:
        logger.info("generate_image_from_prompt: model=%s prompt_len=%d", model, len(prompt))
        resp = http_requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": referer,
                "X-Title": "ScienceReader",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": prompt}],
                "modalities": ["image", "text"],
                "max_tokens": 4096,
            },
            timeout=120,
        )

        if resp.status_code != 200:
            error_detail = ""
            try:
                error_detail = resp.json().get("error", {}).get("message", resp.text[:500])
            except Exception:
                error_detail = resp.text[:500]
            logger.error("generate_image_from_prompt: OpenRouter %d: %s", resp.status_code, error_detail)
            return {"images": [], "text": "", "error": f"OpenRouter error ({resp.status_code}): {error_detail}"}

        result = resp.json()
        choices = result.get("choices", [])
        if not choices:
            return {"images": [], "text": "", "error": "No response from image model."}

        message = choices[0].get("message", {})
        content = message.get("content", "")
        images = []

        if "images" in message:
            for img_obj in message["images"]:
                url = img_obj.get("image_url", {}).get("url", "")
                if url:
                    images.append(url)

        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url:
                            images.append(url)
                    elif part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                elif isinstance(part, str):
                    text_parts.append(part)
            content = "\n".join(text_parts)

        if isinstance(content, str) and not images:
            data_uri_pattern = r'(data:image/[^;]+;base64,[A-Za-z0-9+/=]+)'
            found = re.findall(data_uri_pattern, content)
            if found:
                images.extend(found)

        return {
            "images": images,
            "text": content if isinstance(content, str) else "",
            "error": None,
        }

    except http_requests.Timeout:
        return {"images": [], "text": "", "error": "Image generation timed out (120s)."}
    except Exception as e:
        logger.error("generate_image_from_prompt failed", exc_info=True)
        return {"images": [], "text": "", "error": f"Image generation failed: {str(e)}"}


# ---------------------------------------------------------------------------
# Main endpoint
# ---------------------------------------------------------------------------

@image_gen_bp.route("/api/generate-image", methods=["POST"])
@limiter.limit("10 per minute")
@login_required
def generate_image():
    """Generate an image using OpenRouter's image-capable models.

    Expects JSON body:
        prompt: str              - the image description
        model: str (optional)    - OpenRouter model ID (default: Nano Banana 2)
        conversation_id: str     - (optional) for gathering context
        include_summary: bool    - include conversation summary
        include_messages: bool   - include recent messages
        include_memory_pad: bool - include memory pad
        history_count: int       - number of recent messages (default 10)
        deep_context: bool       - expensive LLM-based context extraction
        better_context: bool     - intermediate LLM call to refine the prompt
    """
    data = request.get_json(silent=True) or {}

    prompt = (data.get("prompt") or "").strip()
    if not prompt:
        return json_error("Prompt is required.", status=400, code="missing_prompt")

    model = (data.get("model") or "").strip() or DEFAULT_IMAGE_MODEL
    conversation_id = (data.get("conversation_id") or "").strip()
    include_summary = bool(data.get("include_summary"))
    include_messages = bool(data.get("include_messages"))
    include_memory_pad = bool(data.get("include_memory_pad"))
    history_count = int(data.get("history_count", 10))
    deep_context = bool(data.get("deep_context"))
    better_context = bool(data.get("better_context"))

    # Gather conversation context if requested
    context_parts = None
    keys = None
    any_context = include_summary or include_messages or include_memory_pad or deep_context
    if conversation_id and any_context:
        try:
            state_obj, keys = get_state_and_keys()
            email, _name, _logged_in = get_session_identity()
            if checkConversationExists(email, conversation_id, users_dir=state_obj.users_dir):
                conversation = state_obj.conversation_cache[conversation_id]
                conversation.set_api_keys(keys)
                context_parts = gather_conversation_context(
                    conversation,
                    prompt,
                    include_context=True,
                    deep_context=deep_context,
                    include_summary=include_summary,
                    include_messages=include_messages,
                    include_memory_pad=include_memory_pad,
                    history_count=history_count,
                )
        except Exception:
            logger.warning("Failed to gather conversation context for image gen", exc_info=True)

    # Build the full prompt — either via LLM refinement or plain concatenation
    if keys is None:
        try:
            _state_obj, keys = get_state_and_keys()
        except Exception:
            return json_error("Failed to get API keys.", status=500, code="key_error")

    if better_context and (context_parts or any_context):
        full_prompt = _refine_prompt_with_llm(prompt, context_parts, keys)
    else:
        full_prompt = _build_image_prompt(prompt, context_parts)

    # Get API key
    api_key = keys.get("OPENROUTER_API_KEY", "")
    if not api_key:
        return json_error(
            "OpenRouter API key is not configured.",
            status=500,
            code="missing_api_key",
        )

    # Call OpenRouter chat completions with image modality
    try:
        logger.info("Image gen: calling OpenRouter model=%s prompt_len=%d", model, len(full_prompt))
        resp = http_requests.post(
            "https://openrouter.ai/api/v1/chat/completions",
            headers={
                "Authorization": f"Bearer {api_key}",
                "Content-Type": "application/json",
                "HTTP-Referer": request.host_url or "https://localhost",
                "X-Title": "ScienceReader",
            },
            json={
                "model": model,
                "messages": [{"role": "user", "content": full_prompt}],
                "modalities": ["image", "text"],
                "max_tokens": 4096,
            },
            timeout=120,
        )

        if resp.status_code != 200:
            error_detail = ""
            try:
                error_detail = resp.json().get("error", {}).get("message", resp.text[:500])
            except Exception:
                error_detail = resp.text[:500]
            logger.error("Image gen: OpenRouter returned %d: %s", resp.status_code, error_detail)
            return json_error(
                f"OpenRouter API error ({resp.status_code}): {error_detail}",
                status=502,
                code="openrouter_error",
            )

        result = resp.json()
        choices = result.get("choices", [])
        if not choices:
            return json_error(
                "No response from image model.",
                status=502,
                code="empty_response",
            )

        message = choices[0].get("message", {})
        content = message.get("content", "")

        # Extract images from the response
        images = []

        # Check for images array (OpenRouter multimodal response format)
        if "images" in message:
            for img_obj in message["images"]:
                url = img_obj.get("image_url", {}).get("url", "")
                if url:
                    images.append(url)

        # Also check content parts if content is a list (multipart response)
        if isinstance(content, list):
            text_parts = []
            for part in content:
                if isinstance(part, dict):
                    if part.get("type") == "image_url":
                        url = part.get("image_url", {}).get("url", "")
                        if url:
                            images.append(url)
                    elif part.get("type") == "text":
                        text_parts.append(part.get("text", ""))
                elif isinstance(part, str):
                    text_parts.append(part)
            content = "\n".join(text_parts)

        # Check for inline base64 in text content (some models embed data URIs)
        if isinstance(content, str) and not images:
            data_uri_pattern = r'(data:image/[^;]+;base64,[A-Za-z0-9+/=]+)'
            found = re.findall(data_uri_pattern, content)
            if found:
                images.extend(found)

        if not images:
            return json_ok({
                "images": [],
                "text": content if isinstance(content, str) else str(content),
                "warning": "Model did not return any images. Try a different prompt or model.",
                "model": model,
                "refined_prompt": full_prompt if better_context else None,
            })

        return json_ok({
            "images": images,
            "text": content if isinstance(content, str) else "",
            "model": model,
            "refined_prompt": full_prompt if better_context else None,
        })

    except http_requests.Timeout:
        return json_error(
            "Image generation timed out (120s). Try a simpler prompt.",
            status=504,
            code="timeout",
        )
    except Exception as e:
        logger.error("Image generation failed", exc_info=True)
        return json_error(
            f"Image generation failed: {str(e)}",
            status=500,
            code="internal_error",
        )


# ---------------------------------------------------------------------------
# Serve stored conversation images
# ---------------------------------------------------------------------------

@image_gen_bp.route("/api/conversation-image/<conversation_id>/<image_filename>", methods=["GET"])
@login_required
def serve_conversation_image(conversation_id: str, image_filename: str):
    """Serve a generated image stored in a conversation's images/ directory."""
    from flask import send_from_directory

    state_obj, _keys = get_state_and_keys()
    email, _name, _logged_in = get_session_identity()

    if not checkConversationExists(email, conversation_id, users_dir=state_obj.users_dir):
        return json_error("Conversation not found.", status=404)

    # Sanitise filename (only allow alphanumeric, hyphens, underscores, dots)
    import re as _re
    if not _re.match(r'^[a-zA-Z0-9_-]+\.(png|jpg|jpeg|webp)$', image_filename):
        return json_error("Invalid filename.", status=400)

    conversation = state_obj.conversation_cache[conversation_id]
    images_dir = os.path.join(conversation._storage, "images")

    if not os.path.isfile(os.path.join(images_dir, image_filename)):
        return json_error("Image not found.", status=404)

    return send_from_directory(images_dir, image_filename, mimetype="image/png")

