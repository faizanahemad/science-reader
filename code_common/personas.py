"""Curated persona library and resolution helpers for per-model response tabs.

Motivation
----------
The multi-model response feature broadcasts an identical prompt and system
prompt to every selected model, so the tabs differ only by model idiosyncrasy.
Personas let each model row carry a distinct viewpoint/stance (appended to the
shared preamble as an extra system-prompt suffix), producing genuinely diverse
tab responses.

This module is the single source of truth for:
  - ``PERSONA_LIBRARY``       : the curated starter set (id -> {label, text}).
  - ``CUSTOM_PERSONA_MAX_CHARS``: cap for free-text custom personas.
  - ``persona_suffix(row)``   : the system-prompt suffix a row contributes.
  - ``persona_label(row)``    : the human-readable label for a row's tab.
  - ``build_systems_and_headers(rows, base_system)``: convenience to turn a list
    of persona rows into the ``systems`` + ``header_template`` lists consumed by
    ``CallMultipleLLM`` / ``stream_multiple_models``.

A "row" is a plain dict shaped like::

    {"model": "gpt-5.5", "persona": "skeptic", "custom_text": ""}

``persona`` is one of the ``PERSONA_LIBRARY`` ids, ``"none"``/``""``/``None``
(no persona), or ``"custom"`` (use ``custom_text``, capped defensively).
"""

from typing import Dict, List, Optional, Tuple

# Max length for a free-text "Custom…" persona. Enforced on the server (here)
# and mirrored on the UI via an input ``maxlength``. Keeps a custom persona from
# ballooning the already-large preamble.
CUSTOM_PERSONA_MAX_CHARS = 500

# Curated starter set. Texts are intentionally concise (2-4 sentences); they are
# appended AFTER the shared preamble, not used as a replacement.
PERSONA_LIBRARY: Dict[str, Dict[str, str]] = {
    "skeptic": {
        "label": "Skeptic",
        "text": (
            "Adopt a skeptical, red-team stance. Interrogate the assumptions in "
            "the question and in your own answer, surface where the reasoning "
            "could be wrong, and flag claims that need evidence. Prefer caveats "
            "and failure modes over confident conclusions."
        ),
    },
    "domain_expert": {
        "label": "Domain Expert",
        "text": (
            "Answer as a rigorous domain expert. Use precise terminology, cite "
            "the relevant principles or standards, and go a level deeper than a "
            "generalist would. Call out common misconceptions in the field."
        ),
    },
    "pragmatist": {
        "label": "Pragmatist",
        "text": (
            "Optimize for actionable, practical guidance. Give concrete steps, "
            "sensible defaults, and the shortest path that works. Note trade-offs "
            "briefly and avoid theoretical digressions."
        ),
    },
    "contrarian": {
        "label": "Contrarian",
        "text": (
            "Argue the strongest opposing case to the obvious answer. Challenge "
            "the consensus view, steelman the neglected alternative, and highlight "
            "what most people get wrong about this question."
        ),
    },
    "eli5": {
        "label": "ELI5",
        "text": (
            "Explain simply, as if to a curious beginner. Use plain language and "
            "everyday analogies, avoid jargon (or define it immediately), and keep "
            "each idea small and concrete."
        ),
    },
    "creative": {
        "label": "Creative",
        "text": (
            "Take a divergent, imaginative angle. Offer unexpected framings, "
            "analogies, or possibilities the straightforward answer would miss. "
            "Favor breadth of ideas over a single tidy conclusion."
        ),
    },
}


def _normalize_persona_id(persona: Optional[str]) -> str:
    """Return a canonical persona id, treating unknown/empty as ``"none"``."""
    if not persona:
        return "none"
    pid = str(persona).strip().lower()
    if pid in ("none", ""):
        return "none"
    if pid == "custom":
        return "custom"
    if pid in PERSONA_LIBRARY:
        return pid
    # Unknown id -> treat as no persona (defensive; never raise on user input).
    return "none"


def persona_suffix(row: Optional[dict]) -> str:
    """Resolve the system-prompt suffix contributed by a single persona row.

    Args:
        row: a dict with keys ``persona`` and optional ``custom_text``. May be
            ``None`` or empty for "no persona".

    Returns:
        The persona instruction text to append after the shared preamble, or an
        empty string when the row carries no persona. Custom text is truncated
        to ``CUSTOM_PERSONA_MAX_CHARS`` defensively.
    """
    if not row:
        return ""
    pid = _normalize_persona_id(row.get("persona"))
    if pid == "none":
        return ""
    if pid == "custom":
        text = (row.get("custom_text") or "").strip()
        return text[:CUSTOM_PERSONA_MAX_CHARS]
    return PERSONA_LIBRARY[pid]["text"]


def persona_label(row: Optional[dict]) -> str:
    """Human-readable label for a row's persona (for tab headers).

    Returns an empty string when the row has no persona. For custom personas the
    label is simply ``"Custom"`` (the free text itself is not shown in the tab
    header).
    """
    if not row:
        return ""
    pid = _normalize_persona_id(row.get("persona"))
    if pid == "none":
        return ""
    if pid == "custom":
        return "Custom" if (row.get("custom_text") or "").strip() else ""
    return PERSONA_LIBRARY[pid]["label"]


def compose_system(base_system: Optional[str], row: Optional[dict]) -> Optional[str]:
    """Append a row's persona suffix after the shared base system prompt.

    Returns ``base_system`` unchanged when the row has no persona. When there is
    a persona but no base system, returns just the persona suffix.
    """
    suffix = persona_suffix(row)
    if not suffix:
        return base_system
    if base_system:
        return f"{base_system}\n\n{suffix}"
    return suffix


def header_for_row(row: Optional[dict]) -> str:
    """Persona-aware header template for a single row.

    Produces e.g. ``"Response from {model} · Skeptic"`` when a persona is set,
    else the default ``"Response from {model}"``. The ``{model}`` placeholder is
    filled in by ``stream_multiple_models``.

    The ``"Response from "`` prefix is deliberate and load-bearing: the frontend
    (``interface/common.js`` ``applyModelResponseTabs``) classifies a response
    ``<details>`` as a model tab only when its ``<summary>`` starts with
    ``"Response from"``, then strips that prefix to derive the tab label. Keeping
    the prefix means a persona header flows through the existing tab machinery
    unchanged and the tab reads ``"{model} · Skeptic"``.
    """
    label = persona_label(row)
    if label:
        return f"Response from {{model}} · {label}"
    return "Response from {model}"


def build_systems_and_headers(
    rows: List[dict], base_system: Optional[str] = None
) -> Tuple[List[Optional[str]], List[str]]:
    """Turn persona rows into ``systems`` + ``header_template`` lists.

    Args:
        rows: list of persona row dicts (each with ``model``/``persona``/
            ``custom_text``).
        base_system: the shared preamble/system prompt applied to every model
            before its persona suffix.

    Returns:
        ``(systems, header_template)`` where both lists are the same length as
        ``rows`` and line up positionally with the model list built from the
        same rows. Suitable to pass straight into ``CallMultipleLLM`` /
        ``stream_multiple_models``.
    """
    systems = [compose_system(base_system, row) for row in rows]
    headers = [header_for_row(row) for row in rows]
    return systems, headers


def catalog() -> List[Dict[str, str]]:
    """Return the curated personas as ``[{id, label}]`` for the UI dropdown."""
    return [{"id": pid, "label": meta["label"]} for pid, meta in PERSONA_LIBRARY.items()]
