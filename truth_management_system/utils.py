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

import uuid
import json
import logging
from datetime import datetime, timezone
from concurrent.futures import ThreadPoolExecutor, Future, as_completed
from typing import Dict, Optional, List, Callable, TypeVar, Any

T = TypeVar('T')

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
        datetime.fromisoformat(ts.replace('Z', '+00:00'))
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
        return datetime.fromisoformat(ts.replace('Z', '+00:00'))
    except (ValueError, AttributeError):
        return None


def is_timestamp_in_range(
    check_ts: str,
    valid_from: str,
    valid_to: Optional[str]
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
        self,
        fn: Callable[..., T],
        items: List[Any],
        timeout: float = 60.0
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
        timeout: float = 60.0
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
    
    def wait_all(
        self,
        futures: List[Future],
        timeout: float = 60.0
    ) -> List[Any]:
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
    return s[:max_length - len(suffix)] + suffix


def normalize_whitespace(s: str) -> str:
    """
    Normalize whitespace in string (collapse multiple spaces, trim).
    
    Args:
        s: String to normalize.
        
    Returns:
        Normalized string.
    """
    return ' '.join(s.split())
