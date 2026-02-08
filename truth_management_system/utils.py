"""
Utility functions for PKB v0.

Provides:
- UUID generation for primary keys
- ISO 8601 timestamp helpers
- JSON validation and manipulation
- ParallelExecutor for concurrent LLM/embedding calls

The ParallelExecutor wraps ThreadPoolExecutor and is compatible
with patterns used in code_common/call_llm.py.
"""

import re
import uuid
import json
import string
import random
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from typing import Dict, Optional, List, Callable, TypeVar, Any

T = TypeVar("T")

logger = logging.getLogger(__name__)


# =============================================================================
# UUID Generation
# =============================================================================


def generate_uuid() -> str:
    """
    Generate a unique identifier for database records.

    Uses UUID4 (random) which provides sufficient uniqueness
    for a single-user personal knowledge base.

    Returns:
        String UUID (e.g., "550e8400-e29b-41d4-a716-446655440000")
    """
    return str(uuid.uuid4())


# =============================================================================
# Timestamp Helpers
# =============================================================================


def now_iso() -> str:
    """
    Get current UTC time as ISO 8601 string.

    Returns:
        ISO 8601 timestamp (e.g., "2024-01-15T10:30:00Z")
    """
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def epoch_iso() -> str:
    """
    Get Unix epoch as ISO 8601 string.

    Used as default valid_from for claims that are always valid.

    Returns:
        "1970-01-01T00:00:00Z"
    """
    return "1970-01-01T00:00:00Z"


def is_valid_iso_timestamp(ts: str) -> bool:
    """
    Validate an ISO 8601 timestamp string.

    Args:
        ts: Timestamp string to validate.

    Returns:
        True if valid ISO 8601 format, False otherwise.
    """
    if not ts or not isinstance(ts, str):
        return False

    try:
        # Try parsing with timezone
        datetime.fromisoformat(ts.replace("Z", "+00:00"))
        return True
    except (ValueError, AttributeError):
        return False


def parse_iso_timestamp(ts: str) -> Optional[datetime]:
    """
    Parse an ISO 8601 timestamp string to datetime.

    Args:
        ts: ISO 8601 timestamp string.

    Returns:
        datetime object or None if invalid.
    """
    if not ts:
        return None
    try:
        return datetime.fromisoformat(ts.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return None


def is_timestamp_in_range(
    check_ts: str, valid_from: str, valid_to: Optional[str]
) -> bool:
    """
    Check if a timestamp falls within a validity range.

    Args:
        check_ts: Timestamp to check.
        valid_from: Start of validity range.
        valid_to: End of validity range (None = no end).

    Returns:
        True if check_ts is within [valid_from, valid_to].
    """
    check = parse_iso_timestamp(check_ts)
    start = parse_iso_timestamp(valid_from)
    end = parse_iso_timestamp(valid_to) if valid_to else None

    if not check or not start:
        return False

    if check < start:
        return False

    if end and check > end:
        return False

    return True


# =============================================================================
# JSON Validation and Manipulation
# =============================================================================


def is_valid_json(s: Optional[str]) -> bool:
    """
    Check if a string is valid JSON.

    Args:
        s: String to validate.

    Returns:
        True if valid JSON, False otherwise.
    """
    if not s:
        return True  # None/empty is valid (no metadata)

    try:
        json.loads(s)
        return True
    except (json.JSONDecodeError, TypeError):
        return False


def parse_meta_json(s: Optional[str]) -> Dict[str, Any]:
    """
    Parse meta_json field to dictionary.

    Args:
        s: JSON string or None.

    Returns:
        Parsed dictionary or empty dict if None/invalid.
    """
    if not s:
        return {}

    try:
        result = json.loads(s)
        return result if isinstance(result, dict) else {}
    except (json.JSONDecodeError, TypeError):
        return {}


def update_meta_json(existing: Optional[str], updates: Dict[str, Any]) -> str:
    """
    Update meta_json field by merging with existing values.

    Args:
        existing: Current meta_json string (or None).
        updates: Dictionary of updates to apply.

    Returns:
        Updated JSON string.

    Example:
        >>> update_meta_json('{"a": 1}', {"b": 2})
        '{"a": 1, "b": 2}'
    """
    current = parse_meta_json(existing)
    current.update(updates)
    return json.dumps(current)


def get_meta_value(meta_json: Optional[str], key: str, default: Any = None) -> Any:
    """
    Get a specific value from meta_json.

    Args:
        meta_json: JSON string.
        key: Key to retrieve.
        default: Default value if key not found.

    Returns:
        Value for key or default.
    """
    data = parse_meta_json(meta_json)
    return data.get(key, default)


# =============================================================================
# Parallel Execution
# =============================================================================


class ParallelExecutor:
    """
    Wrapper for ThreadPoolExecutor with convenience methods.

    Compatible with patterns used in code_common/call_llm.py.
    Used for parallel execution of LLM calls, embedding computations,
    and independent search strategies.

    Attributes:
        max_workers: Maximum number of concurrent workers.
        executor: Underlying ThreadPoolExecutor instance.
    """

    def __init__(self, max_workers: int = 8):
        """
        Initialize executor with specified worker count.

        Args:
            max_workers: Maximum concurrent threads (default: 8).
        """
        self.max_workers = max_workers
        self.executor = ThreadPoolExecutor(max_workers=max_workers)

    def map_parallel(
        self, fn: Callable[..., T], items: List[Any], timeout: float = 60.0
    ) -> List[T]:
        """
        Execute function on each item in parallel, return results in order.

        Args:
            fn: Function to apply to each item.
            items: List of items to process.
            timeout: Timeout per task in seconds.

        Returns:
            List of results in same order as items.

        Raises:
            TimeoutError: If any task exceeds timeout.
            Exception: If any task raises an exception.
        """
        if not items:
            return []

        futures = [self.executor.submit(fn, item) for item in items]
        results = []

        for future in futures:
            try:
                results.append(future.result(timeout=timeout))
            except Exception as e:
                logger.error(f"Parallel execution failed: {e}")
                raise

        return results

    def map_parallel_kwargs(
        self,
        fn: Callable[..., T],
        kwargs_list: List[Dict[str, Any]],
        timeout: float = 60.0,
    ) -> List[T]:
        """
        Execute function with different kwargs in parallel.

        Args:
            fn: Function to call.
            kwargs_list: List of kwargs dictionaries.
            timeout: Timeout per task in seconds.

        Returns:
            List of results in same order as kwargs_list.
        """
        if not kwargs_list:
            return []

        futures = [self.executor.submit(fn, **kwargs) for kwargs in kwargs_list]
        return [f.result(timeout=timeout) for f in futures]

    def submit_all(self, tasks: List[Callable[[], T]]) -> List[Future]:
        """
        Submit multiple independent tasks.

        Args:
            tasks: List of zero-argument callables.

        Returns:
            List of Future objects.
        """
        return [self.executor.submit(task) for task in tasks]

    def wait_all(self, futures: List[Future], timeout: float = 60.0) -> List[Any]:
        """
        Wait for all futures to complete and return results.

        Args:
            futures: List of Future objects.
            timeout: Total timeout for all futures.

        Returns:
            List of results in same order as futures.
        """
        return [f.result(timeout=timeout) for f in futures]

    def shutdown(self, wait: bool = True) -> None:
        """
        Shutdown the executor.

        Args:
            wait: Wait for pending tasks to complete.
        """
        self.executor.shutdown(wait=wait)


# Module-level executor for convenience
_default_executor: Optional[ParallelExecutor] = None


def get_parallel_executor(max_workers: int = 8) -> ParallelExecutor:
    """
    Get or create the default ParallelExecutor.

    For most use cases, a single shared executor is sufficient.
    Use this for parallelizing LLM calls, embeddings, and searches.

    Args:
        max_workers: Max workers (only used if creating new executor).

    Returns:
        ParallelExecutor instance.
    """
    global _default_executor
    if _default_executor is None:
        _default_executor = ParallelExecutor(max_workers=max_workers)
    return _default_executor


def reset_parallel_executor() -> None:
    """Reset the default executor (useful for testing)."""
    global _default_executor
    if _default_executor:
        _default_executor.shutdown(wait=False)
        _default_executor = None


# =============================================================================
# String Helpers
# =============================================================================


def truncate_string(s: str, max_length: int = 100, suffix: str = "...") -> str:
    """
    Truncate string to max length with suffix.

    Args:
        s: String to truncate.
        max_length: Maximum length including suffix.
        suffix: Suffix to append if truncated.

    Returns:
        Truncated string.
    """
    if len(s) <= max_length:
        return s
    return s[: max_length - len(suffix)] + suffix


def normalize_whitespace(s: str) -> str:
    """
    Normalize whitespace in string (collapse multiple spaces, trim).

    Args:
        s: String to normalize.

    Returns:
        Normalized string.
    """
    return " ".join(s.split())


# =============================================================================
# Friendly ID Generation & Validation
# =============================================================================

# Pattern for valid friendly IDs: alphanumeric, underscores, hyphens
FRIENDLY_ID_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def validate_friendly_id(friendly_id: str) -> bool:
    """
    Validate that a friendly_id matches the allowed pattern.

    Friendly IDs are user-facing identifiers for memories and contexts.
    They must be alphanumeric with underscores and hyphens allowed.
    Minimum length is 2 characters, maximum 128.

    Args:
        friendly_id: The ID string to validate.

    Returns:
        True if valid, False otherwise.
    """
    if not friendly_id or not isinstance(friendly_id, str):
        return False
    if len(friendly_id) < 2 or len(friendly_id) > 128:
        return False
    return bool(FRIENDLY_ID_PATTERN.match(friendly_id))


def generate_friendly_id(
    statement: str, max_words: int = 3, suffix_len: int = 4
) -> str:
    """
    Generate a short, human-readable friendly ID that captures the essence
    of a statement.

    Strategy:
    1. Lowercase and strip non-alphanumeric characters
    2. Remove common stopwords (articles, pronouns, auxiliary verbs, etc.)
    3. Take up to max_words meaningful words (1-3 typically)
    4. Join with underscores and append a 4-char random alphanumeric suffix

    The result is short (typically 10-30 chars), descriptive, and unique.

    Args:
        statement: The claim/context text to generate ID from.
        max_words: Maximum number of meaningful words to use (default: 3).
        suffix_len: Length of random suffix (default: 4).

    Returns:
        Friendly ID string, e.g., "prefer_morning_workouts_a3f2"

    Examples:
        >>> generate_friendly_id("I prefer morning workouts over evening ones")
        'prefer_morning_workouts_x7k2'
        >>> generate_friendly_id("My favorite color is blue")
        'favorite_color_blue_p4m1'
        >>> generate_friendly_id("I am allergic to peanuts")
        'allergic_peanuts_r9d3'
    """
    if not statement or not isinstance(statement, str):
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        return f"memory_{suffix}"

    # Clean: lowercase, keep only alphanumeric and spaces
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", statement.lower().strip())

    words = cleaned.split()
    if not words:
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=8))
        return f"memory_{suffix}"

    # Comprehensive stopword list — remove filler words to keep only meaningful ones
    stopwords = {
        "i",
        "me",
        "my",
        "mine",
        "myself",
        "we",
        "our",
        "ours",
        "ourselves",
        "you",
        "your",
        "yours",
        "he",
        "him",
        "his",
        "she",
        "her",
        "hers",
        "it",
        "its",
        "they",
        "them",
        "their",
        "theirs",
        "a",
        "an",
        "the",
        "this",
        "that",
        "these",
        "those",
        "is",
        "am",
        "are",
        "was",
        "were",
        "be",
        "been",
        "being",
        "have",
        "has",
        "had",
        "having",
        "do",
        "does",
        "did",
        "doing",
        "will",
        "would",
        "shall",
        "should",
        "may",
        "might",
        "must",
        "can",
        "could",
        "not",
        "no",
        "nor",
        "but",
        "and",
        "or",
        "so",
        "if",
        "then",
        "than",
        "to",
        "of",
        "in",
        "for",
        "on",
        "at",
        "by",
        "with",
        "from",
        "up",
        "about",
        "into",
        "over",
        "after",
        "before",
        "between",
        "under",
        "during",
        "very",
        "really",
        "just",
        "also",
        "too",
        "more",
        "most",
        "some",
        "any",
        "all",
        "each",
        "every",
        "both",
        "few",
        "many",
        "much",
        "been",
        "there",
        "here",
        "when",
        "where",
        "what",
        "which",
        "who",
        "whom",
        "how",
        "why",
        "because",
        "since",
        "while",
        "although",
        "ones",
        "like",
        "get",
        "got",
        "make",
        "made",
    }

    filtered = [w for w in words if w not in stopwords and len(w) > 1]

    # If all words were filtered, use first meaningful word from original
    if not filtered:
        filtered = [w for w in words if len(w) > 1]
    if not filtered:
        filtered = words[:1]

    # Take up to max_words
    id_words = filtered[:max_words]

    base_id = "_".join(id_words)

    # Truncate if too long
    max_base_len = 60 - suffix_len - 1
    if len(base_id) > max_base_len:
        base_id = base_id[:max_base_len]

    # Add random suffix for uniqueness
    suffix = "".join(
        random.choices(string.ascii_lowercase + string.digits, k=suffix_len)
    )

    candidate = f"{base_id}_{suffix}"

    # Guard: ensure claim friendly_ids never end with a reserved type suffix.
    # This prevents ambiguity with suffix-based routing in resolve_reference().
    # Extremely unlikely (random 4-char suffix would have to match), but we
    # guard for correctness.
    from .constants import RESERVED_FRIENDLY_ID_SUFFIXES

    for _reserved in RESERVED_FRIENDLY_ID_SUFFIXES:
        if candidate.endswith(_reserved):
            # Regenerate suffix until no collision
            suffix = "".join(
                random.choices(string.ascii_lowercase + string.digits, k=suffix_len)
            )
            candidate = f"{base_id}_{suffix}"
            break

    return candidate


# =============================================================================
# Typed Friendly ID Generation (v0.7 — Universal References)
# =============================================================================

# Shared stopword set for typed friendly ID generators.  Re-uses the same
# comprehensive list from generate_friendly_id() above.
_TYPED_STOPWORDS = {
    "i",
    "me",
    "my",
    "mine",
    "myself",
    "we",
    "our",
    "ours",
    "ourselves",
    "you",
    "your",
    "yours",
    "he",
    "him",
    "his",
    "she",
    "her",
    "hers",
    "it",
    "its",
    "they",
    "them",
    "their",
    "theirs",
    "a",
    "an",
    "the",
    "this",
    "that",
    "these",
    "those",
    "is",
    "am",
    "are",
    "was",
    "were",
    "be",
    "been",
    "being",
    "have",
    "has",
    "had",
    "having",
    "do",
    "does",
    "did",
    "doing",
    "will",
    "would",
    "shall",
    "should",
    "may",
    "might",
    "must",
    "can",
    "could",
    "not",
    "no",
    "nor",
    "but",
    "and",
    "or",
    "so",
    "if",
    "then",
    "than",
    "to",
    "of",
    "in",
    "for",
    "on",
    "at",
    "by",
    "with",
    "from",
    "up",
    "about",
    "into",
    "over",
    "after",
    "before",
    "between",
    "under",
    "during",
    "very",
    "really",
    "just",
    "also",
    "too",
    "more",
    "most",
    "some",
    "any",
    "all",
    "each",
    "every",
    "both",
    "few",
    "many",
    "much",
    "been",
    "there",
    "here",
    "when",
    "where",
    "what",
    "which",
    "who",
    "whom",
    "how",
    "why",
    "because",
    "since",
    "while",
    "although",
    "ones",
    "like",
    "get",
    "got",
    "make",
    "made",
}


def _extract_meaningful_words(text: str, max_words: int = 3) -> list:
    """
    Extract up to max_words meaningful words from text for use in friendly IDs.

    Shared helper for generate_entity_friendly_id, generate_tag_friendly_id,
    and generate_context_friendly_id.

    Args:
        text: Raw text (name, label, etc.).
        max_words: Maximum words to keep.

    Returns:
        List of lowercase meaningful words.
    """
    if not text or not isinstance(text, str):
        return []
    cleaned = re.sub(r"[^a-zA-Z0-9\s]", "", text.lower().strip())
    words = cleaned.split()
    if not words:
        return []

    filtered = [w for w in words if w not in _TYPED_STOPWORDS and len(w) > 1]
    if not filtered:
        # Fall back to first words if all were stopwords
        filtered = [w for w in words if len(w) > 1]
    if not filtered:
        filtered = words[:1]

    return filtered[:max_words]


def generate_entity_friendly_id(name: str, entity_type: str) -> str:
    """
    Generate a deterministic friendly_id for an entity.

    Format: {name_words}_{entity_type}_entity

    No random suffix is needed because entities are unique per
    (user_email, entity_type, name) DB constraint.  The entity_type
    in the friendly_id disambiguates entities with the same name but
    different types (e.g. "Apple" as org vs topic).

    Args:
        name: Entity display name (e.g. "John Smith").
        entity_type: Entity type from EntityType enum (e.g. "person").

    Returns:
        Friendly ID string, e.g. "john_smith_person_entity"

    Examples:
        >>> generate_entity_friendly_id("John Smith", "person")
        'john_smith_person_entity'
        >>> generate_entity_friendly_id("Google", "org")
        'google_org_entity'
        >>> generate_entity_friendly_id("Machine Learning", "topic")
        'machine_learning_topic_entity'
    """
    words = _extract_meaningful_words(name, max_words=3)
    if not words:
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"entity_{suffix}_{entity_type}_entity"

    base = "_".join(words)
    # Truncate base if too long (keep room for _{entity_type}_entity)
    type_suffix = f"_{entity_type}_entity"
    max_base_len = 60 - len(type_suffix)
    if len(base) > max_base_len:
        base = base[:max_base_len]

    return f"{base}{type_suffix}"


def generate_tag_friendly_id(name: str) -> str:
    """
    Generate a deterministic friendly_id for a tag.

    Format: {name_words}_tag

    No random suffix needed — tags are unique per (user_email, name, parent_tag_id).
    If a collision occurs the caller can append a disambiguator.

    Args:
        name: Tag name (e.g. "fitness", "morning routine").

    Returns:
        Friendly ID string, e.g. "fitness_tag"

    Examples:
        >>> generate_tag_friendly_id("fitness")
        'fitness_tag'
        >>> generate_tag_friendly_id("morning routine")
        'morning_routine_tag'
    """
    words = _extract_meaningful_words(name, max_words=3)
    if not words:
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"tag_{suffix}_tag"

    base = "_".join(words)
    max_base_len = 60 - len("_tag")
    if len(base) > max_base_len:
        base = base[:max_base_len]

    return f"{base}_tag"


def generate_context_friendly_id(name: str) -> str:
    """
    Generate a deterministic friendly_id for a context.

    Format: {name_words}_context

    Changed from v0.6 (which had no suffix) to v0.7 (with _context suffix)
    to enable unambiguous suffix-based routing.

    Args:
        name: Context display name (e.g. "Health Goals").

    Returns:
        Friendly ID string, e.g. "health_goals_context"

    Examples:
        >>> generate_context_friendly_id("Health Goals")
        'health_goals_context'
        >>> generate_context_friendly_id("Project Alpha")
        'project_alpha_context'
    """
    words = _extract_meaningful_words(name, max_words=3)
    if not words:
        suffix = "".join(random.choices(string.ascii_lowercase + string.digits, k=6))
        return f"context_{suffix}_context"

    base = "_".join(words)
    max_base_len = 60 - len("_context")
    if len(base) > max_base_len:
        base = base[:max_base_len]

    return f"{base}_context"


def domain_to_friendly_id(domain_name: str) -> str:
    """
    Convert a domain_name to its friendly_id representation.

    Domains don't have a DB column for friendly_id — this is computed
    at reference time.  The _domain suffix enables suffix-based routing.

    Args:
        domain_name: Machine-readable domain key (e.g. "health", "life_ops").

    Returns:
        Friendly ID string, e.g. "health_domain"

    Examples:
        >>> domain_to_friendly_id("health")
        'health_domain'
        >>> domain_to_friendly_id("life_ops")
        'life_ops_domain'
    """
    return f"{domain_name}_domain"
