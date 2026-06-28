"""Tests for MergeIterator and DBIterator."""

import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from kvstore.iterator import MergeIterator, DBIterator
from kvstore.record import Record, RecordType


def make_recs(pairs, base_seq=0):
    """Create Records from (key, value) pairs."""
    return [
        Record(k.encode() if isinstance(k, str) else k,
               v.encode() if isinstance(v, str) else v,
               base_seq + i,
               RecordType.PUT)
        for i, (k, v) in enumerate(pairs)
    ]


def make_tombstone(key, seq):
    return Record(key.encode() if isinstance(key, str) else key,
                  b"", seq, RecordType.DELETE)


class TestMergeIterator(unittest.TestCase):

    def test_merge_two_disjoint(self):
        a = make_recs([("a", "1"), ("c", "3"), ("e", "5")])
        b = make_recs([("b", "2"), ("d", "4"), ("f", "6")])
        merged = list(MergeIterator([iter(a), iter(b)]))
        keys = [r.key for r in merged]
        self.assertEqual(keys, [b"a", b"b", b"c", b"d", b"e", b"f"])

    def test_merge_overlapping_dedup(self):
        """When same key appears in multiple sources, highest seq wins."""
        # Source 0 (higher priority): key=b, newer
        a = [Record(b"a", b"old_a", 1, RecordType.PUT),
             Record(b"b", b"new_b", 10, RecordType.PUT)]
        # Source 1: key=b, older
        b = [Record(b"b", b"old_b", 2, RecordType.PUT),
             Record(b"c", b"vc", 3, RecordType.PUT)]
        merged = list(MergeIterator([iter(a), iter(b)]))
        vals = {r.key: r.value for r in merged}
        self.assertEqual(vals[b"b"], b"new_b")
        self.assertEqual(len(merged), 3)

    def test_merge_empty(self):
        merged = list(MergeIterator([]))
        self.assertEqual(merged, [])

    def test_merge_single(self):
        recs = make_recs([("x", "1"), ("y", "2")])
        merged = list(MergeIterator([iter(recs)]))
        self.assertEqual(len(merged), 2)

    def test_merge_all_same_key(self):
        """Multiple sources with the same key: take highest seq."""
        a = [Record(b"key", b"v1", 5, RecordType.PUT)]
        b = [Record(b"key", b"v2", 10, RecordType.PUT)]
        c = [Record(b"key", b"v3", 3, RecordType.PUT)]
        merged = list(MergeIterator([iter(a), iter(b), iter(c)]))
        self.assertEqual(len(merged), 1)
        self.assertEqual(merged[0].value, b"v2")  # highest seq

    def test_tombstone_propagated(self):
        a = [Record(b"x", b"", 5, RecordType.DELETE)]
        merged = list(MergeIterator([iter(a)]))
        self.assertEqual(merged[0].rtype, RecordType.DELETE)


class TestDBIterator(unittest.TestCase):

    def test_filters_tombstones(self):
        recs = [
            Record(b"a", b"1", 1, RecordType.PUT),
            Record(b"b", b"", 2, RecordType.DELETE),
            Record(b"c", b"3", 3, RecordType.PUT),
        ]
        merge = MergeIterator([iter(recs)])
        it = DBIterator(merge)
        pairs = list(it)
        self.assertEqual(pairs, [(b"a", b"1"), (b"c", b"3")])

    def test_empty(self):
        it = DBIterator(MergeIterator([]))
        self.assertEqual(list(it), [])

    def test_all_tombstones(self):
        recs = [
            Record(b"a", b"", 1, RecordType.DELETE),
            Record(b"b", b"", 2, RecordType.DELETE),
        ]
        it = DBIterator(MergeIterator([iter(recs)]))
        self.assertEqual(list(it), [])


if __name__ == "__main__":
    unittest.main()
