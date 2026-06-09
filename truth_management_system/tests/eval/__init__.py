"""
PKB retrieval evaluation harness (plan Workstream G, G1-task).

Provides:
- metrics: recall@k, reciprocal rank, MRR, and aggregation helpers.
- dataset: dataclasses + JSON loader for (claims, query->expected) eval cases.
- runner: seeds a PKB from a dataset, runs queries through the real search
  strategies (HybridSearchStrategy), and computes per-strategy metrics.

The harness exists to measure retrieval quality so that ranking changes
(Workstream C) and the ANN index (Workstream B) can be validated against a
baseline instead of eyeballed.

Run the bundled seed dataset (network-free, FTS only):
    python -m truth_management_system.tests.eval.runner
"""

from .metrics import (
    recall_at_k,
    reciprocal_rank,
    mean_reciprocal_rank,
    aggregate_case_metrics,
)
from .dataset import EvalClaim, EvalCase, EvalDataset, load_dataset, default_dataset_path
from .runner import EvalRunner, EvalReport, StrategyReport

__all__ = [
    "recall_at_k",
    "reciprocal_rank",
    "mean_reciprocal_rank",
    "aggregate_case_metrics",
    "EvalClaim",
    "EvalCase",
    "EvalDataset",
    "load_dataset",
    "default_dataset_path",
    "EvalRunner",
    "EvalReport",
    "StrategyReport",
]
