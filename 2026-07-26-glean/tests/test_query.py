import os
import shutil
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from glean.crawler import crawl
from glean.index import Index, IndexWriter
from glean.query import parse_query, search


class QueryTestBase(unittest.TestCase):
    DOCS = {
        "raft.md": "# Raft\nA deterministic raft consensus simulator with a bloom filter cache.",
        "raytrace.md": "# Ray Tracing\nA physically based ray tracing renderer. Bloom filter is not used here.",
        "chess.md": "# Chess\nA chess engine with alpha-beta search and a transposition table.",
        "empty_ish.md": "# Blank\nx",
    }

    def setUp(self):
        self.root = tempfile.mkdtemp(prefix="glean_test_query_")
        for name, content in self.DOCS.items():
            with open(os.path.join(self.root, name), "w", encoding="utf-8") as f:
                f.write(content)
        self.index_dir = os.path.join(self.root, ".glean")
        writer = IndexWriter(self.root, index_dir=self.index_dir)
        writer.build(crawl(self.root))
        self.index = Index(self.index_dir)

    def tearDown(self):
        shutil.rmtree(self.root, ignore_errors=True)

    def paths(self, results):
        return {r["path"] for r in results}


class TestParseQuery(unittest.TestCase):
    def test_bare_words_default_to_or(self):
        clauses = parse_query("raft consensus")
        self.assertEqual([c.connector for c in clauses], ["OR", "OR"])
        self.assertFalse(any(c.negate for c in clauses))

    def test_explicit_and(self):
        # Both sides of an explicit AND must become required (MUST) clauses,
        # not just the term textually to the right of the keyword.
        clauses = parse_query("chess AND transposition")
        self.assertEqual([c.connector for c in clauses], ["AND", "AND"])

    def test_not_sets_negate_regardless_of_connector(self):
        clauses = parse_query("raft NOT chess")
        self.assertTrue(clauses[-1].negate)

    def test_quoted_phrase_becomes_single_phrase_clause(self):
        clauses = parse_query('"ray tracing"')
        self.assertEqual(len(clauses), 1)
        self.assertEqual(clauses[0].kind, "phrase")
        self.assertEqual([t for t, _ in clauses[0].terms], ["rai", "trace"])

    def test_all_stopword_query_yields_no_clauses(self):
        self.assertEqual(parse_query("the a of"), [])

    def test_empty_query_yields_no_clauses(self):
        self.assertEqual(parse_query(""), [])
        self.assertEqual(parse_query("   "), [])

    def test_unbalanced_quote_degrades_to_bare_word(self):
        clauses = parse_query('"raft leader')
        self.assertTrue(all(c.kind == "term" for c in clauses))


class TestBooleanSearch(QueryTestBase):
    def test_bare_or_returns_any_matching_doc(self):
        results, _, _ = search(self.index, "raft transposition", fuzzy=False)
        self.assertEqual(self.paths(results), {"raft.md", "chess.md"})

    def test_and_requires_all_terms(self):
        results, _, _ = search(self.index, "chess AND transposition", fuzzy=False)
        self.assertEqual(self.paths(results), {"chess.md"})

    def test_and_excludes_partial_matches(self):
        results, _, _ = search(self.index, "chess AND bloom", fuzzy=False)
        self.assertEqual(self.paths(results), set())

    def test_not_excludes_matching_docs(self):
        results, _, _ = search(self.index, "bloom NOT chess", fuzzy=False)
        self.assertNotIn("chess.md", self.paths(results))

    def test_not_excludes_doc_containing_excluded_term(self):
        results, _, _ = search(self.index, "filter NOT raft", fuzzy=False)
        self.assertEqual(self.paths(results), {"raytrace.md"})

    def test_pure_not_query_returns_everything_except_excluded(self):
        results, _, _ = search(self.index, "NOT chess", fuzzy=False)
        self.assertEqual(self.paths(results), {"raft.md", "raytrace.md", "empty_ish.md"})

    def test_nonexistent_term_returns_no_results(self):
        results, suggestions, _ = search(self.index, "zzzznotarealwordzzzz", fuzzy=False)
        self.assertEqual(results, [])


class TestPhraseSearch(QueryTestBase):
    def test_exact_phrase_matches_adjacent_words(self):
        results, _, _ = search(self.index, '"ray tracing"', fuzzy=False)
        self.assertEqual(self.paths(results), {"raytrace.md"})

    def test_phrase_does_not_match_mere_co_occurrence(self):
        # "bloom" and "filter" both appear in raft.md and raytrace.md, but the
        # *phrase* "filter bloom" (reversed word order) appears nowhere.
        results, _, _ = search(self.index, '"filter bloom"', fuzzy=False)
        self.assertEqual(results, [])

    def test_phrase_matches_only_true_adjacency(self):
        # "bloom filter" is adjacent in both raft.md and raytrace.md's text.
        results, _, _ = search(self.index, '"bloom filter"', fuzzy=False)
        self.assertEqual(self.paths(results), {"raft.md", "raytrace.md"})


class TestFuzzySearch(QueryTestBase):
    def test_typo_is_corrected_and_still_finds_doc(self):
        results, suggestions, _ = search(self.index, "consesus", fuzzy=True)
        self.assertEqual(self.paths(results), {"raft.md"})
        self.assertTrue(suggestions)

    def test_no_fuzzy_flag_disables_correction(self):
        results, suggestions, _ = search(self.index, "consesus", fuzzy=False)
        self.assertEqual(results, [])
        self.assertEqual(suggestions, [])

    def test_fuzzy_does_not_rewrite_phrase_clauses(self):
        # A typo inside a quoted phrase must not be silently corrected --
        # "exact phrase" should mean exactly what was typed.
        results, suggestions, _ = search(self.index, '"ray tracign"', fuzzy=True)
        self.assertEqual(results, [])


class TestRankingAndLimit(QueryTestBase):
    def test_results_sorted_descending_by_score(self):
        results, _, _ = search(self.index, "bloom filter", fuzzy=False)
        scores = [r["score"] for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_limit_is_respected(self):
        results, _, _ = search(self.index, "bloom filter raft chess", limit=1, fuzzy=False)
        self.assertLessEqual(len(results), 1)

    def test_zero_or_negative_limit_does_not_crash(self):
        results, _, _ = search(self.index, "chess", limit=0, fuzzy=False)
        self.assertGreaterEqual(len(results), 1)  # clamped to at least 1
        results, _, _ = search(self.index, "chess", limit=-5, fuzzy=False)
        self.assertGreaterEqual(len(results), 1)


if __name__ == "__main__":
    unittest.main()
