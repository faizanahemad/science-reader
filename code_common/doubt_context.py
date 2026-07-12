"""
Path-local packing helpers for doubt-thread context.

These pure functions turn DoubtsClearing history rows into the prior-context
sections used by Conversation.clear_doubt. No DB or LLM calls live here so the
module is unit-testable without Flask / SQLite / model keys.
"""

from __future__ import annotations

from typing import Any, Iterable

# Packing thresholds (locked by doubt_thread_running_summary plan)
DOUBT_SUMMARY_MIN_TURNS = 2
DOUBT_RECENT_VERBATIM_TURNS = 3
DOUBT_SUMMARY_MAX_WORDS = 280
DOUBT_FULL_REPLAY_CHAR_BUDGET = 12000
DOUBT_OLDER_TURN_TRUNC_CHARS = 600
THREAD_SUMMARY_DOUBT_TEXT = "Thread Summary"


def is_system_thread_summary_node(doubt: dict[str, Any] | None) -> bool:
    """Return True for visible manual 'Thread Summary' children (not machine memory)."""
    if not doubt:
        return False
    return (doubt.get("doubt_text") or "").strip() == THREAD_SUMMARY_DOUBT_TEXT


def _filter_content_nodes(history: Iterable[dict[str, Any]] | None) -> list[dict[str, Any]]:
    """Drop system Thread Summary nodes from content packing."""
    if not history:
        return []
    return [d for d in history if not is_system_thread_summary_node(d)]


def select_path_summary(history: list[dict[str, Any]] | None) -> str | None:
    """
    Walk history reverse (tip → root); first ready non-empty thread_summary_upto_here.

    Only summary_status == 'ready' counts. Dirty/pending/error/NULL are ignored so
    packing never trusts a stale or in-flight summary.
    """
    if not history:
        return None
    for node in reversed(history):
        status = (node.get("summary_status") or "").strip().lower()
        text = (node.get("thread_summary_upto_here") or "").strip()
        if status == "ready" and text:
            return text
    return None


def should_generate_summary_for_path(history_len_incl_new: int) -> bool:
    """True when path length is long enough to warrant a stored running summary."""
    return history_len_incl_new >= DOUBT_SUMMARY_MIN_TURNS


def needs_sync_bootstrap(history: list[dict[str, Any]] | None) -> bool:
    """
    True when the path is long enough and no ready summary is available on tip/ancestors.

    Used by clear_doubt / regen to hang a one-shot SUPERFAST bootstrap before the
    answer LLM so legacy threads are not answered with empty thread memory.
    """
    if not history:
        return False
    if not should_generate_summary_for_path(len(history)):
        return False
    return select_path_summary(history) is None


def _format_turn_block(index: int, doubt: dict[str, Any], *, answer_limit: int | None = None) -> str:
    """Format a single history node as a Previous Doubt N block."""
    q = doubt.get("doubt_text") or ""
    a = doubt.get("doubt_answer") or ""
    if answer_limit is not None and answer_limit >= 0 and len(a) > answer_limit:
        a = a[:answer_limit].rstrip() + "…"
    return (
        f"**Previous Doubt {index}:**\n"
        f"User asked: {q}\n"
        f"Assistant answered: {a}\n\n"
    )


def format_recent_turns(
    history: list[dict[str, Any]] | None,
    k: int = DOUBT_RECENT_VERBATIM_TURNS,
) -> str:
    """
    Last k non-system nodes as Previous Doubt N blocks (1-indexed for the segment).

    Empty string when there are no content nodes.
    """
    nodes = _filter_content_nodes(history)
    if not nodes or k <= 0:
        return ""
    recent = nodes[-k:]
    # Index labels relative to the full content chain (not just recent slice).
    start_index = len(nodes) - len(recent) + 1
    parts: list[str] = []
    for offset, doubt in enumerate(recent):
        parts.append(_format_turn_block(start_index + offset, doubt))
    return "".join(parts)


def format_full_or_truncated_history(history: list[dict[str, Any]] | None) -> str:
    """
    Full dump of history for short threads / ensure-failure fallback.

    If total formatted length exceeds DOUBT_FULL_REPLAY_CHAR_BUDGET, keep the last
    DOUBT_RECENT_VERBATIM_TURNS turns full and truncate older answers.
    """
    nodes = _filter_content_nodes(history)
    if not nodes:
        return ""

    k = DOUBT_RECENT_VERBATIM_TURNS
    full_parts = [_format_turn_block(i + 1, d) for i, d in enumerate(nodes)]
    full_text = "".join(full_parts)
    if len(full_text) <= DOUBT_FULL_REPLAY_CHAR_BUDGET:
        return full_text

    if len(nodes) <= k:
        # Even the recent window is huge: truncate every answer.
        return "".join(
            _format_turn_block(i + 1, d, answer_limit=DOUBT_OLDER_TURN_TRUNC_CHARS)
            for i, d in enumerate(nodes)
        )

    older = nodes[:-k]
    recent = nodes[-k:]
    parts: list[str] = []
    for i, d in enumerate(older):
        parts.append(
            _format_turn_block(i + 1, d, answer_limit=DOUBT_OLDER_TURN_TRUNC_CHARS)
        )
    start_index = len(older) + 1
    for offset, d in enumerate(recent):
        parts.append(_format_turn_block(start_index + offset, d))
    return "".join(parts)


def pack_history_for_bootstrap(history: list[dict[str, Any]] | None) -> str:
    """
    Input for first summary on a path (incl. long pre-feature chains).

    Same truncation policy as the fallback packer so the bootstrap LLM sees a
    char-bounded view of the full chain rather than an unbounded dump.
    """
    return format_full_or_truncated_history(history)


def _trim_words(text: str, max_words: int = DOUBT_SUMMARY_MAX_WORDS) -> str:
    """Hard-cap word count while keeping prefix; helper for callers after LLM."""
    if not text:
        return ""
    words = text.split()
    if len(words) <= max_words:
        return text.strip()
    return " ".join(words[:max_words]).strip()


def build_doubt_history_context_section(
    history: list[dict[str, Any]] | None,
    current_doubt_text: str = "",
) -> str:
    """
    Main entry used by clear_doubt after optional ensure_path_summary_sync.

    - If a ready path summary exists: '# Doubt Thread Running Summary' + last K raw turns
      under '# Recent Doubt Turns'.
    - Else: '# Previous Doubt History' with full or truncated pack.

    Does not re-emit the current follow-up question (shown later as User's Doubt).
    current_doubt_text is accepted for API compatibility but ignored by design.
    """
    del current_doubt_text  # not emitted; current Q is in the User's Doubt section of the prompt
    content_nodes = _filter_content_nodes(history)
    if not content_nodes:
        return ""

    summary = select_path_summary(history)
    if summary:
        recent = format_recent_turns(history, k=DOUBT_RECENT_VERBATIM_TURNS)
        section = (
            "# Doubt Thread Running Summary\n\n"
            f"{summary.strip()}\n\n"
            "# Recent Doubt Turns\n\n"
            f"{recent}"
        )
        return section

    body = format_full_or_truncated_history(history)
    if not body:
        return ""
    return (
        "# Previous Doubt History\n\n"
        "This is a follow-up question. Here's the previous doubt conversation:\n\n"
        f"{body}"
    )


__all__ = [
    "DOUBT_SUMMARY_MIN_TURNS",
    "DOUBT_RECENT_VERBATIM_TURNS",
    "DOUBT_SUMMARY_MAX_WORDS",
    "DOUBT_FULL_REPLAY_CHAR_BUDGET",
    "DOUBT_OLDER_TURN_TRUNC_CHARS",
    "THREAD_SUMMARY_DOUBT_TEXT",
    "is_system_thread_summary_node",
    "select_path_summary",
    "should_generate_summary_for_path",
    "needs_sync_bootstrap",
    "format_recent_turns",
    "format_full_or_truncated_history",
    "pack_history_for_bootstrap",
    "build_doubt_history_context_section",
]
