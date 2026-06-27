"""Tests for the LSH index."""
import unittest
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from vecnn.lsh import LSHIndex
from vecnn.bench import exact_knn, recall_at_k


def _unit_vectors(n, dim, seed=0):
    rng = np.random.default_rng(seed)
    v = rng.standard_normal((n, dim))
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return v


class TestLSHBasic(unittest.TestCase):

    def test_empty_search(self):
        idx = LSHIndex(dim=8)
        q = np.array([1.0] + [0.0] * 7)
        self.assertEqual(idx.search(q, k=5), [])

    def test_single_insert_search(self):
        idx = LSHIndex(dim=4, n_tables=5, n_bits=8, seed=0)
        v = np.array([1.0, 0.0, 0.0, 0.0])
        nid = idx.insert(v)
        results = idx.search(v, k=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], nid)

    def test_size(self):
        idx = LSHIndex(dim=4, n_tables=5, seed=0)
        vecs = _unit_vectors(15, 4)
        for v in vecs:
            idx.insert(v)
        self.assertEqual(idx.size, 15)

    def test_metadata_preserved(self):
        idx = LSHIndex(dim=4, seed=1)
        v = np.array([1.0, 0.0, 0.0, 0.0])
        idx.insert(v, metadata={"tag": "test"})
        results = idx.search(v, k=1)
        self.assertEqual(results[0][2]["tag"], "test")

    def test_results_sorted(self):
        idx = LSHIndex(dim=8, n_tables=10, n_bits=12, seed=2)
        vecs = _unit_vectors(50, 8, 2)
        for v in vecs:
            idx.insert(v)
        q = vecs[0]
        results = idx.search(q, k=10)
        dists = [r[1] for r in results]
        self.assertEqual(dists, sorted(dists))

    def test_delete(self):
        idx = LSHIndex(dim=4, seed=3)
        vecs = _unit_vectors(10, 4, 3)
        ids = [idx.insert(v) for v in vecs]
        idx.delete(ids[0])
        self.assertEqual(idx.size, 9)
        results = idx.search(vecs[0], k=5)
        self.assertNotIn(ids[0], [r[0] for r in results])

    def test_wrong_dim_raises(self):
        idx = LSHIndex(dim=4)
        with self.assertRaises(ValueError):
            idx.insert(np.array([1.0, 2.0]))


class TestLSHRecall(unittest.TestCase):

    def test_reasonable_recall(self):
        """
        With short hash codes (n_bits=4), LSH gets high collision probability
        even for vectors that are only moderately close (typical in high-dim
        random unit-vector space).  With n_bits=4 and 20 tables the expected
        recall@5 exceeds 0.5 for dim=32.
        """
        n, dim = 500, 32
        vecs = _unit_vectors(n, dim, seed=10)
        # Short hash codes → more collisions → higher recall (at the cost of
        # more false-positive candidates that are filtered by exact re-scoring).
        idx = LSHIndex(dim=dim, n_tables=20, n_bits=4, seed=10)
        ids = [idx.insert(v) for v in vecs]

        query_vecs = _unit_vectors(10, dim, seed=99)
        total_recall = 0.0
        for q in query_vecs:
            true_top = {ids[i] for i in exact_knn(q, vecs, 5, "cosine")}
            approx = [r[0] for r in idx.search(q, k=5)]
            total_recall += recall_at_k(true_top, approx)
        avg = total_recall / len(query_vecs)
        # LSH recall is fundamentally lower than HNSW; gate at 0.3
        self.assertGreaterEqual(avg, 0.3, f"LSH recall@5={avg:.3f}")


class TestLSHSerialization(unittest.TestCase):

    def test_roundtrip(self):
        idx = LSHIndex(dim=8, n_tables=5, n_bits=8, seed=20)
        vecs = _unit_vectors(30, 8, 20)
        ids = [idx.insert(v) for v in vecs]
        d = idx.to_dict()
        idx2 = LSHIndex.from_dict(d)
        self.assertEqual(idx2.size, 30)
        q = vecs[0]
        r1 = {x[0] for x in idx.search(q, k=5)}
        r2 = {x[0] for x in idx2.search(q, k=5)}
        self.assertEqual(r1, r2)


if __name__ == "__main__":
    unittest.main()
