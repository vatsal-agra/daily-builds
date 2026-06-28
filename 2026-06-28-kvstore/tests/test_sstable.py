"""Tests for SSTable writer and reader."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from kvstore.sstable import SSTableWriter2, SSTableReader, BLOCK_SIZE
from kvstore.record import Record, RecordType


def make_records(n, prefix="key", val_prefix="val", include_tombstone=False):
    records = []
    for i in range(n):
        k = f"{prefix}:{i:06d}".encode()
        if include_tombstone and i % 10 == 5:
            records.append(Record(k, b"", i, RecordType.DELETE))
        else:
            records.append(Record(k, f"{val_prefix}:{i}".encode(), i, RecordType.PUT))
    return records


class TestSSTable(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def _write(self, records, fname="test.sst"):
        path = Path(self.tmpdir) / fname
        writer = SSTableWriter2(path)
        for r in records:
            writer.add(r)
        writer.finish()
        return path

    def test_roundtrip_small(self):
        records = make_records(10)
        path = self._write(records)
        reader = SSTableReader(path)
        all_records = list(reader.iter_all())
        self.assertEqual(len(all_records), 10)
        for orig, read in zip(records, all_records):
            self.assertEqual(read.key, orig.key)
            self.assertEqual(read.value, orig.value)
        reader.close()

    def test_point_lookup_hit(self):
        records = make_records(100)
        path = self._write(records)
        reader = SSTableReader(path)
        for i in range(0, 100, 10):
            key = f"key:{i:06d}".encode()
            result = reader.get(key)
            self.assertIsNotNone(result, f"Key {key!r} not found")
            val, rtype = result
            self.assertEqual(val, f"val:{i}".encode())
            self.assertEqual(rtype, RecordType.PUT)
        reader.close()

    def test_point_lookup_miss(self):
        records = make_records(50)
        path = self._write(records)
        reader = SSTableReader(path)
        result = reader.get(b"key:999999")
        self.assertIsNone(result)
        reader.close()

    def test_bloom_filter_skips_misses(self):
        """Bloom filter should return False for keys definitely not present."""
        records = make_records(200)
        path = self._write(records)
        reader = SSTableReader(path)
        # These keys are definitely not in the SSTable
        false_positives = 0
        for i in range(10000, 11000):
            result = reader.get(f"absent:{i:06d}".encode())
            if result is not None:
                false_positives += 1
        # With Bloom filter, very few FP expected
        self.assertLess(false_positives, 50)
        reader.close()

    def test_scan_range(self):
        records = make_records(200)
        path = self._write(records)
        reader = SSTableReader(path)
        results = list(reader.scan(b"key:000050", b"key:000060"))
        self.assertEqual(len(results), 10)
        self.assertEqual(results[0].key, b"key:000050")
        self.assertEqual(results[-1].key, b"key:000059")
        reader.close()

    def test_scan_no_bounds(self):
        records = make_records(30)
        path = self._write(records)
        reader = SSTableReader(path)
        results = list(reader.scan())
        self.assertEqual(len(results), 30)
        reader.close()

    def test_tombstones_preserved(self):
        records = make_records(20, include_tombstone=True)
        path = self._write(records)
        reader = SSTableReader(path)
        all_recs = list(reader.iter_all())
        tombstones = [r for r in all_recs if r.rtype == RecordType.DELETE]
        # Records at positions 5, 15 have tombstones
        self.assertGreater(len(tombstones), 0)
        reader.close()

    def test_min_max_keys(self):
        records = make_records(50)
        path = self._write(records)
        reader = SSTableReader(path)
        self.assertEqual(reader.min_key, b"key:000000")
        self.assertEqual(reader.max_key, b"key:000049")
        reader.close()

    def test_multi_block(self):
        """Ensure keys spanning multiple blocks are all retrievable."""
        # Create enough records to span multiple 4KB blocks
        records = make_records(2000)
        path = self._write(records)
        reader = SSTableReader(path)
        self.assertGreater(len(reader._index), 1, "Should have multiple blocks")
        # Check random samples
        import random
        rng = random.Random(42)
        sample = rng.sample(records, 50)
        for r in sample:
            result = reader.get(r.key)
            self.assertIsNotNone(result)
            self.assertEqual(result[0], r.value)
        reader.close()

    def test_empty_sstable(self):
        path = self._write([])
        reader = SSTableReader(path)
        self.assertIsNone(reader.min_key)
        self.assertIsNone(reader.max_key)
        self.assertEqual(list(reader.iter_all()), [])
        reader.close()

    def test_binary_keys(self):
        records = [
            Record(bytes([i, i + 1]), bytes([i * 2]), i, RecordType.PUT)
            for i in range(10)
        ]
        records.sort(key=lambda r: r.key)
        path = self._write(records)
        reader = SSTableReader(path)
        result = reader.get(bytes([5, 6]))
        self.assertIsNotNone(result)
        self.assertEqual(result[0], bytes([10]))
        reader.close()

    def test_overlaps(self):
        records = make_records(100)
        path = self._write(records)
        reader = SSTableReader(path)
        self.assertTrue(reader.overlaps(b"key:000010", b"key:000020"))
        self.assertFalse(reader.overlaps(b"zzz", b"zzz"))
        reader.close()


if __name__ == "__main__":
    unittest.main()
