import unittest

from sift.analyzer import analyze
from sift.index import InvertedIndex
from sift.query import search, parse_query, QueryError
from sift.trie import Trie
from sift.fuzzy import BKTree

DOCS = {
    0: "The quick brown fox jumps over the lazy dog",
    1: "A quick fox is not a lazy dog, it runs fast through the forest",
    2: "Cooking recipes for baking bread and cakes require careful timing",
    3: "The fox and the dog became unlikely friends in the forest",
    4: "Bread baking requires yeast flour water and salt",
    5: "Quantum mechanics describes particles as waves until measured",
    6: "Day and night the fox hunted quietly across the forest",
}


def naive_phrase_oracle(doc_text, phrase_terms):
    """Independent phrase-match check: re-tokenize/stem the raw text (not via
    the index's postings/positions) WITHOUT dropping stopwords, and look for
    the phrase's content terms as a literally CONTIGUOUS run in that full
    stream. Adjacent entries in the full (unfiltered) stream are, by
    construction, adjacent raw positions with nothing else in between —
    including no stopword — so this agrees with the engine's position-offset
    adjacency check for any phrase whose own words carry no internal gap
    (the common case this test covers).
    """
    full_stream = [t.term for t in analyze(doc_text, remove_stopwords=False)]
    n, k = len(full_stream), len(phrase_terms)
    for start in range(n - k + 1):
        if full_stream[start : start + k] == phrase_terms:
            return True
    return False


class QueryTestBase(unittest.TestCase):
    def setUp(self):
        self.index = InvertedIndex()
        for doc_id in sorted(DOCS):
            self.index.add_document(f"doc{doc_id}.txt", f"Doc {doc_id}", DOCS[doc_id])
        self.trie = Trie()
        vocab = self.index.vocabulary()
        for term in vocab:
            self.trie.insert(term)
        self.bktree = BKTree(vocab[0]) if vocab else None
        for term in vocab[1:]:
            self.bktree.insert(term)

    def run_query(self, q):
        return {
            doc_id
            for doc_id, _ in search(self.index, q, trie=self.trie, bktree=self.bktree)
        }


class TestBooleanQueries(unittest.TestCase):
    def setUp(self):
        QueryTestBase.setUp(self)

    run_query = QueryTestBase.run_query

    def test_implicit_and(self):
        self.assertEqual(self.run_query("fox dog"), {0, 1, 3})

    def test_explicit_and(self):
        self.assertEqual(self.run_query("fox AND dog"), {0, 1, 3})

    def test_or(self):
        self.assertEqual(self.run_query("bread OR quantum"), {2, 4, 5})

    def test_not(self):
        self.assertEqual(self.run_query("fox NOT dog"), {6})

    def test_parenthesized_grouping_changes_result(self):
        # (fox OR bread) AND baking  -> only docs with fox-or-bread AND baking
        a = self.run_query("(fox OR bread) AND baking")
        self.assertEqual(a, {2, 4})

    def test_precedence_and_binds_tighter_than_or(self):
        # "fox AND dog OR quantum" == (fox AND dog) OR quantum
        self.assertEqual(
            self.run_query("fox AND dog OR quantum"),
            self.run_query("(fox AND dog) OR quantum"),
        )

    def test_case_insensitive_operators(self):
        self.assertEqual(self.run_query("fox and dog"), self.run_query("fox AND dog"))

    def test_double_negative(self):
        self.assertEqual(self.run_query("NOT NOT fox"), self.run_query("fox"))

    def test_term_with_no_matches(self):
        self.assertEqual(self.run_query("nonexistentword"), set())

    def test_unknown_word_and_real_word(self):
        self.assertEqual(self.run_query("fox AND zzzznotaword"), set())


class TestPhraseQueries(unittest.TestCase):
    def setUp(self):
        QueryTestBase.setUp(self)

    run_query = QueryTestBase.run_query

    def test_adjacent_phrase_matches(self):
        # doc1 has "quick fox" adjacent; doc0 has "quick brown fox" (not adjacent)
        self.assertEqual(self.run_query('"quick fox"'), {1})

    def test_phrase_requires_order(self):
        self.assertEqual(self.run_query('"fox quick"'), set())

    def test_phrase_agrees_with_naive_oracle_no_internal_stopwords(self):
        phrase_variants = [
            ("quick fox", ["quick", "fox"]),
            ("lazy dog", ["lazi", "dog"]),
            ("fox dog", ["fox", "dog"]),
            ("cooking recipes", ["cook", "recip"]),
        ]
        for phrase_text, phrase_terms in phrase_variants:
            engine_matches = self.run_query(f'"{phrase_text}"')
            oracle_matches = {
                doc_id
                for doc_id, text in DOCS.items()
                if naive_phrase_oracle(text, phrase_terms)
            }
            self.assertEqual(
                engine_matches, oracle_matches, f"mismatch for phrase {phrase_text!r}"
            )

    def test_phrase_with_internal_stopword_respects_gap(self):
        # "fox and dog" (doc3: "fox and the dog" has an extra word -> no match;
        # doc index has no doc with the exact 3-position gap "fox and dog")
        self.assertEqual(self.run_query('"day and night"'), {6})

    def test_phrase_of_all_stopwords_matches_nothing(self):
        self.assertEqual(self.run_query('"the a"'), set())


class TestWildcardQueries(unittest.TestCase):
    def setUp(self):
        QueryTestBase.setUp(self)

    run_query = QueryTestBase.run_query

    def test_prefix_expansion(self):
        # "cook*" should match cook/cooking/... stems appearing in doc 2
        self.assertEqual(self.run_query("cook*"), {2})

    def test_wildcard_union_semantics(self):
        wildcard_result = self.run_query("qui*")  # quick / quietly
        self.assertEqual(wildcard_result, {0, 1, 6})


class TestFuzzyQueries(unittest.TestCase):
    def setUp(self):
        QueryTestBase.setUp(self)

    run_query = QueryTestBase.run_query

    def test_typo_correction(self):
        self.assertEqual(self.run_query("qwick~2"), {0, 1})

    def test_fuzzy_radius_zero_is_exact(self):
        self.assertEqual(self.run_query("fox~0"), self.run_query("fox"))


class TestQueryParserErrors(unittest.TestCase):
    def test_empty_query_raises(self):
        with self.assertRaises(QueryError):
            parse_query("")

    def test_unbalanced_parens_raises(self):
        with self.assertRaises(QueryError):
            parse_query("(fox AND dog")

    def test_trailing_garbage_raises(self):
        with self.assertRaises(QueryError):
            parse_query("fox)")

    def test_unterminated_phrase_raises(self):
        with self.assertRaises(QueryError):
            parse_query('"unclosed phrase')

    def test_lone_quote_raises(self):
        with self.assertRaises(QueryError):
            parse_query('"')

    def test_wildcard_asterisk_in_middle_raises(self):
        with self.assertRaises(QueryError):
            parse_query("abc*def")

    def test_wildcard_multiple_asterisks_raises(self):
        with self.assertRaises(QueryError):
            parse_query("ab**")

    def test_lone_asterisk_raises(self):
        with self.assertRaises(QueryError):
            parse_query("*")

    def test_valid_wildcard_does_not_raise(self):
        parse_query("comput*")  # should not raise


if __name__ == "__main__":
    unittest.main()
