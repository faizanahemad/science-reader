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

The pipelined approach (extension sends OCR requests per screenshot as they
are captured) means this endpoint is often called with 1 image at a time for
low latency, but it also supports batch mode (up to ``OCR_MAX_IMAGES``).
"""

from __future__ import annotations

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

OCR_VISION_MODEL: str = os.getenv("EXT_OCR_MODEL", "google/gemini-2.5-flash-lite")
"""Default vision model for OCR.  Lightweight and fast for text extraction."""

OCR_MAX_IMAGES: int = int(os.getenv("EXT_OCR_MAX_IMAGES", "30"))
"""Maximum number of images per OCR request (scrolling screenshots can produce many frames)."""

OCR_MAX_WORKERS: int = int(os.getenv("EXT_OCR_MAX_WORKERS", "8"))
"""Maximum parallel LLM calls for batch OCR."""


# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _build_ocr_messages(image_data_url: str) -> List[Dict[str, Any]]:
    """
    Build the LLM message list for a single OCR image.

    Uses a system prompt tuned for document transcription: preserving
    headings, tables, lists, form labels, and section boundaries.

    Parameters
    ----------
    image_data_url : str
        Base64 data URL for the screenshot (``data:image/png;base64,...``).

    Returns
    -------
    list[dict]
        Messages list suitable for ``call_llm(messages=...)``.
    """
    system_prompt = (
        "You are an expert at OCR and document transcription. "
        "Extract all readable text from the image, preserve structure, "
        "and include headings, tables, lists, form labels, and section boundaries. "
        "If something is unreadable, note it briefly."
    )
    user_prompt = (
        "Perform OCR on this screenshot. Return only the extracted text and its "
        "document structure (e.g., headings, sections, tables, lists, and form fields), "
        "keeping the original reading order as best as possible."
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


def _ocr_single_image(
    index: int,
    image_data_url: str,
    model: str,
    keys: dict,
) -> Dict[str, Any]:
    """
    OCR a single image using a vision-capable LLM.

    Parameters
    ----------
    index : int
        Image index in the batch (used for ordering results).
    image_data_url : str
        Base64 data URL for the screenshot.
    model : str
        Vision-capable model identifier (e.g. ``google/gemini-2.5-flash-lite``).
    keys : dict
        API keys from ``get_state_and_keys()``.

    Returns
    -------
    dict
        ``{"index": <int>, "text": <str>}`` with extracted text, or
        ``{"index": <int>, "text": "", "error": <str>}`` on failure.
    """
    try:
        messages = _build_ocr_messages(image_data_url)
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

    Returns
    -------
    JSON
        ``{"text": "<combined>", "pages": [{"index": 0, "text": "..."}, ...]}``
        on success, or ``{"error": "..."}`` on failure.
    """
    try:
        data = request.get_json(silent=True) or {}
        images = data.get("images") or []
        model = data.get("model") or OCR_VISION_MODEL
        url = data.get("url", "")
        title = data.get("title", "")

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
            "OCR request: %d image(s), model=%s, url=%s, title=%s",
            len(images),
            model,
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
                executor.submit(_ocr_single_image, idx, img, model, keys): idx
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

        return jsonify({"text": combined_text, "pages": pages})

    except Exception as exc:
        logger.exception("OCR endpoint error: %s", exc)
        return json_error(f"OCR processing failed: {exc}", status=500)
