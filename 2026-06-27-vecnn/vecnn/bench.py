"""
Benchmarking utilities for approximate nearest-neighbour indices.

Provides:
  - exact_knn()     — brute-force ground truth (O(N*D))
  - recall_at_k()   — fraction of true top-k found by approximate search
  - benchmark()     — full recall vs. speed sweep at multiple ef values
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional, Set, Tuple

import numpy as np

from .distance import get_batch_metric
from .hnsw import HNSWIndex
from .lsh import LSHIndex


def exact_knn(
    query: np.ndarray,
    vectors: np.ndarray,
    k: int,
    metric: str = "cosine",
) -> List[int]:
    """
    Brute-force exact k-nearest neighbours.

    Parameters
    ----------
    query : (d,) array
    vectors : (n, d) array
    k : int
    metric : str

    Returns sorted list of indices (0-based into `vectors`) of the k closest.
    """
    dist_fn = get_batch_metric(metric)
    dists = dist_fn(query, vectors)
    k_actual = min(k, len(vectors))
    # argpartition for O(n) top-k selection
    top_k_idx = np.argpartition(dists, k_actual - 1)[:k_actual]
    top_k_idx = top_k_idx[np.argsort(dists[top_k_idx])]
    return top_k_idx.tolist()


def recall_at_k(true_ids: Set[int], approx_ids: List[int]) -> float:
    """Fraction of true nearest neighbours found in the approximate result."""
    if not true_ids:
        return 1.0
    hits = sum(1 for i in approx_ids if i in true_ids)
    return hits / len(true_ids)


def benchmark(
    index: HNSWIndex,
    query_vectors: np.ndarray,
    all_vectors: np.ndarray,
    all_ids: List[int],
    k: int = 10,
    ef_values: Optional[List[int]] = None,
) -> List[Dict[str, Any]]:
    """
    Sweep over ef (beam width) values and measure recall@k and QPS.

    Parameters
    ----------
    index : HNSWIndex
        Already-built index.
    query_vectors : (n_queries, dim)
    all_vectors : (n_total, dim) — the *exact* vectors in insertion order,
        aligned with all_ids.
    all_ids : list of int — node ids, aligned with all_vectors rows.
    k : int
    ef_values : list of ef values to sweep; defaults to a sensible range.

    Returns list of dicts: {ef, recall_at_k, qps, avg_query_ms}
    """
    if ef_values is None:
        ef_values = sorted({k, k * 2, k * 4, k * 8, 50, 100, 200, 400})
        ef_values = [e for e in ef_values if e >= k]

    # Build id→row mapping for exact search
    id_to_row = {nid: row for row, nid in enumerate(all_ids)}
    metric = index.metric

    results = []
    for ef in ef_values:
        recalls = []
        start = time.perf_counter()
        for q in query_vectors:
            hits = index.search(q, k=k, ef=ef)
            approx_ids = [h[0] for h in hits]

            # get exact ground truth by indexing all_vectors
            q_row_indices = np.array([id_to_row[nid] for nid in all_ids
                                      if nid in id_to_row], dtype=np.int64)
            # Use only live (non-deleted) vectors for exact search
            live_rows = q_row_indices if len(q_row_indices) == len(all_ids) else None
            true_indices = exact_knn(q, all_vectors, k, metric)
            true_set = {all_ids[i] for i in true_indices if i < len(all_ids)}

            recalls.append(recall_at_k(true_set, approx_ids))

        elapsed = time.perf_counter() - start
        n_queries = len(query_vectors)
        qps = n_queries / elapsed if elapsed > 0 else float("inf")
        results.append({
            "ef": ef,
            "recall_at_k": float(np.mean(recalls)),
            "qps": round(qps, 1),
            "avg_query_ms": round(elapsed * 1000 / n_queries, 2),
        })

    return results


def compare_indices(
    hnsw_index: HNSWIndex,
    lsh_index: Optional[LSHIndex],
    query_vectors: np.ndarray,
    all_vectors: np.ndarray,
    all_ids: List[int],
    k: int = 10,
) -> Dict[str, Any]:
    """
    Head-to-head comparison: exact vs HNSW (default ef) vs LSH.
    Returns a dict with per-method recall and QPS.
    """
    metric = hnsw_index.metric
    id_to_row = {nid: i for i, nid in enumerate(all_ids)}

    def _run(search_fn):
        recalls = []
        start = time.perf_counter()
        for q in query_vectors:
            hits = search_fn(q)
            approx_ids = [h[0] for h in hits]
            true_indices = exact_knn(q, all_vectors, k, metric)
            true_set = {all_ids[i] for i in true_indices if i < len(all_ids)}
            recalls.append(recall_at_k(true_set, approx_ids))
        elapsed = time.perf_counter() - start
        n = len(query_vectors)
        return {
            "recall_at_k": float(np.mean(recalls)),
            "qps": round(n / elapsed, 1) if elapsed > 0 else float("inf"),
            "avg_ms": round(elapsed * 1000 / n, 2),
        }

    def _exact(q):
        true_indices = exact_knn(q, all_vectors, k, metric)
        return [(all_ids[i], 0.0, {}) for i in true_indices]

    out = {
        "k": k,
        "n_queries": len(query_vectors),
        "n_vectors": len(all_ids),
        "exact": _run(_exact),
        "hnsw": _run(lambda q: hnsw_index.search(q, k=k)),
    }
    if lsh_index is not None:
        out["lsh"] = _run(lambda q: lsh_index.search(q, k=k))
    return out
