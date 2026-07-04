"""Tests for Collection (persistence, metadata, JSONL bulk-insert)."""
import json
import os
import tempfile
import unittest
import numpy as np
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))

from vecnn.collection import Collection


def _unit_vectors(n, dim, seed=0):
    rng = np.random.default_rng(seed)
    v = rng.standard_normal((n, dim))
    v /= np.linalg.norm(v, axis=1, keepdims=True)
    return v


class TestCollectionBasic(unittest.TestCase):

    def test_create_and_add(self):
        coll = Collection("test", dim=8, metric="cosine")
        v = np.array([1.0] + [0.0] * 7)
        nid = coll.add(v)
        self.assertEqual(coll.size, 1)
        results = coll.search(v, k=1)
        self.assertEqual(results[0][0], nid)

    def test_add_batch(self):
        coll = Collection("batch", dim=4)
        vecs = _unit_vectors(10, 4)
        ids = coll.add_batch(vecs)
        self.assertEqual(len(ids), 10)
        self.assertEqual(coll.size, 10)

    def test_metadata_filter(self):
        coll = Collection("filtered", dim=8, metric="cosine",
                          index_params={"M": 4, "ef_construction": 50})
        vecs = _unit_vectors(50, 8)
        for i, v in enumerate(vecs):
            coll.add(v, metadata={"group": "even" if i % 2 == 0 else "odd"})
        q = vecs[0]
        results = coll.search(q, k=10, filter_expr={"group": "even"})
        for _, _, meta in results:
            self.assertEqual(meta["group"], "even")

    def test_lsh_collection(self):
        coll = Collection("lsh_test", dim=8, index_type="lsh",
                          index_params={"n_tables": 8, "n_bits": 8})
        vecs = _unit_vectors(30, 8, seed=5)
        coll.add_batch(vecs)
        self.assertEqual(coll.size, 30)
        results = coll.search(vecs[0], k=5)
        self.assertGreater(len(results), 0)

    def test_invalid_index_type(self):
        with self.assertRaises(ValueError):
            Collection("bad", dim=4, index_type="kdtree")


class TestCollectionPersistence(unittest.TestCase):

    def _build_and_save(self, tmpdir, name="my_coll", n=40, dim=16, seed=30):
        coll = Collection(name, dim=dim, metric="cosine",
                          index_params={"M": 8, "ef_construction": 100})
        vecs = _unit_vectors(n, dim, seed)
        for i, v in enumerate(vecs):
            coll.add(v, metadata={"i": i})
        path = os.path.join(tmpdir, f"{name}.json")
        coll.save(path)
        return coll, path, vecs

    def test_save_load_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig, path, vecs = self._build_and_save(tmpdir)
            loaded = Collection.load(path)
            self.assertEqual(loaded.size, orig.size)
            self.assertEqual(loaded.name, orig.name)
            self.assertEqual(loaded.metric, orig.metric)
            q = vecs[0]
            r1 = [x[0] for x in orig.search(q, k=5)]
            r2 = [x[0] for x in loaded.search(q, k=5)]
            self.assertEqual(r1, r2)

    def test_file_is_valid_json(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            _, path, _ = self._build_and_save(tmpdir, n=10)
            with open(path) as f:
                d = json.load(f)
            self.assertEqual(d["version"], 1)
            self.assertIn("index", d)

    def test_load_nonexistent_raises(self):
        with self.assertRaises(FileNotFoundError):
            Collection.load("/nonexistent/path.json")

    def test_delete_persists_through_save_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            orig, path, vecs = self._build_and_save(tmpdir, n=20, seed=31)
            ids = orig.all_ids()
            orig.delete(ids[0])
            orig.save(path)
            loaded = Collection.load(path)
            self.assertEqual(loaded.size, 19)
            self.assertNotIn(ids[0], loaded.all_ids())


class TestCollectionJSONL(unittest.TestCase):

    def _write_jsonl(self, path, records):
        with open(path, "w") as f:
            for r in records:
                f.write(json.dumps(r) + "\n")

    def test_jsonl_insert(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coll = Collection("jl", dim=4)
            vecs = _unit_vectors(5, 4, seed=40)
            records = [{"vector": v.tolist(), "metadata": {"label": str(i)}}
                       for i, v in enumerate(vecs)]
            jl_path = os.path.join(tmpdir, "data.jsonl")
            self._write_jsonl(jl_path, records)
            count = coll.add_from_jsonl(jl_path)
            self.assertEqual(count, 5)
            self.assertEqual(coll.size, 5)

    def test_jsonl_with_explicit_ids(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coll = Collection("jl2", dim=4)
            vecs = _unit_vectors(3, 4, seed=41)
            records = [{"id": i * 10, "vector": v.tolist()} for i, v in enumerate(vecs)]
            jl_path = os.path.join(tmpdir, "ids.jsonl")
            self._write_jsonl(jl_path, records)
            coll.add_from_jsonl(jl_path)
            ids = coll.all_ids()
            self.assertIn(0, ids)
            self.assertIn(10, ids)
            self.assertIn(20, ids)

    def test_jsonl_missing_vector_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coll = Collection("jl3", dim=4)
            jl_path = os.path.join(tmpdir, "bad.jsonl")
            with open(jl_path, "w") as f:
                f.write('{"metadata": {"x": 1}}\n')
            with self.assertRaises(ValueError):
                coll.add_from_jsonl(jl_path)

    def test_jsonl_invalid_json_raises(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coll = Collection("jl4", dim=4)
            jl_path = os.path.join(tmpdir, "bad.jsonl")
            with open(jl_path, "w") as f:
                f.write("not json\n")
            with self.assertRaises(ValueError):
                coll.add_from_jsonl(jl_path)

    def test_jsonl_skips_blank_lines(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            coll = Collection("jl5", dim=4)
            vecs = _unit_vectors(3, 4, seed=42)
            jl_path = os.path.join(tmpdir, "blank.jsonl")
            with open(jl_path, "w") as f:
                for v in vecs:
                    f.write(json.dumps({"vector": v.tolist()}) + "\n")
                    f.write("\n")  # blank line
            count = coll.add_from_jsonl(jl_path)
            self.assertEqual(count, 3)


if __name__ == "__main__":
    unittest.main()
