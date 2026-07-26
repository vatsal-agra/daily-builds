import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trove.engine import Engine, MAX_QUERY_LENGTH
from trove.index import InvertedIndex


def build_fixture_index():
    idx = InvertedIndex()
    idx.add_document("d1", "cat dog fox", title="Animals", path="animals.txt")
    idx.add_document("d2", "quantum computer science", title="Quantum", path="quantum.txt")
    idx.finalize()
    return idx


class TestEngineSearch(unittest.TestCase):
    def setUp(self):
        self.engine = Engine(build_fixture_index())

    def test_happy_path_returns_scored_results(self):
        outcome = self.engine.search("cat dog")
        self.assertIsNone(outcome["error"])
        self.assertEqual(len(outcome["results"]), 1)
        self.assertEqual(outcome["results"][0].doc_id, "d1")

    def test_empty_query_returns_empty_without_error(self):
        outcome = self.engine.search("   ")
        self.assertIsNone(outcome["error"])
        self.assertEqual(outcome["results"], [])

    def test_syntax_error_reported_not_raised(self):
        outcome = self.engine.search("cat AND (dog")
        self.assertIsNotNone(outcome["error"])
        self.assertEqual(outcome["results"], [])

    def test_query_is_truncated_to_max_length(self):
        huge = "cat " * 1000  # far longer than MAX_QUERY_LENGTH
        outcome = self.engine.search(huge)
        self.assertIsNone(outcome["error"])  # truncation must not itself break parsing

    def test_negative_top_is_clamped_not_misinterpreted(self):
        # Python slice semantics would otherwise make top=-1 mean "all
        # but the last result" -- silently wrong, not just empty.
        outcome = self.engine.search("cat", top=-1)
        self.assertEqual(outcome["results"], [])
        self.assertIsNone(outcome["error"])

    def test_zero_top_returns_no_results(self):
        outcome = self.engine.search("cat", top=0)
        self.assertEqual(outcome["results"], [])

    def test_deep_recursion_is_caught_gracefully(self):
        # Simulate the pathological-nesting scenario without needing a
        # query longer than MAX_QUERY_LENGTH: temporarily lower the
        # recursion limit so a modest amount of nesting still overflows,
        # proving Engine.search's RecursionError guard actually engages.
        nested = "(" * 30 + "cat" + ")" * 30
        old_limit = sys.getrecursionlimit()
        sys.setrecursionlimit(40)
        try:
            outcome = self.engine.search(nested)
        finally:
            sys.setrecursionlimit(old_limit)
        self.assertIsNotNone(outcome["error"])
        self.assertEqual(outcome["results"], [])

    def test_fuzzy_correction_surfaced_in_outcome(self):
        outcome = self.engine.search("quantm")  # 6-char typo of "quantum"
        self.assertEqual(len(outcome["corrections"]), 1)
        self.assertEqual(outcome["results"][0].doc_id, "d2")

    def test_empty_index_does_not_crash_engine_construction(self):
        engine = Engine(InvertedIndex())
        outcome = engine.search("anything")
        self.assertEqual(outcome["results"], [])
        self.assertIsNone(outcome["error"])


if __name__ == "__main__":
    unittest.main()
