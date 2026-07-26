import unittest

from glean.index import InvertedIndex
from glean.rank import BM25, TfIdfCosine, build_snippet, snippet_to_html, snippet_to_text
from glean.tokenizer import porter_stem


class BM25Tests(unittest.TestCase):
    def setUp(self):
        self.index = InvertedIndex()
        self.with_term = self.index.add_document("A", "python is a great programming language for scripting")
        self.without_term = self.index.add_document("B", "javascript runs in every web browser today")
        self.bm25 = BM25(self.index)

    def test_matching_doc_scores_positive(self):
        term = porter_stem("python")
        score = self.bm25.score(self.with_term, [term])
        self.assertGreater(score, 0.0)

    def test_nonmatching_doc_scores_zero(self):
        term = porter_stem("python")
        score = self.bm25.score(self.without_term, [term])
        self.assertEqual(score, 0.0)

    def test_missing_document_scores_zero(self):
        self.assertEqual(self.bm25.score(999999, ["anything"]), 0.0)

    def test_unknown_term_scores_zero(self):
        score = self.bm25.score(self.with_term, ["zzznoexist"])
        self.assertEqual(score, 0.0)

    def test_idf_nonnegative(self):
        # The BM25+1 IDF variant used here should never go negative, even for
        # a term that appears in every document.
        idx = InvertedIndex()
        idx.add_document("A", "shared shared shared")
        idx.add_document("B", "shared shared")
        bm25 = BM25(idx)
        self.assertGreaterEqual(bm25.idf(porter_stem("shared")), 0.0)

    def test_term_frequency_saturates(self):
        idx = InvertedIndex()
        few = idx.add_document("Few", "cat " * 2 + "filler " * 20)
        many = idx.add_document("Many", "cat " * 100 + "filler " * 20)
        bm25 = BM25(idx)
        term = porter_stem("cat")
        score_few = bm25.score(few, [term])
        score_many = bm25.score(many, [term])
        self.assertGreater(score_many, score_few)
        # 50x the term frequency should not translate to anywhere near 50x score.
        self.assertLess(score_many, score_few * 10)

    def test_length_normalization_penalizes_long_documents(self):
        idx = InvertedIndex()
        short_doc = idx.add_document("Short", "keyword appears once here")
        long_doc = idx.add_document("Long", "keyword appears once here " + "padding word filler " * 50)
        bm25 = BM25(idx)
        term = porter_stem("keyword")
        self.assertGreater(bm25.score(short_doc, [term]), bm25.score(long_doc, [term]))

    def test_rank_orders_by_score_descending(self):
        idx = InvertedIndex()
        low = idx.add_document("Low", "cat mentioned once amid filler filler filler filler")
        high = idx.add_document("High", "cat cat cat cat")
        bm25 = BM25(idx)
        ranked = bm25.rank([low, high], [porter_stem("cat")], top_k=10)
        self.assertEqual(ranked[0][0], high)

    def test_rank_respects_top_k(self):
        idx = InvertedIndex()
        ids = [idx.add_document(f"D{i}", "shared term repeated repeated") for i in range(5)]
        bm25 = BM25(idx)
        ranked = bm25.rank(ids, [porter_stem("shared")], top_k=2)
        self.assertEqual(len(ranked), 2)


class TfIdfCosineTests(unittest.TestCase):
    def test_matching_doc_scores_higher_than_empty_query_terms(self):
        idx = InvertedIndex()
        d1 = idx.add_document("A", "rockets launch into orbit")
        d2 = idx.add_document("B", "bread rises in the oven")
        cosine = TfIdfCosine(idx)
        term = porter_stem("rocket")
        self.assertGreater(cosine.score(d1, [term]), cosine.score(d2, [term]))

    def test_zero_vectors_return_zero(self):
        idx = InvertedIndex()
        d1 = idx.add_document("A", "hello world")
        cosine = TfIdfCosine(idx)
        self.assertEqual(cosine.score(d1, []), 0.0)


class SnippetTests(unittest.TestCase):
    def setUp(self):
        self.index = InvertedIndex()
        self.doc_id = self.index.add_document(
            "Test", "The quick brown fox jumps over the lazy dog near the river bank today"
        )
        self.doc = self.index.documents[self.doc_id]

    def test_highlights_matched_term(self):
        term = porter_stem("fox")
        pieces = build_snippet(self.doc, {term}, radius=3)
        matched_chunks = [chunk for chunk, is_match in pieces if is_match]
        self.assertIn("fox", [c.lower() for c in matched_chunks])

    def test_no_match_terms_returns_prefix(self):
        pieces = build_snippet(self.doc, set(), radius=3)
        self.assertTrue(all(not is_match for _chunk, is_match in pieces))

    def test_empty_document_snippet_does_not_crash(self):
        empty_id = self.index.add_document("Empty title only", "")
        doc = self.index.documents[empty_id]
        pieces = build_snippet(doc, {"x"})
        self.assertIsInstance(pieces, list)

    def test_snippet_to_text_marks_matches(self):
        pieces = [("hello ", False), ("world", True)]
        text = snippet_to_text(pieces)
        self.assertEqual(text, "hello **world**")

    def test_snippet_to_html_escapes_and_marks(self):
        pieces = [("<script> ", False), ("world", True)]
        html = snippet_to_html(pieces)
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)
        self.assertIn("<mark>world</mark>", html)


if __name__ == "__main__":
    unittest.main()
