"""
conversation_reference_utils.py

Utilities for generating human-readable cross-conversation reference identifiers.

Provides:
- generate_conversation_friendly_id(title, created_at) -> str
    Produces a short ID like "react_optimization_b4f2" from conversation title + creation time.
- generate_message_short_hash(conversation_friendly_id, message_text) -> str
    Produces a 6-char hash like "a3f2b1" for a specific message.
- _to_base36(num, length) -> str
    Helper to convert unsigned integer to fixed-length base36 string.

These are used for the cross-conversation message reference system that lets users
reference specific messages from other conversations using @conversation_<fid>_message_<hash>.

Why a separate module:
    Conversation.py is already 7600+ lines. This module is small, testable, and can be
    imported by both Conversation.py and endpoints/conversations.py without circular deps.
"""

import mmh3
import re
import string

_BASE36 = (
    string.ascii_lowercase + string.digits
)  # 'abcdefghijklmnopqrstuvwxyz0123456789'

# Regex for parsing cross-conversation message references.
# Matches: conversation_<conv_friendly_id>_message_<index_or_hash>
# Also:    conv_<conv_friendly_id>_msg_<index_or_hash>
# The .+ is greedy by default, so group(1) captures everything up to the LAST
# occurrence of _message_ or _msg_. This correctly handles conv_friendly_ids
# that contain underscores (e.g. "react_optimization_b4f2").
CONV_REF_PATTERN = re.compile(
    r"^(?:conversation|conv)_(.+)_(?:message|msg)_([a-z0-9]+)$"
)


def _to_base36(num: int, length: int) -> str:
    """
    Convert unsigned integer to fixed-length base36 string.

    Parameters
    ----------
    num : int
        Non-negative integer to convert.
    length : int
        Desired output length (zero-padded if needed).

    Returns
    -------
    str
        Fixed-length base36 string (lowercase a-z, 0-9).
    """
    result = []
    for _ in range(length):
        result.append(_BASE36[num % 36])
        num //= 36
    return "".join(reversed(result))


def generate_conversation_friendly_id(title: str, created_at: str) -> str:
    """
    Generate a short, human-readable conversation identifier.

    Format: {w1}_{w2}_{h4}
    - w1, w2: first 2 meaningful words from title (lowercase, stopwords removed)
    - h4: 4-char base36 hash of (title + created_at)

    Parameters
    ----------
    title : str
        The conversation title string.
    created_at : str
        Stable creation timestamp string (ISO format or any consistent format).

    Returns
    -------
    str
        Conversation friendly ID like "react_optimization_b4f2".

    Notes
    -----
    Uses the same stopword removal as truth_management_system/utils.py:_extract_meaningful_words().
    Falls back to a simple word extraction if the TMS import fails.
    """
    try:
        from truth_management_system.utils import _extract_meaningful_words

        words = _extract_meaningful_words(title, max_words=2)
    except (ImportError, Exception):
        # Fallback: simple word extraction if TMS is unavailable
        words = _simple_extract_words(title, max_words=2)

    if not words:
        words = ["chat"]
    base = "_".join(words)
    h = mmh3.hash(title + created_at, signed=False)
    suffix = _to_base36(h, 4)
    return f"{base}_{suffix}"


def generate_message_short_hash(
    conversation_friendly_id: str, message_text: str
) -> str:
    """
    Generate a 6-char base36 hash for a message.

    The hash is scoped to the conversation (different conversations produce
    different hashes for the same message text). This prevents cross-conversation
    hash collisions and makes references unambiguous.

    Parameters
    ----------
    conversation_friendly_id : str
        The conversation's friendly ID (e.g. "react_optimization_b4f2").
    message_text : str
        The full text of the message.

    Returns
    -------
    str
        6-char lowercase alphanumeric hash (e.g. "a3f2b1").
    """
    h = mmh3.hash(conversation_friendly_id + message_text, signed=False)
    return _to_base36(h, 6)


def _simple_extract_words(text: str, max_words: int = 2) -> list:
    """
    Simple fallback word extraction when TMS utils are unavailable.

    Removes non-alphanumeric chars, lowercases, filters stopwords and
    single-char words. Used only as a fallback.

    Parameters
    ----------
    text : str
        Input text to extract words from.
    max_words : int
        Maximum number of words to return.

    Returns
    -------
    list
        List of meaningful lowercase words, up to max_words.
    """
    _STOPWORDS = {
        "a",
        "an",
        "the",
        "and",
        "or",
        "but",
        "in",
        "on",
        "at",
        "to",
        "for",
        "of",
        "with",
        "by",
        "from",
        "is",
        "it",
        "as",
        "be",
        "was",
        "are",
        "been",
        "being",
        "have",
        "has",
        "had",
        "do",
        "does",
        "did",
        "will",
        "would",
        "could",
        "should",
        "may",
        "might",
        "can",
        "shall",
        "not",
        "no",
        "nor",
        "so",
        "if",
        "then",
        "than",
        "that",
        "this",
        "these",
        "those",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "when",
        "where",
        "why",
        "i",
        "me",
        "my",
        "we",
        "our",
        "you",
        "your",
        "he",
        "she",
        "his",
        "her",
        "they",
        "them",
        "their",
        "its",
        "about",
        "up",
    }
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", text).lower()
    tokens = cleaned.split()
    filtered = [w for w in tokens if w not in _STOPWORDS and len(w) > 1]
    if not filtered and tokens:
        filtered = tokens[:max_words]
    return filtered[:max_words]
