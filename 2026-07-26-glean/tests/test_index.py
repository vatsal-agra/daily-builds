import os
import shutil
import sys
import tempfile
import time
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from glean.crawler import crawl
from glean.index import Index, IndexWriter, _read_varint, _write_varint


class TestVarint(unittest.TestCase):
    def _roundtrip(self, n):
        buf = bytearray()
        _write_varint(buf, n)
        value, offset = _read_varint(bytes(buf), 0)
        self.assertEqual(value, n)
        self.assertEqual(offset, len(buf))

    def test_small_values(self):
        for n in [0, 1, 2, 127]:
            self._roundtrip(n)

    def test_multi_byte_values(self):
        for n in [128, 300, 16384, 2 ** 20, 2 ** 32]:
            self._roundtrip(n)

    def test_rejects_negative(self):
        with self.assertRaises(ValueError):
            _write_varint(bytearray(), -1)

    def test_sequential_read(self):
        buf = bytearray()
        for n in [5, 300, 0, 127, 128]:
            _write_varint(buf, n)
        buf = bytes(buf)
        offset = 0
        values = []
        for _ in range(5):
            v, offset = _read_varint(buf, offset)
            values.append(v)
        self.assertEqual(values, [5, 300, 0, 127, 128])


class TestIndexBuildAndLoad(unittest.TestCase):
    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="glean_test_index_")
        self.index_dir = os.path.join(self.root, ".glean")

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def _write(self, name, content):
        with open(os.path.join(self.root, name), "w", encoding="utf-8") as f:
            f.write(content)

    def _build(self, extensions=(".md", ".txt")):
        writer = IndexWriter(self.root, index_dir=self.index_dir, extensions=extensions)
        return writer.build(crawl(self.root, extensions))

    def test_build_and_load_basic(self):
        self._write("a.md", "# Raft\nRaft consensus algorithm with leader election.")
        self._write("b.md", "# Chess\nA chess engine with alpha beta search.")
        stats = self._build()
        self.assertEqual(stats["total"], 2)
        self.assertEqual(stats["reanalyzed"], 2)
        self.assertEqual(stats["reused"], 0)

        index = Index(self.index_dir)
        self.assertEqual(index.doc_count, 2)
        self.assertGreater(len(index.vocabulary()), 0)
        self.assertIn("raft", index.terms)
        self.assertEqual(index.document_frequency("raft"), 1)
        postings = index.postings("raft")
        self.assertEqual(len(postings), 1)
        doc_id, tf, positions = postings[0]
        self.assertEqual(tf, 2)  # "Raft" appears twice
        self.assertEqual(index.doc(doc_id)["path"], "a.md")

    def test_missing_index_raises(self):
        with self.assertRaises(FileNotFoundError):
            Index(os.path.join(self.root, "nonexistent"))

    def test_empty_corpus(self):
        stats = self._build()
        self.assertEqual(stats["total"], 0)
        index = Index(self.index_dir)
        self.assertEqual(index.doc_count, 0)
        self.assertEqual(index.avg_doc_length, 0.0)
        self.assertEqual(index.postings("anything"), [])

    def test_incremental_reindex_reuses_unchanged_files(self):
        self._write("a.md", "content one")
        self._write("b.md", "content two")
        self._build()

        stats = self._build()  # nothing changed
        self.assertEqual(stats["reanalyzed"], 0)
        self.assertEqual(stats["reused"], 2)

    def test_incremental_reindex_reanalyzes_changed_file(self):
        self._write("a.md", "content one")
        self._write("b.md", "content two")
        self._build()

        time.sleep(1.05)  # ensure mtime resolution ticks over
        self._write("a.md", "content one CHANGED with new words")
        stats = self._build()
        self.assertEqual(stats["reanalyzed"], 1)
        self.assertEqual(stats["reused"], 1)

        index = Index(self.index_dir)
        results = index.postings("chang")  # stem of "CHANGED"
        self.assertEqual(len(results), 1)

    def test_incremental_reindex_drops_removed_file(self):
        self._write("a.md", "alpha content")
        self._write("b.md", "beta content")
        self._build()

        os.remove(os.path.join(self.root, "b.md"))
        stats = self._build()
        self.assertEqual(stats["removed"], 1)
        self.assertEqual(stats["total"], 1)

        index = Index(self.index_dir)
        self.assertEqual(index.doc_count, 1)
        for doc_id, _tf, _pos in index.postings("beta"):
            self.fail("removed document's terms should not remain in the index")

    def test_title_extracted_from_markdown_heading(self):
        self._write("a.md", "# My Great Title\nsome body text")
        self._build()
        index = Index(self.index_dir)
        self.assertEqual(index.doc(0)["title"], "My Great Title")

    def test_title_falls_back_to_first_line(self):
        self._write("a.md", "Just a plain first line\nmore text")
        self._build()
        index = Index(self.index_dir)
        self.assertEqual(index.doc(0)["title"], "Just a plain first line")


if __name__ == "__main__":
    unittest.main()
