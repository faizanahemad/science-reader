"""
Similarity cache persistence helpers.

CRUD for the ConversationSimilarityCache table — stores BM25 tokens and
embeddings keyed by conversation_id + title_summary_hash.
"""

from __future__ import annotations

import json
import logging
from typing import Optional

from database.connection import create_connection

logger = logging.getLogger(__name__)

_default_users_dir: Optional[str] = None


def configure_users_dir(users_dir: str) -> None:
    global _default_users_dir
    _default_users_dir = users_dir


def _resolve_users_dir(users_dir: Optional[str]) -> str:
    if users_dir is not None:
        return users_dir
    if _default_users_dir is None:
        raise RuntimeError("users_dir not configured.")
    return _default_users_dir


def get_cached(conversation_id: str, users_dir: Optional[str] = None) -> Optional[dict]:
    """Get cached similarity data for a conversation."""
    conn = create_connection(_resolve_users_dir(users_dir))
    cur = conn.cursor()
    cur.execute(
        "SELECT title_summary_hash, bm25_tokens, embedding, updated_at FROM ConversationSimilarityCache WHERE conversation_id = ?",
        (conversation_id,),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        return None
    return {
        "conversation_id": conversation_id,
        "title_summary_hash": row[0],
        "bm25_tokens": json.loads(row[1]) if row[1] else None,
        "embedding": row[2],
        "updated_at": row[3],
    }


def get_all_cached(conversation_ids: list, users_dir: Optional[str] = None) -> dict:
    """Get cached similarity data for multiple conversations. Returns dict of id -> cache entry."""
    if not conversation_ids:
        return {}
    conn = create_connection(_resolve_users_dir(users_dir))
    cur = conn.cursor()
    placeholders = ",".join("?" * len(conversation_ids))
    cur.execute(
        f"SELECT conversation_id, title_summary_hash, bm25_tokens, embedding FROM ConversationSimilarityCache WHERE conversation_id IN ({placeholders})",
        conversation_ids,
    )
    rows = cur.fetchall()
    conn.close()
    result = {}
    for row in rows:
        result[row[0]] = {
            "conversation_id": row[0],
            "title_summary_hash": row[1],
            "bm25_tokens": json.loads(row[2]) if row[2] else None,
            "embedding": row[3],
        }
    return result


def upsert_cache(conversation_id: str, title_summary_hash: str, bm25_tokens: list = None, embedding: bytes = None, users_dir: Optional[str] = None) -> None:
    """Insert or update similarity cache entry."""
    conn = create_connection(_resolve_users_dir(users_dir))
    cur = conn.cursor()
    tokens_json = json.dumps(bm25_tokens) if bm25_tokens is not None else None
    cur.execute(
        """INSERT INTO ConversationSimilarityCache (conversation_id, title_summary_hash, bm25_tokens, embedding, updated_at)
           VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
           ON CONFLICT(conversation_id) DO UPDATE SET
             title_summary_hash = excluded.title_summary_hash,
             bm25_tokens = COALESCE(excluded.bm25_tokens, ConversationSimilarityCache.bm25_tokens),
             embedding = COALESCE(excluded.embedding, ConversationSimilarityCache.embedding),
             updated_at = CURRENT_TIMESTAMP""",
        (conversation_id, title_summary_hash, tokens_json, embedding),
    )
    conn.commit()
    conn.close()
