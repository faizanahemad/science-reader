"""
Extension page-context endpoints.

Provides ``/ext/ocr`` for screenshot-based OCR using vision-capable LLMs.
This endpoint was migrated from ``extension_server.py`` and enhanced with
better error handling, configurable models, and main-backend key management.

The OCR pipeline:
1. Extension captures viewport or scrolling screenshots (base64 PNG).
2. Extension sends array of screenshots to ``/ext/ocr``.
3. Each image is processed in parallel via a vision-capable LLM.
4. Combined text + per-page results are returned.

Two extraction modes are supported via the ``extract_comments`` flag:
- Clean mode (default): plain-text OCR, comment bubbles ignored.
- Comments mode: **two parallel LLM calls** per screenshot —
  Call A extracts clean document text (ignoring comments),
  Call B extracts only comments/annotations as a JSON array.
  Both fire simultaneously so latency equals the slower call, not their sum.

The pipelined approach (extension sends OCR requests per screenshot as they
are captured) means this endpoint is often called with 1 image at a time for
low latency, but it also supports batch mode (up to ``OCR_MAX_IMAGES``).
"""

from __future__ import annotations

import logging
import json
import logging
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from typing import Any, Dict, List, Optional

from flask import Blueprint, jsonify, request

from code_common.call_llm import call_llm
from endpoints.ext_auth import auth_required
from endpoints.request_context import get_state_and_keys
from endpoints.responses import json_error
from extensions import limiter

ext_page_bp = Blueprint("ext_page", __name__)
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration (env-overridable)
# ---------------------------------------------------------------------------

OCR_VISION_MODEL: str = os.getenv("EXT_OCR_MODEL", "google/gemini-2.5-flash")
"""Default vision model for OCR.  Must be a vision-capable model (gemini-2.5-flash-lite does NOT support image input)."""

OCR_MAX_IMAGES: int = int(os.getenv("EXT_OCR_MAX_IMAGES", "30"))
"""Maximum number of images per OCR request (scrolling screenshots can produce many frames)."""

OCR_MAX_WORKERS: int = int(os.getenv("EXT_OCR_MAX_WORKERS", "8"))
"""Maximum parallel LLM calls for batch OCR."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_ocr_messages_clean(image_data_url: str) -> List[Dict[str, Any]]:
    """
    Build LLM messages for clean text extraction (no comments).

    The model is instructed to return only the main document content,
    free of any comment or annotation noise.

    Parameters
    ----------
    image_data_url : str
        Base64 data URL for the screenshot (``data:image/png;base64,...``).

    Returns
    -------
    list[dict]
        Messages list suitable for ``call_llm(messages=...)``.  The response
        is plain text (not JSON).
    """
    system_prompt = (
        "You are an expert at OCR and document transcription. "
        "Extract all readable text from the image, preserve structure, "
        "and include headings, tables, lists, form labels, and section boundaries. "
        "Ignore any comment bubbles, annotation overlays, or margin notes \u2014 extract only the main document content. "
        "If something is unreadable, note it briefly."
    )
    user_prompt = (
        "Perform OCR on this screenshot. Return only the extracted text and its "
        "document structure (e.g., headings, sections, tables, lists, and form fields), "
        "keeping the original reading order as best as possible. "
        "Do not include comments or annotations."
    )
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]


def _build_ocr_messages_comments_only(image_data_url: str) -> List[Dict[str, Any]]:
    """
    Build LLM messages for extracting ONLY comments/annotations from a screenshot.

    This prompt is sharply focused: the model must ignore the main document body
    and return ONLY the review comments, sticky notes, margin annotations, or
    comment bubbles visible in the image.  The response is a JSON array.

    Used in parallel with ``_build_ocr_messages_clean`` when ``extract_comments=True``
    so both tasks are done simultaneously without burdening a single call.

    Parameters
    ----------
    image_data_url : str
        Base64 data URL for the screenshot (``data:image/png;base64,...``).

    Returns
    -------
    list[dict]
        Messages list for ``call_llm(messages=...)``.  Response must be parsed
        as a JSON array by the caller.
    """
    system_prompt = (
        "You are an expert at extracting review comments and annotations from document screenshots. "
        "Your ONLY job is to find and transcribe comment bubbles, sticky notes, margin notes, "
        "review annotations, tracked-changes notes, or any other reviewer feedback visible in the image. "
        "Do NOT transcribe the main document body text \u2014 only the comment/annotation content. "
        "Always respond with a JSON array (no markdown fences, no prose outside the JSON). "
        "If there are no comments or annotations visible, return an empty array: []."
    )
    user_prompt = (
        "Look at this document screenshot carefully. "
        "Find every comment bubble, sticky note, margin annotation, tracked-change note, "
        "or reviewer feedback element visible anywhere in the image \u2014 including sidebars, margins, "
        "and overlay panels. "
        "Return a JSON array where each element is an object with exactly two keys:\n"
        "  - \"anchor\": a short quote or phrase from the main document that this comment refers to "
        "(use empty string if unclear).\n"
        "  - \"body\": the full verbatim text of the comment or annotation.\n"
        "Example: [{\"anchor\": \"quarterly results\", \"body\": \"Please verify these numbers with finance.\"}]\n"
        "If no comments are visible, return: []"
    )
    return [
        {"role": "system", "content": system_prompt},
        {
            "role": "user",
            "content": [
                {"type": "text", "text": user_prompt},
                {"type": "image_url", "image_url": {"url": image_data_url}},
            ],
        },
    ]


def _parse_comments_json(raw: str, index: int) -> list:
    """
    Parse LLM response for the comments-only call into a list of comment dicts.

    Strips markdown fences, attempts JSON parse, and returns the list.
    Falls back to empty list with a warning on any parse error.

    Parameters
    ----------
    raw : str
        Raw string response from the comments LLM call.
    index : int
        Image index (for log messages).

    Returns
    -------
    list
        List of ``{anchor, body}`` dicts (may be empty).
    """
    if not raw or not raw.strip():
        logger.debug("OCR image %d: comments call returned empty string", index)
        return []
    stripped = raw.strip()
    # Strip markdown fences if the model wraps the array
    if stripped.startswith("```"):
        stripped = stripped.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    logger.debug("OCR image %d: raw comments response (first 500): %s", index, stripped[:500])
    try:
        parsed = json.loads(stripped)
        if not isinstance(parsed, list):
            # Model may have returned {comments: [...]} \u2014 try unwrapping
            if isinstance(parsed, dict):
                inner = parsed.get("comments") or parsed.get("annotations") or []
                if isinstance(inner, list):
                    logger.debug(
                        "OCR image %d: comments call returned wrapped dict, unwrapped %d items",
                        index, len(inner),
                    )
                    return inner
            logger.warning(
                "OCR image %d: comments call returned non-list JSON type=%s, discarding",
                index, type(parsed).__name__,
            )
            return []
        logger.info("OCR image %d: extracted %d comment(s)", index, len(parsed))
        return parsed
    except (json.JSONDecodeError, ValueError) as exc:
        logger.warning(
            "OCR image %d: comments call returned non-JSON (error: %s). Raw (first 300): %s",
            index, exc, stripped[:300],
        )
        return []


def _ocr_single_image(
    index: int,
    image_data_url: str,
    model: str,
    keys: dict,
    extract_comments: bool = False,
) -> Dict[str, Any]:
    """
    OCR a single image using a vision-capable LLM.

    When ``extract_comments=False`` (default), fires one clean-text LLM call.

    When ``extract_comments=True``, fires **two parallel LLM calls**:
    - Call A: clean document text (``_build_ocr_messages_clean``)
    - Call B: comments/annotations only (``_build_ocr_messages_comments_only``)
    Both calls run simultaneously via a 2-worker ThreadPoolExecutor so latency
    is bounded by the slower of the two rather than their sum.

    Parameters
    ----------
    index : int
        Image index in the batch (used for ordering results).
    image_data_url : str
        Base64 data URL for the screenshot.
    model : str
        Vision-capable model identifier (e.g. ``google/gemini-2.5-flash``).
    keys : dict
        API keys from ``get_state_and_keys()``.
    extract_comments : bool
        When True, fires two parallel calls and returns ``text`` + ``comments``.
        When False (default), fires one clean call and returns plain ``text``.

    Returns
    -------
    dict
        Clean mode:    ``{"index": int, "text": str}``
        Comments mode: ``{"index": int, "text": str, "comments": list}``
        On failure:    ``{"index": int, "text": "", "error": str}``
    """
    try:
        if extract_comments:
            logger.debug("OCR image %d: firing parallel clean+comments calls, model=%s", index, model)
            # Fire both LLM calls in parallel \u2014 2 workers, bounded by the slower call
            def _call_clean():
                msgs = _build_ocr_messages_clean(image_data_url)
                result = call_llm(keys=keys, model_name=model, messages=msgs, stream=False) or ""
                logger.debug("OCR image %d: clean call done, text length=%d", index, len(result))
                return result

            def _call_comments():
                msgs = _build_ocr_messages_comments_only(image_data_url)
                raw = call_llm(keys=keys, model_name=model, messages=msgs, stream=False) or ""
                logger.debug("OCR image %d: comments call raw response length=%d", index, len(raw))
                return raw

            with ThreadPoolExecutor(max_workers=2) as dual_exec:
                f_clean = dual_exec.submit(_call_clean)
                f_comments = dual_exec.submit(_call_comments)
                text = f_clean.result()
                comments_raw = f_comments.result()

            comments = _parse_comments_json(comments_raw, index)
            logger.info(
                "OCR image %d: parallel done \u2014 text=%d chars, comments=%d",
                index, len(text), len(comments),
            )
            return {"index": index, "text": text, "comments": comments}
        else:
            messages = _build_ocr_messages_clean(image_data_url)
            text = call_llm(keys=keys, model_name=model, messages=messages, stream=False)
            return {"index": index, "text": text or ""}
    except Exception as exc:
        logger.warning("OCR failed for image %d: %s", index, exc)
        return {"index": index, "text": "", "error": str(exc)}


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------


@ext_page_bp.route("/ext/ocr", methods=["POST"])
@limiter.limit("50 per minute")
@auth_required
def ocr_screenshots():
    """
    Perform OCR on an array of screenshots using a vision-capable LLM.

    The extension captures viewport or full-page scrolling screenshots as
    base64 PNG data URLs and sends them here for text extraction.  Results
    are returned both as combined text and as per-page objects for the
    extension's paginated content viewer.

    Request JSON
    -------------
    images : list[str]
        **Required.** Array of base64 data URLs (``data:image/png;base64,...``).
        Maximum ``OCR_MAX_IMAGES`` (default 30) images per request.
    url : str, optional
        Source page URL (for logging / metadata).
    title : str, optional
        Source page title (for logging / metadata).
    model : str, optional
        Override the default OCR vision model.
    extract_comments : bool, optional
        When ``true``, uses the comments-aware prompt.  Each page in the
        response will include a ``comments`` list alongside ``text``.
        Defaults to ``false``.

    Returns
    -------
    JSON
        ``{"text": "<combined>", "pages": [{"index": 0, "text": "...", "comments": [...]},...]}``
        on success (``comments`` key only present when ``extract_comments`` is true),
        or ``{"error": "..."}`` on failure.
    """
    try:
        data = request.get_json(silent=True) or {}
        images = data.get("images") or []
        model = data.get("model") or OCR_VISION_MODEL
        url = data.get("url", "")
        title = data.get("title", "")
        extract_comments: bool = bool(data.get("extract_comments", False))

        # --- Validation --------------------------------------------------
        if not isinstance(images, list) or not images:
            return json_error(
                "images[] is required and must be a non-empty list", status=400
            )

        if len(images) > OCR_MAX_IMAGES:
            return json_error(
                f"Too many images: {len(images)} exceeds maximum of {OCR_MAX_IMAGES}",
                status=400,
            )

        # Validate each image is a non-empty string (basic sanity check)
        for i, img in enumerate(images):
            if not isinstance(img, str) or not img.strip():
                return json_error(f"images[{i}] must be a non-empty string", status=400)

        logger.info(
            "OCR request: %d image(s), model=%s, extract_comments=%s, url=%s, title=%s",
            len(images),
            model,
            extract_comments,
            url[:80] if url else "",
            title[:60] if title else "",
        )

        # --- Get API keys from main backend key management ----------------
        _state, keys = get_state_and_keys()

        # --- Parallel OCR processing -------------------------------------
        pages: List[Dict[str, Any]] = []
        num_workers = min(OCR_MAX_WORKERS, len(images))

        with ThreadPoolExecutor(max_workers=num_workers) as executor:
            futures = {
                executor.submit(_ocr_single_image, idx, img, model, keys, extract_comments): idx
                for idx, img in enumerate(images)
            }
            for future in as_completed(futures):
                try:
                    pages.append(future.result())
                except Exception as exc:
                    idx = futures[future]
                    logger.error("OCR future failed for image %d: %s", idx, exc)
                    pages.append({"index": idx, "text": "", "error": str(exc)})

        # Sort by original index for consistent ordering
        pages.sort(key=lambda p: p["index"])

        # Combine text from all pages
        combined_text = "\n\n--- PAGE ---\n\n".join(
            p["text"] for p in pages if p.get("text")
        )

        # Count failures for logging
        failures = sum(1 for p in pages if "error" in p)
        if failures:
            logger.warning(
                "OCR completed with %d/%d failures for url=%s",
                failures,
                len(images),
                url[:80] if url else "unknown",
            )

        return jsonify({"text": combined_text, "pages": pages, "extract_comments": extract_comments})

    except Exception as exc:
        logger.exception("OCR endpoint error: %s", exc)
        return json_error(f"OCR processing failed: {exc}", status=500)
