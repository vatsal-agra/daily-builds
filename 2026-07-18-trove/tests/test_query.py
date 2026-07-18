import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trove.index import InvertedIndex
from trove.fuzzy import build_bktree
from trove import query as query_mod


def build_fixture_index():
    idx = InvertedIndex()
    idx.add_document("d1", "The quick brown fox jumps over the lazy dog. The dog barks at the fox.")
    idx.add_document("d2", "A fast brown fox runs through the forest. Foxes are quick and clever animals.")
    idx.add_document("d3", "The lazy cat sleeps all day long. Cats do not jump very often, unlike dogs.")
    idx.add_document("d4", "Quantum computers use qubits instead of classical bits for computation.")
    idx.finalize()
    return idx


class TestQueryParserAndEvaluator(unittest.TestCase):
    def setUp(self):
        self.idx = build_fixture_index()

    def run_query(self, text, **kw):
        return query_mod.evaluate(self.idx, text, **kw)

    def test_single_word(self):
        r = self.run_query("fox")
        self.assertEqual(r.doc_ids, {"d1", "d2"})

    def test_implicit_and(self):
        r = self.run_query("fox lazy")
        self.assertEqual(r.doc_ids, {"d1"})

    def test_explicit_and(self):
        r = self.run_query("fox AND lazy")
        self.assertEqual(r.doc_ids, {"d1"})

    def test_or(self):
        r = self.run_query("quantum OR cat")
        self.assertEqual(r.doc_ids, {"d3", "d4"})

    def test_not_with_minus(self):
        r = self.run_query("fox -lazy")
        self.assertEqual(r.doc_ids, {"d2"})

    def test_not_keyword(self):
        r = self.run_query("fox NOT lazy")
        self.assertEqual(r.doc_ids, {"d2"})

    def test_parentheses_change_precedence(self):
        # Without parens: quantum OR (cat AND dog) -> d4 plus doc(s) with both cat+dog
        r1 = self.run_query("quantum OR cat dog")
        # d3 has both "cat" and "dog" ("unlike dogs" stems to dog)
        self.assertEqual(r1.doc_ids, {"d3", "d4"})
        # With parens forcing OR of everything: (quantum OR cat) AND dog -> only docs with dog AND (quantum or cat)
        r2 = self.run_query("(quantum OR cat) AND dog")
        self.assertEqual(r2.doc_ids, {"d3"})

    def test_phrase_query_requires_adjacency(self):
        r = self.run_query('"brown fox"')
        self.assertEqual(r.doc_ids, {"d1", "d2"})
        # "fox brown" (reversed) should not match either doc as a phrase
        r2 = self.run_query('"fox brown"')
        self.assertEqual(r2.doc_ids, set())

    def test_phrase_with_stopword_inside(self):
        # "at" and "the" are stopwords, dropped at both index and query
        # time; the surviving terms dog/bark/fox must still line up as
        # *consecutive* positions in the filtered stream to match, which
        # only d1's "dog barks at the fox" satisfies.
        r = self.run_query('"dog barks at the fox"')
        self.assertEqual(r.doc_ids, {"d1"})

    def test_prefix_query(self):
        r = self.run_query("qu*")
        # matches "quick" (d1,d2) and "quantum" (d4)
        self.assertEqual(r.doc_ids, {"d1", "d2", "d4"})

    def test_negated_prefix(self):
        r = self.run_query("fox -qu*")
        self.assertEqual(r.doc_ids, set())  # both fox docs also match qu* (quick)

    def test_empty_query_returns_nothing(self):
        r = self.run_query("   ")
        self.assertEqual(r.doc_ids, set())
        self.assertEqual(r.terms, set())

    def test_unknown_word_without_fuzzy_returns_nothing(self):
        r = self.run_query("zzzznotaword")
        self.assertEqual(r.doc_ids, set())

    def test_fuzzy_correction_applied(self):
        bktree = build_bktree(self.idx)
        r = self.run_query("quantm", fuzzy_corrector=bktree, fuzzy_max_distance=2)
        self.assertEqual(r.doc_ids, {"d4"})
        self.assertEqual(len(r.corrections), 1)
        typed, corrected = r.corrections[0]
        self.assertEqual(typed, "quantm")

    def test_fuzzy_correction_not_applied_when_exact_match_exists(self):
        bktree = build_bktree(self.idx)
        r = self.run_query("fox", fuzzy_corrector=bktree, fuzzy_max_distance=2)
        self.assertEqual(r.corrections, [])

    def test_malformed_query_raises_syntax_error(self):
        with self.assertRaises(query_mod.QuerySyntaxError):
            self.run_query("fox AND (lazy")
        with self.assertRaises(query_mod.QuerySyntaxError):
            self.run_query("fox)")
        with self.assertRaises(query_mod.QuerySyntaxError):
            self.run_query("AND fox")

    def test_unterminated_phrase_raises_instead_of_silently_reinterpreting(self):
        with self.assertRaises(query_mod.QuerySyntaxError):
            self.run_query('"fox brown')

    def test_fused_minus_negates_parenthesized_group(self):
        # Regression: '-(' used to lex as junk (dropped), silently
        # returning the *positive* group instead of its negation.
        positive = self.run_query("fox AND lazy")
        self.assertEqual(positive.doc_ids, {"d1"})
        negated = self.run_query("-(fox AND lazy)")
        self.assertEqual(negated.doc_ids, self.idx.all_doc_ids() - positive.doc_ids)
        self.assertNotIn("d1", negated.doc_ids)

    def test_fused_minus_negates_phrase(self):
        positive = self.run_query('"brown fox"')
        self.assertEqual(positive.doc_ids, {"d1", "d2"})
        negated = self.run_query('-"brown fox"')
        self.assertEqual(negated.doc_ids, self.idx.all_doc_ids() - positive.doc_ids)

    def test_short_term_gets_no_fuzzy_correction_by_default(self):
        # "cat" (3 chars) must not fuzzy-correct to some unrelated short
        # vocabulary word at the old fixed distance=2 default.
        bktree = build_bktree(self.idx)
        r = self.run_query("cot", fuzzy_corrector=bktree)  # auto distance for len<=3 is 0
        self.assertEqual(r.doc_ids, set())
        self.assertEqual(r.corrections, [])

    def test_double_negative_not_not(self):
        # NOT NOT fox == fox
        r1 = self.run_query("NOT NOT fox")
        r2 = self.run_query("fox")
        self.assertEqual(r1.doc_ids, r2.doc_ids)


if __name__ == "__main__":
    unittest.main()
