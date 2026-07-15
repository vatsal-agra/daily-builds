import os
import tempfile
import unittest

from glean.engine import SearchEngine
from glean.query import QuerySyntaxError
from corpus.demo_corpus import load_corpus


class SearchEngineTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.engine = SearchEngine()
        for article in load_corpus():
            cls.engine.add_document(article["title"], article["text"], path=article["topic"])

    def test_basic_search_returns_relevant_top_result(self):
        results = self.engine.search("photosynthesis")
        self.assertTrue(results)
        self.assertEqual(results[0].title, "How Photosynthesis Works")

    def test_phrase_search(self):
        results = self.engine.search('"printing press"')
        self.assertTrue(any(r.title == "The Printing Press and Its Impact" for r in results))

    def test_negative_top_k_clamped_not_slice_wrapped(self):
        # top_k=-1 must not silently become Python's "all but last" slice.
        results = self.engine.search("history", top_k=-1)
        self.assertEqual(results, [])

    def test_zero_top_k(self):
        self.assertEqual(self.engine.search("history", top_k=0), [])

    def test_no_results_for_nonsense_query(self):
        results = self.engine.search("zzzznonexistentwordxyz")
        self.assertEqual(results, [])

    def test_invalid_query_raises_syntax_error(self):
        with self.assertRaises(QuerySyntaxError):
            self.engine.search("(unterminated")

    def test_results_are_ranked_descending(self):
        results = self.engine.search("history OR science OR technology", top_k=10)
        scores = [r.score for r in results]
        self.assertEqual(scores, sorted(scores, reverse=True))

    def test_stats_reports_all_documents(self):
        stats = self.engine.stats()
        self.assertEqual(stats["documents"], 50)
        self.assertGreater(stats["vocabulary"], 0)

    def test_autocomplete_returns_real_words(self):
        completions = self.engine.autocomplete("phot")
        self.assertIn("photosynthesis", completions)

    def test_autocomplete_empty_prefix(self):
        self.assertEqual(self.engine.autocomplete(""), [])

    def test_autocomplete_unknown_prefix(self):
        self.assertEqual(self.engine.autocomplete("zzqzq"), [])

    def test_did_you_mean_for_typo(self):
        suggestions = self.engine.did_you_mean("photosinthesis")
        self.assertTrue(suggestions)
        all_words = [w for cands in suggestions.values() for w, _d in cands]
        self.assertIn("photosynthesis", all_words)

    def test_did_you_mean_empty_for_correct_query(self):
        self.assertEqual(self.engine.did_you_mean("roman empire"), {})

    def test_did_you_mean_handles_syntax_errors_gracefully(self):
        self.assertEqual(self.engine.did_you_mean("(unterminated"), {})

    def test_vocabulary_change_invalidates_cached_fuzzy_and_trie(self):
        engine = SearchEngine()
        engine.add_document("A", "aardvark armadillo antelope")
        self.assertIn("aardvark", engine.autocomplete("aard"))
        engine.add_document("B", "aardwolf appears too")
        self.assertIn("aardwolf", engine.autocomplete("aard"))

    def test_save_load_round_trip_preserves_search_results(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "e.idx")
            self.engine.save(path)
            loaded = SearchEngine.load(path)
            before = [(r.doc_id, round(r.score, 6)) for r in self.engine.search("roman empire")]
            after = [(r.doc_id, round(r.score, 6)) for r in loaded.search("roman empire")]
            self.assertEqual(before, after)


if __name__ == "__main__":
    unittest.main()
