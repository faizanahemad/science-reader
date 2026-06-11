# PKB Retrieval Eval Harness

Measures *retrieval quality* for the PKB so ranking and indexing changes can be
validated against a baseline instead of eyeballed. Implements plan Workstream G
(`G1-task`) under `documentation/planning/plans/pkb_memory_system_improvements.plan.md`.

## Quick start

```bash
# From the repo root (auto-activates the 'science-reader' conda env):
./truth_management_system/tests/eval/run_eval.sh --k 5
./truth_management_system/tests/eval/run_eval.sh --k 5 --verbose      # per-case detail
./truth_management_system/tests/eval/run_eval.sh --k 5 --json > eval.json

# Or directly:
python -m truth_management_system.tests.eval.runner --k 5 [--dataset PATH] [--json] [--verbose]
```

Without `OPENROUTER_API_KEY`, only the **FTS** strategy runs (fully offline). Export
the key to also evaluate `embedding` and `hybrid` (`fts`+`embedding`) configs.

## What it reports

Per strategy config, an overall line plus a **per-category** breakdown of:

- `recall@k` — did the expected claim(s) appear in the top-k?
- `precision@k` — how many of the top-k are relevant? (drops when distractors rank high)
- `mrr` — mean reciprocal rank of the first relevant result (captures *ordering*).

Example (network-free FTS over the bundled `seed_dataset.json`):

```
PKB eval report — dataset='pkb_seed_v3', claims=46, cases=38, k=5
[fts] strategies=['fts']
    overall       precision@5=0.537  recall@5=0.763  mrr=0.664
    lexical       precision@5=0.730  recall@5=1.000  mrr=1.000
    scoped        precision@5=1.000  recall@5=1.000  mrr=1.000
    lifecycle     precision@5=0.600  recall@5=1.000  mrr=0.625
    multi         precision@5=1.000  recall@5=1.000  mrr=1.000
    temporal      precision@5=1.000  recall@5=1.000  mrr=1.000
    hard_negative precision@5=0.375  recall@5=1.000  mrr=0.750
    recency       precision@5=0.500  recall@5=1.000  mrr=0.500
    conflict      precision@5=0.500  recall@5=1.000  mrr=0.500
    semantic      precision@5=0.050  recall@5=0.100  mrr=0.050
```

## Case categories

| Category | What it tests | Who should win | Current FTS |
|---|---|---|---|
| `lexical` | Query shares words with the target | FTS | strong (baseline) |
| `multi` | Several relevant targets | any | strong |
| `scoped` | Per-case `SearchFilters` (type/domain) — **existing** capability | filters | strong |
| `lifecycle` | Superseded/expired excluded by default — **existing** | status+expiry | strong recall |
| `temporal` | Two dated claims on a topic; recall both | any | strong |
| `hard_negative` | A tempting distractor shares strong tokens | better ranking | low precision → room to grow |
| `recency` | Expect the **newer** of two claims (ordering) | Workstream C (recency decay) | mrr 0.50 at default; **1.00 with `w_recency` on** |
| `conflict` | Contradictory claims; expect the current one | Workstream C/D/H | mrr 0.50 at default; **1.00 with `w_recency` on** |
| `semantic` | Paraphrase with no shared word-prefix | embeddings/hybrid | ~0 → room to grow |

The low categories are intentional headroom: they encode capabilities the plan
will deliver (embeddings, recency ranking, conflict resolution), so improvements
show up as measurable gains here.

## Dataset format (`seed_dataset.json`)

```jsonc
{
  "name": "...", "description": "...",
  "claims": [
    {"key": "stable_key", "statement": "...", "claim_type": "fact", "context_domain": "health",
     // optional lifecycle fields:
     "status": "superseded",          // ClaimStatus value (default 'active')
     "confidence": 0.9,                // 0..1 (for confidence-weighted ranking, WS C)
     "created_at": "-400d", "updated_at": "-10d",  // ISO or relative [+-]N[d|h|m]
     "valid_to": "-7d",               // past value + expiry sweep -> 'expired'
     "pinned": true, "meta": {"k": "v"}}
  ],
  "cases": [
    {"query": "...", "expected": ["key1"], "category": "lexical",
     "not_expected": ["key2"],          // hard negatives (diagnostics)
     "filters": {"context_domains": ["work"], "claim_types": ["task"]}}  // -> SearchFilters
  ]
}
```

`key`s map to auto-generated `claim_id`s at seed time, so the dataset is stable.
`load_dataset()` validates that every `expected`/`not_expected` key exists.

## Programmatic use (weight sweeps for WS C / H)

```python
from truth_management_system.config import PKBConfig
from truth_management_system.tests.eval import EvalRunner, load_dataset

ds = load_dataset()
# Sweep the recency weight (Workstream C). The runner always uses an isolated
# temp DB, so a tuned config is safe to pass.
for w in (0.0, 1.0, 2.0):
    cfg = PKBConfig(w_recency=w, recency_half_life_days=60.0)
    with EvalRunner(keys={}, config=cfg) as r:
        r.seed(ds)
        report = r.evaluate(ds, k=5)
    print(w, report.strategy_reports["fts"].by_category["recency"]["mrr"])
# 0.0 -> 0.500   (default: newer/older tie, older wins on insertion order)
# 1.0 -> 1.000   (recency promotes the newer claim)
# 2.0 -> 1.000

with EvalRunner(keys={"OPENROUTER_API_KEY": "..."}) as r:
    r.seed(ds)  # applies lifecycle overrides + expiry sweep
    report = r.evaluate(ds, k=10, strategy_sets={"fts": ["fts"], "hybrid": ["fts", "embedding"]})
    print(report.format_report())
    data = report.to_dict()  # JSON-able (aggregate + by_category + per_case)
```

The recency/conflict cases use **distinctive queries** (e.g. `iphone`,
`honda tesla`, `keto mediterranean`, `eat meat`) that match essentially only the
paired claims, so the metric reflects newer-vs-older *ordering* rather than
FTS common-word noise. At the default `w_recency = 0` the re-rank is an exact
no-op, so this baseline is stable for regression.

## Gating the rewrite/entity unification (keyed)

The single-rewrite-call unification (`rewrite_is_query_source` +
`entity_use_rewrite_entities`, on by default) only engages with a key — the
`hybrid` default set includes `rewrite` + `entity`, so one rewrite LLM call
drives FTS/embedding/entity. To gate it:

```bash
export OPENROUTER_API_KEY=...        # the app LLM path is OpenRouter-only
./truth_management_system/tests/eval/run_eval.sh --k 5 --verbose
```

> Bulk keyed runs trip a pre-existing `SQLITE_MISUSE` because the embedding
> store reads/writes one shared sqlite connection from parallel worker threads
> (prod embeds incrementally and never hits it). For a stable run, construct the
> `EvalRunner` with `PKBConfig(max_parallel_embedding_calls=1,
> max_parallel_llm_calls=1)` — serial execution does not change RRF results.

Compare the `[hybrid]` block against `[fts]` and `[entity]`; precision@5 / mrr
should improve or hold and recall@5 must not regress. To make the LLM-entity
advantage visible (lowercase / paraphrased entity references the regex heuristic
misses), add such cases under a new category (e.g. `entity_nl`) — the guard test
only floors `lexical`, so a new category is safe.

Then sweep the **W-A** per-source weights and ship only what helps:

```python
from truth_management_system.tests.eval.runner import EvalRunner
from truth_management_system.tests.eval.dataset import load_dataset

ds = load_dataset()
for w in ({}, {"fts": 0.6, "embedding": 1.0, "rewrite": 1.0, "entity": 0.8}):
    with EvalRunner(keys={"OPENROUTER_API_KEY": "..."}) as r:
        r.config.rrf_strategy_weights = w
        r.seed(ds)
        print(w, r.run(ds, strategy_names=["fts", "embedding", "rewrite", "entity"], k=5).overall)
```

(`rrf_k` stays 60 during tuning.) See
`documentation/planning/plans/pkb_rewrite_entity_unification.plan.md`.

## Files

- `metrics.py` — `recall_at_k`, `precision_at_k`, `reciprocal_rank`, `mean_reciprocal_rank`, `aggregate_case_metrics`.
- `dataset.py` — `EvalClaim` / `EvalCase` / `EvalDataset` + `load_dataset`.
- `seed_dataset.json` — the bundled persona dataset.
- `runner.py` — `EvalRunner`, `StrategyReport`, `EvalReport`, CLI.
- `run_eval.sh` — portable wrapper (conda activation + repo-root cwd).
- `../test_eval_harness.py` — metric unit tests + network-free FTS guards.

## Extending toward realism

This is synthetic data. For stronger signal, augment with **real anonymized
queries** labeled with expected claim keys (the plan flags labels as the core
challenge). The keyed-JSON format is designed so new cases drop in without
touching the runner or metrics.
