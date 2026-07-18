import math
import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trove.index import InvertedIndex
from trove import ranking


def textbook_bm25(index, term, doc_id, k1=1.5, b=0.75):
    """An independent re-implementation of Okapi BM25 typed directly from
    the textbook formula, not sharing any code with ranking.py. Used to
    hand-verify the shipped implementation is correct, the same way
    test_stemmer.py cross-checks against the NLTK oracle."""
    df = index.doc_freq(term)
    n = index.N
    if df == 0:
        return 0.0
    idf = math.log(1 + (n - df + 0.5) / (df + 0.5))
    tf = len(index.postings.get(term, {}).get(doc_id, []))
    if tf == 0:
        return 0.0
    dl = index.doc_lengths[doc_id]
    avgdl = index.avg_doc_length
    numerator = tf * (k1 + 1)
    denominator = tf + k1 * (1 - b + b * dl / avgdl)
    return idf * numerator / denominator


def build_fixture_index():
    idx = InvertedIndex()
    idx.add_document("d1", "cat cat cat dog")            # len 4
    idx.add_document("d2", "cat dog dog dog dog")          # len 5
    idx.add_document("d3", "bird bird bird")                # len 3, no cat/dog
    idx.finalize()
    return idx


class TestBM25(unittest.TestCase):
    def setUp(self):
        self.idx = build_fixture_index()

    def test_matches_textbook_formula_for_every_term_doc_pair(self):
        for term in ("cat", "dog", "bird"):
            for doc_id in ("d1", "d2", "d3"):
                with self.subTest(term=term, doc_id=doc_id):
                    expected = textbook_bm25(self.idx, term, doc_id)
                    actual = ranking.bm25_term_score(self.idx, term, doc_id)
                    self.assertAlmostEqual(actual, expected, places=9)

    def test_hand_computed_exact_value(self):
        # N=3, df(cat)=2 -> idf = ln(1 + (3-2+0.5)/(2+0.5)) = ln(1.6)
        expected_idf_cat = math.log(1.6)
        self.assertAlmostEqual(ranking.idf(self.idx, "cat"), expected_idf_cat, places=9)
        # d1: tf(cat)=3, dl=4, avgdl=4, k1=1.5, b=0.75
        # denom = 3 + 1.5*(0.25 + 0.75*4/4) = 3 + 1.5*1 = 4.5
        # score = idf * (3*2.5)/4.5 = idf * 7.5/4.5
        expected_score = expected_idf_cat * (3 * 2.5) / 4.5
        self.assertAlmostEqual(
            ranking.bm25_term_score(self.idx, "cat", "d1"), expected_score, places=9
        )

    def test_document_with_more_occurrences_scores_higher(self):
        # d2 has 4 occurrences of "dog" vs d1's 1 -> d2 should score higher for "dog"
        score_d1 = ranking.bm25_term_score(self.idx, "dog", "d1")
        score_d2 = ranking.bm25_term_score(self.idx, "dog", "d2")
        self.assertGreater(score_d2, score_d1)

    def test_term_absent_from_corpus_scores_zero(self):
        self.assertEqual(ranking.bm25_term_score(self.idx, "elephant", "d1"), 0.0)

    def test_term_absent_from_doc_scores_zero(self):
        self.assertEqual(ranking.bm25_term_score(self.idx, "bird", "d1"), 0.0)

    def test_idf_always_nonnegative(self):
        # The Lucene-style BM25 IDF variant must never go negative, unlike
        # the classic Robertson-Sparck Jones form.
        idx = InvertedIndex()
        idx.add_document("a", "common common common")
        idx.add_document("b", "common common")
        idx.add_document("c", "common")
        idx.finalize()
        self.assertGreaterEqual(ranking.idf(idx, "common"), 0.0)

    def test_rank_orders_descending_and_respects_top(self):
        ranked = ranking.rank(self.idx, ["cat", "dog"], {"d1", "d2", "d3"}, top=2)
        self.assertEqual(len(ranked), 2)
        scores = [s for _, s in ranked]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_rank_restricted_to_candidate_set(self):
        # Even though d1 matches "cat", if it's excluded from the
        # candidate set (e.g. by a boolean filter upstream) it must not
        # appear in the ranked results.
        ranked = ranking.rank(self.idx, ["cat"], {"d2", "d3"}, top=10)
        doc_ids = [d for d, _ in ranked]
        self.assertNotIn("d1", doc_ids)


if __name__ == "__main__":
    unittest.main()
