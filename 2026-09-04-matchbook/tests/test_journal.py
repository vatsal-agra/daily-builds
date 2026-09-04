import os
import tempfile
import unittest

from matchbook.journal import Journal, JournalCorruption


class TestJournal(unittest.TestCase):
    def setUp(self):
        self.tmpdir = tempfile.mkdtemp()
        self.path = os.path.join(self.tmpdir, "test.journal")

    def test_append_and_read_all_round_trips(self):
        j = Journal(self.path, truncate=True)
        events = [{"cmd": "SUBMIT", "order_id": i} for i in range(5)]
        for e in events:
            j.append(e)
        j.close()
        read_back = Journal.read_all(self.path)
        self.assertEqual(read_back, events)

    def test_reopen_appends_without_truncating(self):
        j = Journal(self.path, truncate=True)
        j.append({"a": 1})
        j.close()
        j2 = Journal(self.path, truncate=False)
        j2.append({"a": 2})
        j2.close()
        events = Journal.read_all(self.path)
        self.assertEqual(events, [{"a": 1}, {"a": 2}])

    def test_truncate_true_clears_existing_content(self):
        j = Journal(self.path, truncate=True)
        j.append({"a": 1})
        j.close()
        j2 = Journal(self.path, truncate=True)
        j2.append({"a": 2})
        j2.close()
        self.assertEqual(Journal.read_all(self.path), [{"a": 2}])

    def test_missing_file_reads_as_empty(self):
        self.assertEqual(Journal.read_all(os.path.join(self.tmpdir, "nope.journal")), [])

    def test_torn_final_write_is_dropped_in_strict_mode(self):
        j = Journal(self.path, truncate=True)
        j.append({"cmd": "SUBMIT", "order_id": 1})
        j.append({"cmd": "SUBMIT", "order_id": 2})
        j.close()
        # Simulate a crash mid-write: truncate the last line's payload.
        with open(self.path, "r+", encoding="utf-8") as fh:
            content = fh.read()
        torn = content[: len(content) - 10]  # chop off the tail of the last line
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(torn)
        events = Journal.read_all(self.path, strict=True)
        self.assertEqual(events, [{"cmd": "SUBMIT", "order_id": 1}])

    def test_corruption_raises_in_non_strict_mode(self):
        j = Journal(self.path, truncate=True)
        j.append({"cmd": "SUBMIT", "order_id": 1})
        j.close()
        with open(self.path, "r", encoding="utf-8") as fh:
            content = fh.read()
        # Flip a byte in the payload without touching the CRC prefix.
        corrupted = content.replace('"order_id":1', '"order_id":9')
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write(corrupted)
        with self.assertRaises(JournalCorruption):
            Journal.read_all(self.path, strict=False)

    def test_blank_lines_are_skipped(self):
        with open(self.path, "w", encoding="utf-8") as fh:
            fh.write("\n\n")
        self.assertEqual(Journal.read_all(self.path), [])


if __name__ == "__main__":
    unittest.main()
