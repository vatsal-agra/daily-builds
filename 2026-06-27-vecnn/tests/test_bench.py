"""Tests for the benchmarking utilities."""
import unittest
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from vecnn.bench import exact_knn, recall_at_k, benchmark, compare_indices
from vecnn.hnsw import HNSWIndex
from vecnn.lsh import LSHIndex


def _unit_vectors(n, dim, seed=0):
    rng = np.random.default_rng(seed)
    v = rng.standard_normal((n, dim))
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return v


class TestExactKNN(unittest.TestCase):

    def test_returns_k_results(self):
        vecs = _unit_vectors(50, 8, seed=0)
        q = vecs[0]
        results = exact_knn(q, vecs, k=5, metric="cosine")
        self.assertEqual(len(results), 5)

    def test_first_result_is_self(self):
        vecs = _unit_vectors(20, 8, seed=1)
        q = vecs[3]
        results = exact_knn(q, vecs, k=1, metric="cosine")
        self.assertEqual(results[0], 3)

    def test_sorted_ascending(self):
        from vecnn.distance import cosine_distance_batch
        vecs = _unit_vectors(30, 8, seed=2)
        q = vecs[0]
        results = exact_knn(q, vecs, k=10, metric="cosine")
        dists = cosine_distance_batch(q, vecs)
        for i in range(len(results) - 1):
            self.assertLessEqual(dists[results[i]], dists[results[i+1]] + 1e-12)

    def test_k_larger_than_n(self):
        vecs = _unit_vectors(5, 4, seed=3)
        q = vecs[0]
        results = exact_knn(q, vecs, k=20, metric="cosine")
        self.assertEqual(len(results), 5)

    def test_euclidean_metric(self):
        # unit vectors: nearest by euclidean should also be very close by cosine
        vecs = _unit_vectors(30, 8, seed=4)
        q = vecs[0]
        eu_results = exact_knn(q, vecs, k=3, metric="euclidean")
        self.assertEqual(eu_results[0], 0)


class TestRecallAtK(unittest.TestCase):

    def test_perfect_recall(self):
        true_set = {1, 2, 3, 4, 5}
        approx = [1, 2, 3, 4, 5]
        self.assertAlmostEqual(recall_at_k(true_set, approx), 1.0)

    def test_zero_recall(self):
        true_set = {1, 2, 3}
        approx = [4, 5, 6]
        self.assertAlmostEqual(recall_at_k(true_set, approx), 0.0)

    def test_partial_recall(self):
        true_set = {1, 2, 3, 4}
        approx = [1, 2, 5, 6]
        self.assertAlmostEqual(recall_at_k(true_set, approx), 0.5)

    def test_empty_true_set(self):
        self.assertAlmostEqual(recall_at_k(set(), [1, 2, 3]), 1.0)


class TestBenchmark(unittest.TestCase):

    def test_benchmark_returns_results_for_each_ef(self):
        n, dim = 200, 16
        vecs = _unit_vectors(n, dim, seed=10)
        idx = HNSWIndex(dim=dim, metric="cosine", M=8, ef_construction=100, seed=10)
        ids = [idx.insert(v) for v in vecs]
        query_vecs = _unit_vectors(5, dim, seed=99)
        ef_vals = [10, 50, 100]
        results = benchmark(idx, query_vecs, vecs, ids, k=5, ef_values=ef_vals)
        self.assertEqual(len(results), 3)
        for r in results:
            self.assertIn("ef", r)
            self.assertIn("recall_at_k", r)
            self.assertIn("qps", r)
            self.assertIn("avg_query_ms", r)
            self.assertGreaterEqual(r["recall_at_k"], 0.0)
            self.assertLessEqual(r["recall_at_k"], 1.0)

    def test_higher_ef_generally_higher_recall(self):
        n, dim = 500, 32
        vecs = _unit_vectors(n, dim, seed=11)
        idx = HNSWIndex(dim=dim, metric="cosine", M=16, ef_construction=200, seed=11)
        ids = [idx.insert(v) for v in vecs]
        query_vecs = _unit_vectors(20, dim, seed=88)
        ef_vals = [5, 50, 200]
        results = benchmark(idx, query_vecs, vecs, ids, k=5, ef_values=ef_vals)
        recalls = [r["recall_at_k"] for r in results]
        # recall@5 should be non-decreasing as ef grows (softly, not strict)
        self.assertGreaterEqual(recalls[-1], recalls[0])


class TestCompareIndices(unittest.TestCase):

    def test_compare_returns_all_methods(self):
        n, dim = 200, 16
        vecs = _unit_vectors(n, dim, seed=20)
        hnsw = HNSWIndex(dim=dim, metric="cosine", M=8, ef_construction=100, seed=20)
        ids = [hnsw.insert(v) for v in vecs]
        lsh = LSHIndex(dim=dim, n_tables=10, n_bits=12, seed=20)
        for nid, v in zip(ids, vecs):
            lsh.insert(v, node_id=nid)
        query_vecs = _unit_vectors(10, dim, seed=99)
        comp = compare_indices(hnsw, lsh, query_vecs, vecs, ids, k=5)
        self.assertIn("exact", comp)
        self.assertIn("hnsw", comp)
        self.assertIn("lsh", comp)

    def test_exact_recall_is_one(self):
        n, dim = 100, 8
        vecs = _unit_vectors(n, dim, seed=21)
        hnsw = HNSWIndex(dim=dim, metric="cosine", M=8, ef_construction=100, seed=21)
        ids = [hnsw.insert(v) for v in vecs]
        query_vecs = _unit_vectors(5, dim, seed=77)
        comp = compare_indices(hnsw, None, query_vecs, vecs, ids, k=5)
        self.assertAlmostEqual(comp["exact"]["recall_at_k"], 1.0, places=5)


if __name__ == "__main__":
    unittest.main()
