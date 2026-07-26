import os
import tempfile
import unittest

from glean.index import InvertedIndex
from glean.tokenizer import porter_stem


class InvertedIndexTests(unittest.TestCase):
    def setUp(self):
        self.index = InvertedIndex()
        self.d1 = self.index.add_document("Cats", "The cat sat on the mat.")
        self.d2 = self.index.add_document("Dogs", "The dog sat on the log.")
        self.d3 = self.index.add_document("Empty", "")

    def test_doc_count(self):
        self.assertEqual(self.index.doc_count, 3)

    def test_title_is_searchable(self):
        cat_stem = porter_stem("cats")
        self.assertIn(self.d1, self.index.postings.get(cat_stem, {}))

    def test_postings_positions(self):
        sat_stem = porter_stem("sat")
        postings = self.index.postings[sat_stem]
        self.assertIn(self.d1, postings)
        self.assertIn(self.d2, postings)

    def test_empty_body_still_indexes_title(self):
        # title text is folded into the searchable content, so an empty body
        # still yields the title's tokens ("Empty" -> 1 token).
        self.assertEqual(self.index.documents[self.d3].length, 1)
        self.assertIn(porter_stem("empty"), self.index.postings)

    def test_avg_doc_length_nonzero(self):
        self.assertGreater(self.index.avg_doc_length, 0)

    def test_phrase_positions_true(self):
        stems = [porter_stem(w) for w in ["sat", "on", "the"]]
        self.assertTrue(self.index.phrase_positions(self.d1, stems))

    def test_phrase_positions_false_wrong_order(self):
        stems = [porter_stem(w) for w in ["the", "sat"]]
        self.assertFalse(self.index.phrase_positions(self.d1, stems))

    def test_phrase_positions_empty_stems(self):
        self.assertFalse(self.index.phrase_positions(self.d1, []))

    def test_phrase_positions_missing_doc(self):
        stems = [porter_stem("cat")]
        self.assertFalse(self.index.phrase_positions(999999, stems))

    def test_min_distance(self):
        cat_stem, mat_stem = porter_stem("cat"), porter_stem("mat")
        d = self.index.min_distance(self.d1, cat_stem, mat_stem)
        self.assertIsNotNone(d)
        self.assertGreater(d, 0)

    def test_min_distance_absent_term(self):
        d = self.index.min_distance(self.d1, porter_stem("cat"), "nonexistentterm")
        self.assertIsNone(d)

    def test_remove_document(self):
        cat_stem = porter_stem("cats")
        self.index.remove_document(self.d1)
        self.assertNotIn(self.d1, self.index.documents)
        self.assertNotIn(self.d1, self.index.postings.get(cat_stem, {}))

    def test_remove_missing_document_raises(self):
        with self.assertRaises(KeyError):
            self.index.remove_document(999999)

    def test_remove_last_reference_drops_term(self):
        unique_id = self.index.add_document("Unique", "zzyyxxqqword")
        term = porter_stem("zzyyxxqqword")
        self.assertIn(term, self.index.postings)
        self.index.remove_document(unique_id)
        self.assertNotIn(term, self.index.postings)


class PersistenceTests(unittest.TestCase):
    def test_round_trip(self):
        index = InvertedIndex()
        index.add_document("Cats", "The cat sat on the mat.", path="a.txt")
        index.add_document("Dogs", "The dog sat on the warm log by the sea.", path="b.txt")
        index.add_document("Unicode", "café naïve résumé", path="c.txt")

        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "test.idx")
            index.save(path)
            loaded = InvertedIndex.load(path)

            self.assertEqual(loaded.doc_count, index.doc_count)
            self.assertEqual(sorted(loaded.postings.keys()), sorted(index.postings.keys()))
            for term in index.postings:
                self.assertEqual(
                    {k: sorted(v) for k, v in loaded.postings[term].items()},
                    {k: sorted(v) for k, v in index.postings[term].items()},
                )
            for doc_id, doc in index.documents.items():
                loaded_doc = loaded.documents[doc_id]
                self.assertEqual(loaded_doc.title, doc.title)
                self.assertEqual(loaded_doc.path, doc.path)
                self.assertEqual(loaded_doc.text, doc.text)
                self.assertEqual(loaded_doc.tokens, doc.tokens)
                self.assertEqual(loaded_doc.spans, doc.spans)

    def test_load_rejects_foreign_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "bogus.idx")
            with open(path, "wb") as f:
                f.write(b"not a glean index")
            with self.assertRaises(Exception):
                InvertedIndex.load(path)

    def test_add_after_load_gets_fresh_doc_id(self):
        index = InvertedIndex()
        first = index.add_document("A", "alpha")
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "t.idx")
            index.save(path)
            loaded = InvertedIndex.load(path)
            second = loaded.add_document("B", "beta")
            self.assertNotEqual(first, second)
            self.assertEqual(loaded.doc_count, 2)


if __name__ == "__main__":
    unittest.main()
