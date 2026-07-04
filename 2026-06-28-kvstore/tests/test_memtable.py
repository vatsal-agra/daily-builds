"""Tests for MemTable."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from kvstore.memtable import MemTable
from kvstore.record import RecordType


class TestMemTable(unittest.TestCase):

    def _mt(self, size_limit=1024 * 1024):
        return MemTable(size_limit)

    def test_put_and_get(self):
        mt = self._mt()
        mt.put(b"hello", b"world", 1)
        result = mt.get(b"hello")
        self.assertIsNotNone(result)
        val, rtype = result
        self.assertEqual(val, b"world")
        self.assertEqual(rtype, RecordType.PUT)

    def test_get_missing(self):
        mt = self._mt()
        self.assertIsNone(mt.get(b"missing"))

    def test_overwrite(self):
        mt = self._mt()
        mt.put(b"k", b"v1", 1)
        mt.put(b"k", b"v2", 2)
        val, rtype = mt.get(b"k")
        self.assertEqual(val, b"v2")

    def test_delete(self):
        mt = self._mt()
        mt.put(b"k", b"v", 1)
        mt.delete(b"k", 2)
        val, rtype = mt.get(b"k")
        self.assertEqual(rtype, RecordType.DELETE)

    def test_scan_sorted(self):
        mt = self._mt()
        keys = [b"c", b"a", b"e", b"b", b"d"]
        for i, k in enumerate(keys):
            mt.put(k, b"v" + k, i + 1)
        records = list(mt.iter_all())
        self.assertEqual([r.key for r in records], sorted(keys))

    def test_scan_range(self):
        mt = self._mt()
        for i in range(10):
            mt.put(f"key:{i:02d}".encode(), b"v", i)
        # [key:03, key:07)
        records = list(mt.scan(b"key:03", b"key:07"))
        keys = [r.key for r in records]
        self.assertEqual(keys, [f"key:{i:02d}".encode() for i in range(3, 7)])

    def test_scan_no_start(self):
        mt = self._mt()
        for i in range(5):
            mt.put(f"k{i}".encode(), b"v", i)
        records = list(mt.scan(end=b"k3"))
        self.assertEqual(len(records), 3)

    def test_snapshot_isolation(self):
        mt = self._mt()
        mt.put(b"k", b"old", 5)
        mt.put(b"k", b"new", 10)
        # MemTable is multi-version: at max_seq=7, see "old" (seq=5)
        result = mt.get(b"k", max_seq=7)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], b"old")
        # At max_seq=4, neither version is visible
        result = mt.get(b"k", max_seq=4)
        self.assertIsNone(result)
        # At max_seq=10, see "new" (highest seq <= 10)
        result = mt.get(b"k", max_seq=10)
        self.assertIsNotNone(result)
        self.assertEqual(result[0], b"new")

    def test_size_tracking(self):
        mt = MemTable(size_limit=100)
        self.assertFalse(mt.is_full())
        # Write enough to exceed limit
        for i in range(100):
            mt.put(f"key:{i:03d}".encode(), b"x" * 20, i)
        self.assertTrue(mt.is_full())

    def test_tombstone_in_scan(self):
        mt = self._mt()
        mt.put(b"a", b"1", 1)
        mt.put(b"b", b"2", 2)
        mt.delete(b"a", 3)
        records = list(mt.iter_all())
        # Both keys present; 'a' has DELETE type
        types = {r.key: r.rtype for r in records}
        self.assertEqual(types[b"a"], RecordType.DELETE)
        self.assertEqual(types[b"b"], RecordType.PUT)

    def test_len(self):
        mt = self._mt()
        self.assertEqual(len(mt), 0)
        mt.put(b"a", b"1", 1)
        mt.put(b"b", b"2", 2)
        self.assertEqual(len(mt), 2)
        mt.put(b"a", b"3", 3)  # overwrite — same key
        self.assertEqual(len(mt), 2)


if __name__ == "__main__":
    unittest.main()
