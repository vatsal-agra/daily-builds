"""
Integration tests for the DB — end-to-end differential testing
against a dict oracle across thousands of operations.
"""

import os
import sys
import random
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from kvstore.db import DB, Options
from kvstore.batch import WriteBatch


def _db(tmpdir, **opts_kwargs):
    opts = Options(**opts_kwargs)
    return DB.open(tmpdir, opts)


class TestBasicOperations(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_put_and_get(self):
        db = _db(self.tmpdir)
        db.put(b"hello", b"world")
        self.assertEqual(db.get(b"hello"), b"world")
        db.close()

    def test_get_missing(self):
        db = _db(self.tmpdir)
        self.assertIsNone(db.get(b"nope"))
        db.close()

    def test_delete(self):
        db = _db(self.tmpdir)
        db.put(b"k", b"v")
        db.delete(b"k")
        self.assertIsNone(db.get(b"k"))
        db.close()

    def test_overwrite(self):
        db = _db(self.tmpdir)
        db.put(b"k", b"v1")
        db.put(b"k", b"v2")
        self.assertEqual(db.get(b"k"), b"v2")
        db.close()

    def test_scan_basic(self):
        db = _db(self.tmpdir)
        for i in range(10):
            db.put(f"key:{i:02d}".encode(), f"val:{i}".encode())
        pairs = list(db.scan(b"key:03", b"key:07"))
        self.assertEqual(len(pairs), 4)
        self.assertEqual(pairs[0], (b"key:03", b"val:3"))
        db.close()

    def test_scan_full(self):
        db = _db(self.tmpdir)
        for i in range(20):
            db.put(f"k{i:02d}".encode(), b"v")
        pairs = list(db.scan())
        self.assertEqual(len(pairs), 20)
        keys = [p[0] for p in pairs]
        self.assertEqual(keys, sorted(keys))
        db.close()

    def test_type_errors(self):
        db = _db(self.tmpdir)
        with self.assertRaises(TypeError):
            db.put("string_key", b"val")
        with self.assertRaises(TypeError):
            db.put(b"key", "string_val")
        with self.assertRaises(TypeError):
            db.get("string")
        db.close()


class TestPersistence(unittest.TestCase):
    """Test WAL recovery across DB open/close cycles."""

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_survives_reopen(self):
        db = _db(self.tmpdir)
        db.put(b"persistent", b"value")
        db.put(b"another", b"data")
        db.close()

        db2 = _db(self.tmpdir)
        self.assertEqual(db2.get(b"persistent"), b"value")
        self.assertEqual(db2.get(b"another"), b"data")
        db2.close()

    def test_delete_survives_reopen(self):
        db = _db(self.tmpdir)
        db.put(b"k", b"v")
        db.delete(b"k")
        db.close()

        db2 = _db(self.tmpdir)
        self.assertIsNone(db2.get(b"k"))
        db2.close()

    def test_wal_recovery_after_flush(self):
        """After flush (MemTable → SSTable), new WAL should be clean."""
        # Small memtable to force flushes
        db = _db(self.tmpdir, memtable_size=1024)
        for i in range(100):
            db.put(f"key:{i:04d}".encode(), b"x" * 50)
        db.close()

        db2 = _db(self.tmpdir, memtable_size=1024)
        for i in range(100):
            val = db2.get(f"key:{i:04d}".encode())
            self.assertIsNotNone(val, f"key:{i:04d} missing after reopen")
        db2.close()


class TestWriteBatch(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_batch_put(self):
        db = _db(self.tmpdir)
        batch = WriteBatch()
        batch.put(b"a", b"1").put(b"b", b"2").put(b"c", b"3")
        db.write_batch(batch)
        self.assertEqual(db.get(b"a"), b"1")
        self.assertEqual(db.get(b"b"), b"2")
        self.assertEqual(db.get(b"c"), b"3")
        db.close()

    def test_batch_delete(self):
        db = _db(self.tmpdir)
        db.put(b"x", b"to_delete")
        batch = WriteBatch()
        batch.delete(b"x").put(b"y", b"kept")
        db.write_batch(batch)
        self.assertIsNone(db.get(b"x"))
        self.assertEqual(db.get(b"y"), b"kept")
        db.close()

    def test_empty_batch(self):
        db = _db(self.tmpdir)
        db.write_batch(WriteBatch())  # should not error
        db.close()

    def test_batch_type_errors(self):
        batch = WriteBatch()
        with self.assertRaises(TypeError):
            batch.put("str", b"val")
        with self.assertRaises(TypeError):
            batch.delete("str")


class TestSnapshots(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_snapshot_sees_past(self):
        db = _db(self.tmpdir)
        db.put(b"k", b"old")
        snap = db.snapshot()
        db.put(b"k", b"new")
        # Snapshot should see 'old'
        self.assertEqual(db.get(b"k", snapshot=snap), b"old")
        self.assertEqual(db.get(b"k"), b"new")
        db.close()

    def test_snapshot_misses_future_writes(self):
        db = _db(self.tmpdir)
        snap = db.snapshot()
        db.put(b"newkey", b"value")
        # Snapshot was taken before newkey was written
        self.assertIsNone(db.get(b"newkey", snapshot=snap))
        db.close()

    def test_snapshot_misses_future_deletes(self):
        db = _db(self.tmpdir)
        db.put(b"k", b"v")
        snap = db.snapshot()
        db.delete(b"k")
        # At snapshot, key exists
        self.assertEqual(db.get(b"k", snapshot=snap), b"v")
        # Current: deleted
        self.assertIsNone(db.get(b"k"))
        db.close()


class TestCompaction(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_compaction_preserves_data(self):
        db = _db(self.tmpdir, memtable_size=512, auto_compact=False)
        expected = {}
        for i in range(500):
            k = f"key:{i:05d}".encode()
            v = f"val:{i}".encode()
            db.put(k, v)
            expected[k] = v
        # Delete some
        for i in range(0, 500, 3):
            k = f"key:{i:05d}".encode()
            db.delete(k)
            expected.pop(k, None)
        db.compact()
        for k, v in expected.items():
            self.assertEqual(db.get(k), v, f"Key {k!r} wrong after compaction")
        db.close()

    def test_tombstones_gc_at_deepest_level(self):
        """After full compaction, deleted keys should not reappear."""
        db = _db(self.tmpdir, memtable_size=512)
        for i in range(200):
            db.put(f"key:{i:04d}".encode(), b"v")
        for i in range(100):
            db.delete(f"key:{i:04d}".encode())
        db.compact()
        db.compact()
        for i in range(100):
            self.assertIsNone(db.get(f"key:{i:04d}".encode()))
        for i in range(100, 200):
            self.assertIsNotNone(db.get(f"key:{i:04d}".encode()))
        db.close()


class TestDifferentialOracle(unittest.TestCase):
    """
    Differential test: compare DB output against a Python dict oracle
    over thousands of random operations.
    """

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_1000_random_ops(self):
        rng = random.Random(0x1337CAFE)
        oracle: dict = {}
        db = _db(self.tmpdir, memtable_size=2048, auto_compact=True)

        keys = [f"key:{i:04d}".encode() for i in range(50)]

        for op_num in range(1000):
            key = rng.choice(keys)
            op = rng.choice(["put", "put", "put", "get", "del"])

            if op == "put":
                val = f"val:{op_num}".encode()
                db.put(key, val)
                oracle[key] = val
            elif op == "get":
                db_val = db.get(key)
                oracle_val = oracle.get(key)
                self.assertEqual(
                    db_val, oracle_val,
                    f"Op {op_num}: get({key!r}) = {db_val!r}, expected {oracle_val!r}"
                )
            elif op == "del":
                db.delete(key)
                oracle.pop(key, None)

        # Final scan: compare all present keys
        all_pairs = dict(db.scan())
        self.assertEqual(
            set(all_pairs.keys()), set(oracle.keys()),
            "Key sets differ between DB and oracle"
        )
        for k, v in oracle.items():
            self.assertEqual(
                all_pairs.get(k), v,
                f"Value mismatch for key {k!r}"
            )

        db.close()

    def test_5000_ops_with_flushes(self):
        """More operations with many MemTable flushes to stress L0→L1 compaction."""
        rng = random.Random(0xDEADBEEF)
        oracle: dict = {}
        db = _db(self.tmpdir, memtable_size=512, auto_compact=True)

        keys = [f"k:{i:03d}".encode() for i in range(30)]

        for op_num in range(5000):
            key = rng.choice(keys)
            r = rng.random()
            if r < 0.5:
                val = f"v:{op_num}:{rng.randint(0, 9999)}".encode()
                db.put(key, val)
                oracle[key] = val
            elif r < 0.7:
                db.delete(key)
                oracle.pop(key, None)
            else:
                db_val = db.get(key)
                oracle_val = oracle.get(key)
                self.assertEqual(
                    db_val, oracle_val,
                    f"Op {op_num}: get({key!r}) mismatch: got {db_val!r}, expected {oracle_val!r}"
                )

        # Full scan check
        all_db = dict(db.scan())
        self.assertEqual(set(all_db.keys()), set(oracle.keys()))
        for k in oracle:
            self.assertEqual(all_db[k], oracle[k])

        db.close()

    def test_batch_differential(self):
        """Test batches against oracle."""
        rng = random.Random(42)
        oracle: dict = {}
        db = _db(self.tmpdir)
        keys = [f"bk:{i}".encode() for i in range(20)]

        for _ in range(100):
            batch = WriteBatch()
            # Each batch: 5 random ops
            batch_ops = []
            for _ in range(5):
                k = rng.choice(keys)
                if rng.random() < 0.7:
                    v = f"v:{rng.randint(0, 999)}".encode()
                    batch.put(k, v)
                    batch_ops.append(("put", k, v))
                else:
                    batch.delete(k)
                    batch_ops.append(("del", k, None))
            db.write_batch(batch)
            for op_type, k, v in batch_ops:
                if op_type == "put":
                    oracle[k] = v
                else:
                    oracle.pop(k, None)

        for k in keys:
            self.assertEqual(db.get(k), oracle.get(k))
        db.close()


class TestInfo(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_info_keys(self):
        db = _db(self.tmpdir)
        info = db.info()
        self.assertIn("memtable_size", info)
        self.assertIn("memtable_entries", info)
        self.assertIn("next_seq", info)
        self.assertIn("levels", info)
        db.close()

    def test_info_after_writes(self):
        db = _db(self.tmpdir, memtable_size=512)
        for i in range(200):
            db.put(f"k{i}".encode(), b"v")
        info = db.info()
        self.assertGreater(info["next_seq"], 200)
        db.close()


if __name__ == "__main__":
    unittest.main()
