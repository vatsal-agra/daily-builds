import os
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trove.index import InvertedIndex, build_index, split_markdown_sections

FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures")


class TestInvertedIndex(unittest.TestCase):
    def test_add_document_and_lookup(self):
        idx = InvertedIndex()
        idx.add_document("a", "cats and dogs")
        idx.finalize()
        self.assertEqual(idx.N, 1)
        self.assertIn("cat", idx.postings)
        self.assertEqual(idx.doc_freq("cat"), 1)

    def test_duplicate_doc_id_rejected(self):
        idx = InvertedIndex()
        idx.add_document("a", "hello")
        with self.assertRaises(ValueError):
            idx.add_document("a", "hello again")

    def test_finalize_computes_avg_doc_length(self):
        idx = InvertedIndex()
        idx.add_document("a", "one two three four")   # 4 content terms
        idx.add_document("b", "five six")              # 2 content terms
        idx.finalize()
        self.assertAlmostEqual(idx.avg_doc_length, 3.0)

    def test_save_and_load_round_trip(self):
        idx = InvertedIndex()
        idx.add_document("a", "the quick brown fox", path="a.txt", title="Doc A")
        idx.finalize()
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "sub", "index.json")
            idx.save(path)
            self.assertTrue(os.path.exists(path))
            loaded = InvertedIndex.load(path)
        self.assertEqual(loaded.N, idx.N)
        self.assertEqual(loaded.postings, idx.postings)
        self.assertEqual(loaded.doc_meta["a"]["title"], "Doc A")
        self.assertEqual(loaded.term_surface, idx.term_surface)


class TestMarkdownSectionSplitting(unittest.TestCase):
    def test_splits_on_h2_headers(self):
        text = "# Title\nintro\n## First\nbody1\n## Second\nbody2\n"
        sections = split_markdown_sections(text)
        titles = [t for t, _ in sections]
        self.assertIn("First", titles)
        self.assertIn("Second", titles)

    def test_no_headers_returns_single_section(self):
        text = "# Just A Title\njust some body text with no h2 headers\n"
        sections = split_markdown_sections(text)
        self.assertEqual(len(sections), 1)
        self.assertEqual(sections[0][0], "Just A Title")


class TestBuildIndexGenericOverAnyDirectory(unittest.TestCase):
    """Proves the engine is not hardcoded to the daily-builds corpus by
    building a real index over an entirely independent fixture corpus
    (a recipe book, markdown, different domain and vocabulary) and
    confirming ordinary indexing/search invariants hold."""

    def test_indexes_independent_second_corpus(self):
        idx = build_index(os.path.join(FIXTURES, "corpus_b"))
        self.assertGreater(idx.N, 1)  # recipes.md splits into multiple sections
        self.assertIn("bake", idx.postings)  # "baking"/"bake"/"baked" all stem here
        self.assertIn("chicken", idx.postings)
        self.assertNotIn("software", idx.postings)  # confirms no cross-corpus leakage

    def test_indexes_txt_and_md_fixture_corpus_a(self):
        idx = build_index(os.path.join(FIXTURES, "corpus_a"))
        self.assertEqual(idx.N, 4)
        self.assertIn("fox", idx.postings)
        self.assertIn("quantum", idx.postings)

    def test_empty_directory_yields_empty_index(self):
        with tempfile.TemporaryDirectory() as d:
            idx = build_index(d)
        self.assertEqual(idx.N, 0)


if __name__ == "__main__":
    unittest.main()
