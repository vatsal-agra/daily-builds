import os
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from trove.snippet import make_snippet
from trove.tokenizer import normalize_term


class TestSnippet(unittest.TestCase):
    def test_highlights_query_terms(self):
        text = "The quick brown fox jumps over the lazy dog near the river bank."
        terms = {normalize_term("fox"), normalize_term("dog")}
        snippet = make_snippet(text, terms)
        self.assertIn("**fox**", snippet)
        self.assertIn("**dog**", snippet)

    def test_no_query_terms_falls_back_to_start_of_doc(self):
        text = "Alpha beta gamma delta epsilon zeta eta theta."
        snippet = make_snippet(text, set())
        self.assertTrue(snippet.startswith("Alpha"))

    def test_no_match_in_text_falls_back_gracefully_no_crash(self):
        text = "Completely unrelated content with no hits at all."
        snippet = make_snippet(text, {normalize_term("quantum")})
        self.assertTrue(snippet)  # falls back to start-of-doc, doesn't crash or return empty

    def test_empty_text_returns_empty_string(self):
        self.assertEqual(make_snippet("", {normalize_term("fox")}), "")

    def test_picks_densest_cluster_over_first_occurrence(self):
        # "target" appears once early, alone, and three times later,
        # clustered -- the snippet should center on the cluster.
        text = (
            "target appears once here with nothing else interesting. " +
            ("filler word here. " * 15) +
            "then target target target all cluster together at the end."
        )
        terms = {normalize_term("target")}
        snippet = make_snippet(text, terms)
        self.assertEqual(snippet.count("**target**"), 3)

    def test_respects_max_chars(self):
        text = "word " * 500 + "needle"
        snippet = make_snippet(text, {normalize_term("needle")}, max_chars=100)
        self.assertLessEqual(len(snippet), 110)  # small slack for the trailing ellipsis

    def test_never_raises_on_weird_input(self):
        for text in ["", " ", "...", "a", "𝔘𝔫𝔦𝔠𝔬𝔡𝔢 𝔱𝔢𝔵𝔱"]:
            make_snippet(text, {normalize_term("fox")})  # must not raise


if __name__ == "__main__":
    unittest.main()
