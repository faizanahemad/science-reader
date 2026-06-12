"""
Auto-archival staleness scoring logic.

Pure functions that determine whether a conversation should be auto-archived.
No side effects — reads data, returns decisions.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Callable, Optional, Set, Tuple

from utils.text_similarity import (
    embedding_cosine_similarity,
    jaccard_similarity,
    tokenize,
)

logger = logging.getLogger(__name__)

BM25_THRESHOLD = 0.4
BM25_STANDALONE_THRESHOLD = 0.6  # BM25-only supersession (no embedding needed)
EMBEDDING_THRESHOLD = 0.75
OPEN_STALE_DAYS = 45


def is_exempt(conv_metadata: dict, pinned_conv_ids: Set[str]) -> bool:
    """Check if conversation is exempt from auto-archival.

    Exempt if: flagged, has pinned messages, or auto_archive_exempt is True.
    """
    if conv_metadata.get("flag"):
        return True
    if conv_metadata.get("auto_archive_exempt"):
        return True
    if conv_metadata.get("conversation_id") in pinned_conv_ids:
        return True
    return False


def message_count_modifier(msg_count: int) -> float:
    """Grace period multiplier based on message count."""
    if msg_count < 4:
        return 0.5
    elif msg_count > 40:
        return 2.0
    return 1.0


def find_superseding_conversation(
    target_conv_id: str,
    target_tokens: list,
    target_embedding,
    target_last_updated: datetime,
    all_conv_tokens: list,
    cache_map: dict,
    embed_fn: Optional[Callable] = None,
) -> bool:
    """Check if a newer conversation with similar title+summary exists.

    Args:
        target_conv_id: conversation_id of the target (for self-exclusion)
        target_tokens: BM25 tokens for the target conversation
        target_embedding: embedding bytes for the target (or None)
        target_last_updated: last_updated datetime of target
        all_conv_tokens: list of (conv_id, tokens, last_updated, embedding) for all other convs
        cache_map: similarity cache map {conv_id: cache_entry}
        embed_fn: optional function to compute embedding if missing

    Returns:
        True if a newer similar conversation supersedes the target.
    """
    if not target_tokens:
        return False

    for conv_id, tokens, last_updated, embedding in all_conv_tokens:
        # Self-exclusion
        if conv_id == target_conv_id:
            continue
        # Only consider newer conversations
        if last_updated <= target_last_updated:
            continue

        # BM25 pre-filter
        score = jaccard_similarity(target_tokens, tokens)
        if score < BM25_THRESHOLD:
            continue

        # Embedding confirmation (if available)
        if target_embedding is not None and embedding is not None:
            cosine = embedding_cosine_similarity(target_embedding, embedding)
            if cosine > EMBEDDING_THRESHOLD:
                return True
        elif score >= BM25_STANDALONE_THRESHOLD:
            # High BM25 score alone is sufficient when embeddings unavailable
            return True

    return False


def compute_staleness(
    conv_metadata: dict,
    msg_count: int,
    all_conv_tokens: list,
    cache_map: dict,
    pinned_conv_ids: Set[str],
    grace_days: int = 90,
    embed_fn: Optional[Callable] = None,
    now: Optional[datetime] = None,
) -> Tuple[bool, str]:
    """Compute whether a conversation is stale enough to auto-archive.

    Args:
        conv_metadata: dict from get_metadata()
        msg_count: len(conversation_history)
        all_conv_tokens: list of (conv_id, tokens, last_updated, embedding) for comparison
        cache_map: similarity cache map
        pinned_conv_ids: set of conv IDs that have pinned messages
        grace_days: base grace period in days
        embed_fn: optional embedding function
        now: current time (for testing)

    Returns:
        (is_stale, reason) tuple
    """
    if now is None:
        now = datetime.now()

    conv_id = conv_metadata.get("conversation_id", "")

    # Exemption check
    if is_exempt(conv_metadata, pinned_conv_ids):
        return False, "exempt"

    # Parse timestamps
    last_updated_str = conv_metadata.get("last_updated", "")
    last_opened_str = conv_metadata.get("last_opened_at")

    try:
        last_updated = datetime.strptime(last_updated_str, "%Y-%m-%d %H:%M:%S") if isinstance(last_updated_str, str) and last_updated_str else now
    except ValueError:
        last_updated = now

    # If last_opened_at is None (pre-existing conversation, never tracked),
    # fall back to last_updated as best estimate of last activity
    if last_opened_str is None:
        last_opened = last_updated
    else:
        try:
            last_opened = datetime.strptime(last_opened_str, "%Y-%m-%d %H:%M:%S") if isinstance(last_opened_str, str) else last_opened_str
        except (ValueError, TypeError):
            last_opened = now

    # Staleness clock = max of last_updated and last_opened_at
    staleness_clock = max(last_updated, last_opened)
    age_days = (now - staleness_clock).days

    # Message count modifier
    modifier = message_count_modifier(msg_count)
    adjusted_grace = grace_days * modifier

    # Superseded modifier
    cache_entry = cache_map.get(conv_id, {})
    target_tokens = cache_entry.get("bm25_tokens", [])
    target_embedding = cache_entry.get("embedding")

    is_superseded = find_superseding_conversation(
        conv_id, target_tokens, target_embedding, last_updated,
        all_conv_tokens, cache_map, embed_fn
    )
    if is_superseded:
        adjusted_grace *= 0.5

    # Final check
    if age_days <= adjusted_grace:
        return False, "within_grace"

    open_stale = (now - last_opened).days > min(OPEN_STALE_DAYS, adjusted_grace)
    update_stale = (now - last_updated).days > adjusted_grace

    if open_stale or update_stale:
        reason_parts = [f"age={age_days}d", f"grace={adjusted_grace:.0f}d"]
        if is_superseded:
            reason_parts.append("superseded")
        reason_parts.append(f"msgs={msg_count}")
        return True, ", ".join(reason_parts)

    return False, "recently_active"
