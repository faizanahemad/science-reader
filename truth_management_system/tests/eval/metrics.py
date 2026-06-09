"""
Information-retrieval metrics for the PKB eval harness.

All functions operate on plain lists/sets of claim IDs (strings) so they are
decoupled from the search layer and trivially unit-testable.

Conventions:
- ``retrieved_ids`` is an ordered list (rank 0 = top result), possibly with
  duplicates removed by the caller.
- ``expected_ids`` is the set of relevant/ground-truth claim IDs for a query.
- ``k`` is the cutoff (top-k). ``k <= 0`` means "no cutoff" (use all).
"""

from __future__ import annotations

from typing import Dict, Iterable, List, Sequence, Set


def _topk(retrieved_ids: Sequence[str], k: int) -> List[str]:
    """Return the top-k slice (k <= 0 means the whole list)."""
    if k is None or k <= 0:
        return list(retrieved_ids)
    return list(retrieved_ids[:k])


def recall_at_k(
    retrieved_ids: Sequence[str],
    expected_ids: Iterable[str],
    k: int = 10,
) -> float:
    """
    Fraction of expected (relevant) IDs that appear in the top-k retrieved.

    recall@k = |expected ∩ top_k(retrieved)| / |expected|

    Returns 0.0 when there are no expected IDs (nothing to recall).
    """
    expected: Set[str] = set(expected_ids)
    if not expected:
        return 0.0
    top = set(_topk(retrieved_ids, k))
    hits = len(expected & top)
    return hits / len(expected)


def precision_at_k(
    retrieved_ids: Sequence[str],
    expected_ids: Iterable[str],
    k: int = 10,
) -> float:
    """
    Fraction of the top-k retrieved IDs that are relevant.

    precision@k = |expected ∩ top_k(retrieved)| / |top_k(retrieved)|

    Returns 0.0 when nothing was retrieved.
    """
    expected: Set[str] = set(expected_ids)
    top = _topk(retrieved_ids, k)
    if not top:
        return 0.0
    hits = sum(1 for cid in top if cid in expected)
    return hits / len(top)


def reciprocal_rank(
    retrieved_ids: Sequence[str],
    expected_ids: Iterable[str],
) -> float:
    """
    Reciprocal of the rank (1-indexed) of the first relevant result.

    RR = 1 / rank_of_first_hit, or 0.0 if no expected ID was retrieved.
    """
    expected: Set[str] = set(expected_ids)
    if not expected:
        return 0.0
    for idx, cid in enumerate(retrieved_ids):
        if cid in expected:
            return 1.0 / (idx + 1)
    return 0.0


def mean_reciprocal_rank(
    per_case: Iterable[Sequence[str]],
    per_case_expected: Iterable[Iterable[str]],
) -> float:
    """
    Mean reciprocal rank across cases.

    Args:
        per_case: iterable of retrieved-ID lists, one per query.
        per_case_expected: iterable of expected-ID iterables, one per query.
    """
    rrs: List[float] = []
    for retrieved, expected in zip(per_case, per_case_expected):
        rrs.append(reciprocal_rank(retrieved, expected))
    if not rrs:
        return 0.0
    return sum(rrs) / len(rrs)


def aggregate_case_metrics(
    case_metrics: List[Dict[str, float]],
) -> Dict[str, float]:
    """
    Average a list of per-case metric dicts into a single summary dict.

    Every key present in any case is averaged over the *total* number of
    cases (missing keys count as 0.0). Returns {} for an empty input.
    """
    if not case_metrics:
        return {}
    keys: Set[str] = set()
    for m in case_metrics:
        keys.update(m.keys())
    n = len(case_metrics)
    return {key: sum(m.get(key, 0.0) for m in case_metrics) / n for key in sorted(keys)}
