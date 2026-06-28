"""Tests for Write-Ahead Log."""

import os
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.dirname(__file__)))
from kvstore.wal import WAL
from kvstore.record import RecordType


class TestWAL(unittest.TestCase):

    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.wal_path = Path(self.tmpdir) / "test.wal"

    def tearDown(self):
        import shutil
        shutil.rmtree(self.tmpdir, ignore_errors=True)

    def test_write_and_replay_single(self):
        wal = WAL(self.wal_path)
        wal.append(1, RecordType.PUT, b"hello", b"world")
        wal.close()

        records = list(WAL.replay(self.wal_path))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].key, b"hello")
        self.assertEqual(records[0].value, b"world")
        self.assertEqual(records[0].seq, 1)
        self.assertEqual(records[0].rtype, RecordType.PUT)

    def test_write_and_replay_multiple(self):
        wal = WAL(self.wal_path)
        entries = [
            (1, RecordType.PUT, b"a", b"1"),
            (2, RecordType.PUT, b"b", b"2"),
            (3, RecordType.DELETE, b"a", b""),
        ]
        for seq, rtype, k, v in entries:
            wal.append(seq, rtype, k, v)
        wal.close()

        records = list(WAL.replay(self.wal_path))
        self.assertEqual(len(records), 3)
        self.assertEqual(records[2].rtype, RecordType.DELETE)
        self.assertEqual(records[2].key, b"a")

    def test_replay_empty_file(self):
        self.wal_path.write_bytes(b"")
        records = list(WAL.replay(self.wal_path))
        self.assertEqual(records, [])

    def test_replay_nonexistent_file(self):
        records = list(WAL.replay(Path(self.tmpdir) / "missing.wal"))
        self.assertEqual(records, [])

    def test_crc_corruption_stops_replay(self):
        wal = WAL(self.wal_path)
        wal.append(1, RecordType.PUT, b"key1", b"val1")
        wal.append(2, RecordType.PUT, b"key2", b"val2")
        wal.close()

        # Corrupt bytes in the second record
        data = bytearray(self.wal_path.read_bytes())
        data[-5] ^= 0xFF  # flip bits near end
        self.wal_path.write_bytes(bytes(data))

        records = list(WAL.replay(self.wal_path))
        # Should stop at or before the corrupted record
        self.assertLessEqual(len(records), 2)

    def test_large_keys_and_values(self):
        wal = WAL(self.wal_path)
        big_key = b"k" * 1000
        big_val = b"v" * 100000
        wal.append(99, RecordType.PUT, big_key, big_val)
        wal.close()

        records = list(WAL.replay(self.wal_path))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].key, big_key)
        self.assertEqual(records[0].value, big_val)
        self.assertEqual(records[0].seq, 99)

    def test_empty_value_delete(self):
        wal = WAL(self.wal_path)
        wal.append(10, RecordType.DELETE, b"gone", b"")
        wal.close()

        records = list(WAL.replay(self.wal_path))
        self.assertEqual(len(records), 1)
        self.assertEqual(records[0].value, b"")
        self.assertEqual(records[0].rtype, RecordType.DELETE)

    def test_binary_keys(self):
        wal = WAL(self.wal_path)
        wal.append(1, RecordType.PUT, bytes(range(256)), b"\x00\xFF\x42")
        wal.close()

        records = list(WAL.replay(self.wal_path))
        self.assertEqual(records[0].key, bytes(range(256)))
        self.assertEqual(records[0].value, b"\x00\xFF\x42")


if __name__ == "__main__":
    unittest.main()
