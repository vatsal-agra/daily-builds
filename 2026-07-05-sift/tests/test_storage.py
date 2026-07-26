import os
import tempfile
import unittest

from sift.index import InvertedIndex
from sift.storage import save_index, load_index
from sift.query import search

DOCS = [
    ("a.txt", "Doc A", "the quick brown fox jumps over the lazy dog"),
    ("b.txt", "Doc B", "a quick fox is not a lazy dog it runs fast"),
    ("c.txt", "Doc C", "cooking recipes for baking bread and cakes"),
    ("d.txt", "Doc D", "quantum mechanics describes particles as waves"),
]


class TestStorageRoundTrip(unittest.TestCase):
    def setUp(self):
        self.index = InvertedIndex()
        for path, title, text in DOCS:
            self.index.add_document(path, title, text)
        self.tmpdir = tempfile.TemporaryDirectory()
        self.index_path = os.path.join(self.tmpdir.name, "test.sift")

    def tearDown(self):
        self.tmpdir.cleanup()

    def test_roundtrip_preserves_vocabulary(self):
        save_index(self.index, self.index_path)
        loaded = load_index(self.index_path)
        self.assertEqual(loaded.vocabulary(), self.index.vocabulary())

    def test_roundtrip_preserves_doc_metadata(self):
        save_index(self.index, self.index_path)
        loaded = load_index(self.index_path)
        for doc_id, doc in self.index.documents.items():
            loaded_doc = loaded.documents[doc_id]
            self.assertEqual(loaded_doc.path, doc.path)
            self.assertEqual(loaded_doc.title, doc.title)
            self.assertEqual(loaded_doc.length, doc.length)

    def test_roundtrip_preserves_postings_exactly(self):
        save_index(self.index, self.index_path)
        loaded = load_index(self.index_path)
        for term in self.index.vocabulary():
            original_bucket = self.index.postings[term]
            loaded_bucket = loaded.postings[term]
            self.assertEqual(set(original_bucket.keys()), set(loaded_bucket.keys()))
            for doc_id, posting in original_bucket.items():
                loaded_posting = loaded_bucket[doc_id]
                self.assertEqual(loaded_posting.tf, posting.tf)
                self.assertEqual(loaded_posting.positions, posting.positions)

    def test_roundtrip_preserves_query_results(self):
        save_index(self.index, self.index_path)
        loaded = load_index(self.index_path)
        for q in ["fox", "fox AND dog", '"quick fox"', "bread OR quantum", "fox NOT dog"]:
            self.assertEqual(search(self.index, q), search(loaded, q))

    def test_bad_magic_raises(self):
        with open(self.index_path, "wb") as fh:
            fh.write(b"NOTASIFTFILE")
        with self.assertRaises(ValueError):
            load_index(self.index_path)

    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            load_index(os.path.join(self.tmpdir.name, "does_not_exist.sift"))

    def test_empty_index_roundtrip(self):
        empty = InvertedIndex()
        path = os.path.join(self.tmpdir.name, "empty.sift")
        save_index(empty, path)
        loaded = load_index(path)
        self.assertEqual(loaded.doc_count, 0)
        self.assertEqual(loaded.vocabulary(), [])


if __name__ == "__main__":
    unittest.main()
