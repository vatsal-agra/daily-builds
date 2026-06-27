"""Tests for the HNSW index."""
import json
import math
import unittest
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from vecnn.hnsw import HNSWIndex
from vecnn.distance import cosine_distance, euclidean_distance
from vecnn.bench import exact_knn, recall_at_k


def _unit_vectors(n, dim, seed=0):
    rng = np.random.default_rng(seed)
    v = rng.standard_normal((n, dim))
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return v


class TestHNSWBasic(unittest.TestCase):

    def test_empty_search_returns_empty(self):
        idx = HNSWIndex(dim=4, metric="cosine")
        q = np.array([1.0, 0.0, 0.0, 0.0])
        self.assertEqual(idx.search(q, k=5), [])

    def test_single_insert_and_search(self):
        idx = HNSWIndex(dim=3, metric="cosine", seed=0)
        v = np.array([1.0, 0.0, 0.0])
        nid = idx.insert(v)
        results = idx.search(v, k=1)
        self.assertEqual(len(results), 1)
        self.assertEqual(results[0][0], nid)
        self.assertAlmostEqual(results[0][1], 0.0, places=10)

    def test_size_tracking(self):
        idx = HNSWIndex(dim=4, metric="cosine", seed=1)
        vecs = _unit_vectors(10, 4, 10)
        for v in vecs:
            idx.insert(v)
        self.assertEqual(idx.size, 10)

    def test_wrong_dim_raises(self):
        idx = HNSWIndex(dim=4, metric="cosine")
        with self.assertRaises(ValueError):
            idx.insert(np.array([1.0, 0.0]))

    def test_invalid_metric_raises(self):
        with self.assertRaises(ValueError):
            HNSWIndex(dim=4, metric="manhattan")

    def test_metadata_preserved(self):
        idx = HNSWIndex(dim=3, metric="cosine", seed=2)
        v = np.array([1.0, 0.0, 0.0])
        nid = idx.insert(v, metadata={"label": "cat", "score": 42})
        results = idx.search(v, k=1)
        self.assertEqual(results[0][2]["label"], "cat")
        self.assertEqual(results[0][2]["score"], 42)

    def test_results_sorted_ascending(self):
        idx = HNSWIndex(dim=8, metric="cosine", seed=3, M=4, ef_construction=50)
        vecs = _unit_vectors(50, 8, 3)
        for v in vecs:
            idx.insert(v)
        q = vecs[0]
        results = idx.search(q, k=10)
        dists = [r[1] for r in results]
        self.assertEqual(dists, sorted(dists))

    def test_recall_high_for_small_index(self):
        """On a tiny index, recall@5 should be perfect."""
        idx = HNSWIndex(dim=16, metric="cosine", seed=4, M=8, ef_construction=100)
        vecs = _unit_vectors(200, 16, 4)
        ids = [idx.insert(v) for v in vecs]
        q = _unit_vectors(1, 16, 99)[0]
        # Exact top-5
        true_top = set(exact_knn(q, vecs, 5, "cosine"))
        true_ids = {ids[i] for i in true_top}
        approx = idx.search(q, k=5, ef=200)
        approx_ids = [r[0] for r in approx]
        recall = recall_at_k(true_ids, approx_ids)
        self.assertGreaterEqual(recall, 0.8)  # conservative gate; usually 1.0


class TestHNSWMetrics(unittest.TestCase):

    def test_euclidean_nearest_is_correct(self):
        idx = HNSWIndex(dim=2, metric="euclidean", seed=5, M=4, ef_construction=50)
        vecs = np.array([[0.0, 0.0], [1.0, 0.0], [0.0, 1.0], [10.0, 10.0]])
        for v in vecs:
            idx.insert(v)
        q = np.array([0.1, 0.1])
        results = idx.search(q, k=1, ef=100)
        # nearest should be (0,0)
        nid = results[0][0]
        nn_vec = idx.get_node(nid).vector
        self.assertAlmostEqual(nn_vec[0], 0.0, places=5)
        self.assertAlmostEqual(nn_vec[1], 0.0, places=5)

    def test_inner_product_metric(self):
        idx = HNSWIndex(dim=4, metric="inner", seed=6, M=4, ef_construction=50)
        vecs = _unit_vectors(50, 4, 6)
        for v in vecs:
            idx.insert(v)
        q = vecs[0]
        results = idx.search(q, k=1)
        # The closest by inner product (negated) should be q itself or very close
        self.assertLessEqual(results[0][1], 0.0)


class TestHNSWRecallAtScale(unittest.TestCase):

    def test_recall_at_k10_medium(self):
        """1000 vectors, dim=32 → recall@10 at ef=200 should exceed 0.85."""
        n, dim = 1000, 32
        vecs = _unit_vectors(n, dim, seed=7)
        idx = HNSWIndex(dim=dim, metric="cosine", M=16, ef_construction=200, seed=7)
        ids = [idx.insert(v) for v in vecs]

        query_vecs = _unit_vectors(20, dim, seed=77)
        total_recall = 0.0
        for q in query_vecs:
            true_top = set(ids[i] for i in exact_knn(q, vecs, 10, "cosine"))
            approx = [r[0] for r in idx.search(q, k=10, ef=200)]
            total_recall += recall_at_k(true_top, approx)
        avg_recall = total_recall / len(query_vecs)
        self.assertGreaterEqual(avg_recall, 0.85,
            f"recall@10={avg_recall:.3f} below 0.85 gate")

    def test_higher_ef_gives_higher_recall(self):
        """Recall should be monotonically non-decreasing as ef increases."""
        n, dim = 500, 16
        vecs = _unit_vectors(n, dim, seed=8)
        idx = HNSWIndex(dim=dim, metric="cosine", M=8, ef_construction=100, seed=8)
        ids = [idx.insert(v) for v in vecs]
        q = _unit_vectors(1, dim, seed=88)[0]
        true_top = set(ids[i] for i in exact_knn(q, vecs, 5, "cosine"))

        prev_recall = 0.0
        for ef in [5, 10, 20, 50, 100, 200]:
            approx = [r[0] for r in idx.search(q, k=5, ef=ef)]
            r = recall_at_k(true_top, approx)
            self.assertGreaterEqual(r, prev_recall - 0.01)  # allow tiny float wobble
            prev_recall = r

    def test_recall_cosine_vs_euclidean(self):
        """Both metrics should achieve reasonable recall on unit vectors."""
        n, dim = 300, 16
        vecs = _unit_vectors(n, dim, seed=9)
        q = _unit_vectors(1, dim, seed=99)[0]
        for metric in ["cosine", "euclidean"]:
            idx = HNSWIndex(dim=dim, metric=metric, M=8, ef_construction=100, seed=9)
            ids = [idx.insert(v) for v in vecs]
            true_top = set(ids[i] for i in exact_knn(q, vecs, 5, metric))
            approx = [r[0] for r in idx.search(q, k=5, ef=100)]
            r = recall_at_k(true_top, approx)
            self.assertGreaterEqual(r, 0.6, f"recall@5 for {metric}={r:.3f}")


class TestHNSWDelete(unittest.TestCase):

    def test_delete_removes_from_results(self):
        idx = HNSWIndex(dim=4, metric="cosine", seed=10, M=4, ef_construction=50)
        vecs = _unit_vectors(20, 4, 10)
        ids = [idx.insert(v) for v in vecs]
        # Search before delete
        q = vecs[0]
        before = {r[0] for r in idx.search(q, k=5, ef=50)}
        # Delete the closest (id=0, which is vecs[0] itself)
        idx.delete(ids[0])
        self.assertEqual(idx.size, 19)
        after = {r[0] for r in idx.search(q, k=5, ef=50)}
        self.assertNotIn(ids[0], after)

    def test_delete_nonexistent(self):
        idx = HNSWIndex(dim=4, metric="cosine")
        self.assertFalse(idx.delete(999))

    def test_delete_all_then_search(self):
        idx = HNSWIndex(dim=4, metric="cosine", seed=11)
        ids = [idx.insert(_unit_vectors(1, 4, i)[0]) for i in range(5)]
        for nid in ids:
            idx.delete(nid)
        q = np.array([1.0, 0.0, 0.0, 0.0])
        self.assertEqual(idx.search(q, k=3), [])


class TestHNSWMetadataFilter(unittest.TestCase):

    def test_filter_restricts_results(self):
        idx = HNSWIndex(dim=8, metric="cosine", seed=12, M=8, ef_construction=100)
        vecs = _unit_vectors(100, 8, 12)
        ids = [idx.insert(v, metadata={"cat": "A" if i % 2 == 0 else "B"})
               for i, v in enumerate(vecs)]
        q = vecs[0]
        results = idx.search(q, k=10, ef=100, filter_fn=lambda m: m.get("cat") == "A")
        for nid, dist, meta in results:
            self.assertEqual(meta["cat"], "A")

    def test_filter_can_return_empty(self):
        idx = HNSWIndex(dim=4, metric="cosine", seed=13)
        vecs = _unit_vectors(10, 4, 13)
        for v in vecs:
            idx.insert(v, metadata={"cat": "X"})
        q = vecs[0]
        results = idx.search(q, k=5, filter_fn=lambda m: m.get("cat") == "Y")
        self.assertEqual(results, [])


class TestHNSWSerialization(unittest.TestCase):

    def _build_index(self, n=100, dim=16, seed=14):
        vecs = _unit_vectors(n, dim, seed)
        idx = HNSWIndex(dim=dim, metric="cosine", M=8, ef_construction=100, seed=seed)
        ids = []
        for i, v in enumerate(vecs):
            ids.append(idx.insert(v, metadata={"i": i}))
        return idx, vecs, ids

    def test_to_dict_from_dict_roundtrip(self):
        idx, vecs, ids = self._build_index()
        d = idx.to_dict()
        idx2 = HNSWIndex.from_dict(d)
        q = vecs[0]
        r1 = [(x[0], round(x[1], 8)) for x in idx.search(q, k=5, ef=50)]
        r2 = [(x[0], round(x[1], 8)) for x in idx2.search(q, k=5, ef=50)]
        self.assertEqual(r1, r2)

    def test_json_roundtrip(self):
        idx, vecs, ids = self._build_index(n=50)
        d = idx.to_dict()
        json_str = json.dumps(d)
        idx2 = HNSWIndex.from_dict(json.loads(json_str))
        q = vecs[5]
        r1 = [x[0] for x in idx.search(q, k=3, ef=50)]
        r2 = [x[0] for x in idx2.search(q, k=3, ef=50)]
        self.assertEqual(r1, r2)

    def test_size_preserved_after_roundtrip(self):
        idx, _, ids = self._build_index(n=60)
        d = idx.to_dict()
        idx2 = HNSWIndex.from_dict(d)
        self.assertEqual(idx2.size, 60)

    def test_deleted_nodes_preserved(self):
        idx, vecs, ids = self._build_index(n=20)
        idx.delete(ids[0])
        idx.delete(ids[5])
        d = idx.to_dict()
        idx2 = HNSWIndex.from_dict(d)
        self.assertEqual(idx2.size, 18)
        self.assertTrue(idx2.get_node(ids[0]).deleted)


class TestHNSWLayerGraph(unittest.TestCase):

    def test_layer0_contains_all_nodes(self):
        idx = HNSWIndex(dim=8, metric="cosine", M=4, ef_construction=50, seed=15)
        vecs = _unit_vectors(30, 8, 15)
        ids = [idx.insert(v) for v in vecs]
        g = idx.get_layer_graph(0)
        self.assertEqual(set(g.keys()), set(ids))

    def test_higher_layer_subset_of_lower(self):
        idx = HNSWIndex(dim=8, metric="cosine", M=4, ef_construction=50, seed=16)
        vecs = _unit_vectors(100, 8, 16)
        for v in vecs:
            idx.insert(v)
        g0 = set(idx.get_layer_graph(0).keys())
        if idx._max_layer >= 1:
            g1 = set(idx.get_layer_graph(1).keys())
            self.assertTrue(g1.issubset(g0))


class TestHNSWEdgeCases(unittest.TestCase):

    def test_k_larger_than_index(self):
        idx = HNSWIndex(dim=4, metric="cosine", seed=17)
        vecs = _unit_vectors(5, 4, 17)
        for v in vecs:
            idx.insert(v)
        q = vecs[0]
        results = idx.search(q, k=20)
        self.assertLessEqual(len(results), 5)

    def test_ef_less_than_k(self):
        idx = HNSWIndex(dim=4, metric="cosine", seed=18, M=4, ef_construction=50)
        vecs = _unit_vectors(50, 4, 18)
        for v in vecs:
            idx.insert(v)
        q = vecs[0]
        # ef<k is allowed; search should not crash
        results = idx.search(q, k=10, ef=3)
        self.assertGreaterEqual(len(results), 0)

    def test_node_ids_unique(self):
        idx = HNSWIndex(dim=4, metric="cosine", seed=19)
        vecs = _unit_vectors(50, 4, 19)
        ids = [idx.insert(v) for v in vecs]
        self.assertEqual(len(ids), len(set(ids)))

    def test_stats_keys(self):
        idx = HNSWIndex(dim=4, metric="cosine", seed=20)
        vecs = _unit_vectors(30, 4, 20)
        for v in vecs:
            idx.insert(v)
        st = idx.stats()
        self.assertIn("size", st)
        self.assertIn("max_layer", st)
        self.assertIn("total_edges", st)


if __name__ == "__main__":
    unittest.main()
