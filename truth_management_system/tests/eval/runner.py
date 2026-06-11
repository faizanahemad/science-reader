"""
Eval runner for the PKB retrieval harness.

Seeds a throwaway PKB from an :class:`EvalDataset`, runs each query through the
real search path (:class:`HybridSearchStrategy`) for one or more strategy
configurations, and computes recall@k / MRR per configuration.

Network behavior:
- ``fts`` is pure SQLite and runs offline.
- ``embedding`` / hybrid require ``OPENROUTER_API_KEY`` (or a monkeypatched
  embedding function). When no key is present, ``HybridSearchStrategy`` only
  registers ``fts``, so embedding configs are skipped automatically.

CLI:
    python -m truth_management_system.tests.eval.runner [--dataset PATH] [--k 10]
"""

from __future__ import annotations

import os
import shutil
import tempfile
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from ...config import PKBConfig
from ...database import PKBDatabase
from ...crud.claims import ClaimCRUD
from ...models import Claim
from ...search.base import SearchFilters
from ...search.hybrid_search import HybridSearchStrategy

from .dataset import EvalDataset, load_dataset
from .metrics import recall_at_k, precision_at_k, reciprocal_rank, aggregate_case_metrics


@dataclass
class StrategyReport:
    """Metrics for one strategy configuration over a dataset."""
    label: str
    strategy_names: List[str]
    k: int
    per_case: List[Dict] = field(default_factory=list)
    aggregate: Dict[str, float] = field(default_factory=dict)
    by_category: Dict[str, Dict[str, float]] = field(default_factory=dict)


@dataclass
class EvalReport:
    """Top-level report spanning one or more strategy configurations."""
    dataset_name: str
    k: int
    num_claims: int
    num_cases: int
    strategy_reports: Dict[str, StrategyReport] = field(default_factory=dict)

    def format_report(self) -> str:
        lines = [
            f"PKB eval report — dataset='{self.dataset_name}', "
            f"claims={self.num_claims}, cases={self.num_cases}, k={self.k}",
            "=" * 72,
        ]
        for label, rep in self.strategy_reports.items():
            agg = rep.aggregate
            metric_str = "  ".join(f"{m}={v:.3f}" for m, v in agg.items())
            lines.append(f"[{label}] strategies={rep.strategy_names}")
            lines.append(f"    overall   {metric_str}")
            for cat, cagg in rep.by_category.items():
                cstr = "  ".join(f"{m}={v:.3f}" for m, v in cagg.items())
                lines.append(f"    {cat:<13} {cstr}")
        return "\n".join(lines)

    def to_dict(self) -> Dict:
        """Serialize the full report (aggregate + per-category + per-case) to JSON-able dict."""
        return {
            "dataset_name": self.dataset_name,
            "k": self.k,
            "num_claims": self.num_claims,
            "num_cases": self.num_cases,
            "strategies": {
                label: {
                    "strategy_names": rep.strategy_names,
                    "aggregate": rep.aggregate,
                    "by_category": rep.by_category,
                    "per_case": rep.per_case,
                }
                for label, rep in self.strategy_reports.items()
            },
        }


class EvalRunner:
    """
    Seeds a temporary PKB and evaluates retrieval against a dataset.

    Args:
        keys: API keys dict (pass ``{"OPENROUTER_API_KEY": ...}`` to enable
            embedding/hybrid configs). Defaults to reading the environment.
        config: Optional PKBConfig. A temp on-disk DB path is injected if the
            given config has no usable path.
        db: Optional pre-built PKBDatabase (e.g. a pytest fixture). When given,
            the runner will not create or delete a database of its own.
    """

    def __init__(
        self,
        keys: Optional[Dict[str, str]] = None,
        config: Optional[PKBConfig] = None,
        db: Optional[PKBDatabase] = None,
    ):
        if keys is None:
            keys = {}
            if os.environ.get("OPENROUTER_API_KEY"):
                keys["OPENROUTER_API_KEY"] = os.environ["OPENROUTER_API_KEY"]
        self.keys = keys
        self._owns_db = db is None
        self._tmpdir: Optional[str] = None

        if db is None:
            self._tmpdir = tempfile.mkdtemp(prefix="pkb_eval_")
            db_path = os.path.join(self._tmpdir, "pkb_eval.sqlite")
            self.config = config or PKBConfig(db_path=db_path)
            # The runner owns a throwaway DB here, so the temp path ALWAYS wins —
            # even when a caller passes a tuned config (e.g. for a weight sweep)
            # whose db_path still points at the default persistent location.
            self.config.db_path = db_path
            self.db = PKBDatabase(self.config)
            self.db.connect()
            self.db.initialize_schema()
        else:
            self.db = db
            self.config = config or PKBConfig(db_path=getattr(db.config, "db_path", ":memory:"))

        self._key_to_id: Dict[str, str] = {}

    # ------------------------------------------------------------------ seed
    @staticmethod
    def _resolve_ts(value: Optional[str]) -> Optional[str]:
        """
        Resolve a timestamp spec to an ISO string matching ``now_iso()``.

        Accepts a relative shorthand ``[+-]N[d|h|m]`` (days/hours/minutes from
        now) or a literal ISO string (returned unchanged). ``None`` -> ``None``.
        """
        if not value:
            return None
        import re
        from datetime import datetime, timezone, timedelta
        m = re.fullmatch(r"\s*([+-]?\d+)\s*([dhm])\s*", value)
        if not m:
            return value  # assume already ISO
        n = int(m.group(1))
        unit = m.group(2)
        delta = {"d": timedelta(days=n), "h": timedelta(hours=n), "m": timedelta(minutes=n)}[unit]
        return (datetime.now(timezone.utc) + delta).strftime("%Y-%m-%dT%H:%M:%SZ")

    def seed(self, dataset: EvalDataset, apply_expiry: bool = True) -> Dict[str, str]:
        """
        Insert the dataset's claims (applying any lifecycle overrides) and
        return a ``key -> claim_id`` map.

        When ``apply_expiry`` is True, runs ``expire_stale_claims`` after seeding
        so claims with a past ``valid_to`` transition to 'expired' (hard TTL).
        """
        import json as _json
        crud = ClaimCRUD(self.db)
        self._key_to_id = {}
        for ec in dataset.claims:
            claim = Claim.create(
                statement=ec.statement,
                claim_type=ec.claim_type,
                context_domain=ec.context_domain,
            )
            if ec.status:
                claim.status = ec.status
            if ec.confidence is not None:
                claim.confidence = ec.confidence
            ca = self._resolve_ts(ec.created_at)
            if ca:
                claim.created_at = ca
            ua = self._resolve_ts(ec.updated_at)
            if ua:
                claim.updated_at = ua
            vt = self._resolve_ts(ec.valid_to)
            if vt:
                claim.valid_to = vt
            # Merge pin/meta into meta_json.
            meta = {}
            if getattr(claim, "meta_json", None):
                try:
                    meta = _json.loads(claim.meta_json) or {}
                except Exception:
                    meta = {}
            if ec.pinned:
                meta["pinned"] = True
            if ec.meta:
                meta.update(ec.meta)
            if meta:
                claim.meta_json = _json.dumps(meta)
            crud.add(claim)
            self._key_to_id[ec.key] = claim.claim_id

            # Entity-linked retrieval (W-C): create/link declared entities.
            if ec.entities:
                from ...crud.entities import EntityCRUD
                from ...crud.links import link_claim_entity
                from ...constants import EntityType
                ent_crud = EntityCRUD(self.db)
                for ename in ec.entities:
                    ent, _ = ent_crud.get_or_create(ename, EntityType.ORG.value)
                    link_claim_entity(self.db, claim.claim_id, ent.entity_id, "subject")

            # Tag-linked retrieval (W-D): create/link declared tags.
            if ec.tags:
                from ...crud.tags import TagCRUD
                from ...crud.links import link_claim_tag
                tag_crud = TagCRUD(self.db)
                for tname in ec.tags:
                    tag, _ = tag_crud.get_or_create(tname)
                    link_claim_tag(self.db, claim.claim_id, tag.tag_id)

        if apply_expiry:
            try:
                from ...utils import expire_stale_claims
                expire_stale_claims(self.db)
            except Exception:
                pass
        return dict(self._key_to_id)

    # ------------------------------------------------------------------- run
    def run(
        self,
        dataset: EvalDataset,
        strategy_names: Optional[List[str]] = None,
        k: int = 10,
        label: Optional[str] = None,
    ) -> StrategyReport:
        """
        Run every case through one strategy configuration and score it.

        Requires :meth:`seed` to have been called for ``dataset`` first.
        """
        if not self._key_to_id:
            raise RuntimeError("Call seed(dataset) before run().")

        hybrid = HybridSearchStrategy(self.db, self.keys, self.config)
        strat = strategy_names or ["fts"]
        label = label or "+".join(strat)
        recall_key = f"recall@{k}"
        precision_key = f"precision@{k}"

        per_case: List[Dict] = []
        case_metrics: List[Dict[str, float]] = []
        cat_metrics: Dict[str, List[Dict[str, float]]] = {}
        for case in dataset.cases:
            filters = SearchFilters(**case.filters) if case.filters else SearchFilters()
            results = hybrid.search(
                case.query,
                strategy_names=strat,
                k=k,
                filters=filters,
            )
            # Dedupe retrieved claim IDs, preserving rank order.
            seen = set()
            retrieved_ids: List[str] = []
            for r in results:
                cid = r.claim.claim_id
                if cid not in seen:
                    seen.add(cid)
                    retrieved_ids.append(cid)

            expected_ids = [self._key_to_id[key] for key in case.expected]
            metrics = {
                recall_key: recall_at_k(retrieved_ids, expected_ids, k),
                precision_key: precision_at_k(retrieved_ids, expected_ids, k),
                "rr": reciprocal_rank(retrieved_ids, expected_ids),
            }
            case_metrics.append(metrics)
            cat_metrics.setdefault(case.category, []).append(metrics)
            per_case.append({
                "query": case.query,
                "category": case.category,
                "expected": case.expected,
                "retrieved": retrieved_ids,
                "metrics": metrics,
            })

        def _finalize(metric_list: List[Dict[str, float]]) -> Dict[str, float]:
            agg = aggregate_case_metrics(metric_list)
            if "rr" in agg:  # mean of per-case reciprocal ranks == MRR
                agg["mrr"] = agg.pop("rr")
            return agg

        aggregate = _finalize(case_metrics)
        by_category = {cat: _finalize(ms) for cat, ms in sorted(cat_metrics.items())}
        return StrategyReport(
            label=label,
            strategy_names=strat,
            k=k,
            per_case=per_case,
            aggregate=aggregate,
            by_category=by_category,
        )

    def evaluate(
        self,
        dataset: EvalDataset,
        k: int = 10,
        strategy_sets: Optional[Dict[str, List[str]]] = None,
    ) -> EvalReport:
        """
        Seed (if needed) and evaluate multiple strategy configurations.

        ``strategy_sets`` maps a label to a list of strategy names. When omitted,
        evaluates ``fts`` and — if embeddings are available — ``embedding`` and
        ``hybrid`` (fts+embedding).
        """
        if not self._key_to_id:
            self.seed(dataset)

        available = set(HybridSearchStrategy(self.db, self.keys, self.config).get_available_strategies())
        if strategy_sets is None:
            strategy_sets = {"fts": ["fts"]}
            if "entity" in available:
                # Entity-linked retrieval runs offline (no key needed); it
                # degrades to recency order without embeddings.
                strategy_sets["entity"] = ["entity"]
            if "tag" in available:
                # Tag-linked retrieval (W-D). Only registered when
                # tag_strategy_enabled is set, so this is absent by default.
                strategy_sets["tag"] = ["tag"]
            if "embedding" in available:
                strategy_sets["embedding"] = ["embedding"]
                strategy_sets["hybrid"] = ["fts", "embedding"]

        report = EvalReport(
            dataset_name=dataset.name,
            k=k,
            num_claims=len(dataset.claims),
            num_cases=len(dataset.cases),
        )
        for label, strat in strategy_sets.items():
            report.strategy_reports[label] = self.run(dataset, strat, k=k, label=label)
        return report

    # ----------------------------------------------------------------- close
    def close(self) -> None:
        """Close and remove the temp DB if this runner created it."""
        if self._owns_db and self.db is not None:
            try:
                self.db.close()
            except Exception:
                pass
        if self._tmpdir and os.path.isdir(self._tmpdir):
            shutil.rmtree(self._tmpdir, ignore_errors=True)
            self._tmpdir = None

    def __enter__(self) -> "EvalRunner":
        return self

    def __exit__(self, *exc) -> None:
        self.close()


def _main() -> int:
    import argparse
    import json as _json

    parser = argparse.ArgumentParser(description="Run the PKB retrieval eval harness.")
    parser.add_argument("--dataset", default=None, help="Path to a dataset JSON (default: bundled seed_dataset.json).")
    parser.add_argument("--k", type=int, default=10, help="Top-k cutoff (default: 10).")
    parser.add_argument("--json", action="store_true", help="Emit the full report (incl. per-case) as JSON.")
    parser.add_argument("--verbose", action="store_true", help="Print per-case query/expected/retrieved details.")
    args = parser.parse_args()

    dataset = load_dataset(args.dataset)
    with EvalRunner() as runner:
        runner.seed(dataset)
        report = runner.evaluate(dataset, k=args.k)

    if args.json:
        print(_json.dumps(report.to_dict(), indent=2))
        return 0

    print(report.format_report())
    if args.verbose:
        for label, rep in report.strategy_reports.items():
            print(f"\n--- per-case [{label}] ---")
            for pc in rep.per_case:
                ms = "  ".join(f"{m}={v:.2f}" for m, v in pc["metrics"].items())
                print(f"  [{pc['category']}] {pc['query']!r}  ({ms})")
    return 0


if __name__ == "__main__":
    raise SystemExit(_main())
