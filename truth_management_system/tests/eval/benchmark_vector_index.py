#!/usr/bin/env python
"""
Workstream B4 — synthetic benchmark for the vector index backends.

Generates random unit embeddings at several corpus sizes and times:
  - linear: the pure-Python per-vector cosine loop (the pre-index baseline)
  - flat:   VectorIndex flat backend (vectorized numpy matmul, exact)
  - hnsw:   VectorIndex faiss HNSW backend (approximate), if faiss is installed

For the approximate backend it also reports recall@k against the exact ranking.
This is network-free and DB-free.

Usage:
  python -m truth_management_system.tests.eval.benchmark_vector_index \
      [--sizes 1000 10000 50000] [--dim 1536] [--k 20] [--queries 20]
"""

import argparse
import time
from typing import List, Tuple

import numpy as np

from truth_management_system.search.ann_vector_index import (
    VectorIndex,
    faiss_available,
)


def _make_items(n: int, dim: int) -> List[Tuple[str, np.ndarray]]:
    rng = np.random.default_rng(42)
    mat = rng.standard_normal((n, dim)).astype(np.float32)
    return [(f"c{i}", mat[i]) for i in range(n)]


def _linear_topk(query: np.ndarray, items, k: int) -> List[str]:
    q = query / (np.linalg.norm(query) or 1.0)
    scored = []
    for cid, v in items:
        nv = np.linalg.norm(v)
        sim = float(np.dot(q, v) / nv) if nv else 0.0
        scored.append((cid, sim))
    scored.sort(key=lambda x: x[1], reverse=True)
    return [cid for cid, _ in scored[:k]]


def _time(fn, queries) -> float:
    start = time.perf_counter()
    for q in queries:
        fn(q)
    return (time.perf_counter() - start) / len(queries) * 1000.0  # ms/query


def _recall(approx: List[str], exact: List[str]) -> float:
    if not exact:
        return 1.0
    return len(set(approx) & set(exact)) / len(exact)


def run(sizes, dim, k, n_queries):
    rng = np.random.default_rng(7)
    queries = [rng.standard_normal(dim).astype(np.float32) for _ in range(n_queries)]

    print(f"\nVector index benchmark — dim={dim}, k={k}, queries={n_queries}")
    print(f"faiss available: {faiss_available()}")
    header = f"{'size':>8} | {'linear ms':>10} | {'flat ms':>9} | {'hnsw ms':>9} | {'hnsw recall':>11}"
    print(header)
    print("-" * len(header))

    for n in sizes:
        items = _make_items(n, dim)

        flat = VectorIndex(backend="flat").build(items)
        linear_ms = _time(lambda q: _linear_topk(q, items, k), queries)
        flat_ms = _time(lambda q: flat.search(q, k), queries)

        hnsw_ms = float("nan")
        recall = float("nan")
        if faiss_available():
            hnsw = VectorIndex(backend="hnsw").build(items)
            hnsw_ms = _time(lambda q: hnsw.search(q, k), queries)
            recall = float(
                np.mean([
                    _recall(
                        [cid for cid, _ in hnsw.search(q, k)],
                        [cid for cid, _ in flat.search(q, k)],
                    )
                    for q in queries
                ])
            )

        print(
            f"{n:>8} | {linear_ms:>10.3f} | {flat_ms:>9.3f} | "
            f"{hnsw_ms:>9.3f} | {recall:>11.3f}"
        )


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--sizes", type=int, nargs="+", default=[1000, 10000, 50000])
    ap.add_argument("--dim", type=int, default=1536)
    ap.add_argument("--k", type=int, default=20)
    ap.add_argument("--queries", type=int, default=20)
    args = ap.parse_args()
    run(args.sizes, args.dim, args.k, args.queries)


if __name__ == "__main__":
    main()
