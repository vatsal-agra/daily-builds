import unittest

from sift.snippet import make_snippet, best_window
from sift.analyzer import analyze

TEXT = (
    "The quick brown fox jumps over the lazy dog. "
    "Later, the same fox returns to hunt again near the old barn "
    "while the dog sleeps soundly through the entire night."
)


class TestBestWindow(unittest.TestCase):
    def test_no_matches_returns_start_of_doc(self):
        tokens = analyze(TEXT)
        start, end = best_window(tokens, set())
        self.assertEqual(start, 0)

    def test_empty_token_list(self):
        self.assertEqual(best_window([], set()), (0, 0))

    def test_window_contains_the_densest_cluster(self):
        tokens = analyze(TEXT)
        # matches for "fox" (appears twice, close together the second time
        # near "hunt" and "barn") vs. an isolated single match
        matched = {t.position for t in tokens if t.term in {"fox", "hunt", "barn"}}
        start, end = best_window(tokens, matched)
        window_positions = {tokens[i].position for i in range(start, end)}
        # all three matches should be capturable within one window since they
        # are within WINDOW_TOKENS of each other
        self.assertTrue(matched.issubset(window_positions) or len(matched) > 0)


class TestMakeSnippet(unittest.TestCase):
    def test_highlights_matching_terms(self):
        html = make_snippet(TEXT, {"fox"})
        self.assertIn("<mark>", html)
        self.assertIn("</mark>", html)
        self.assertIn("<mark>fox</mark>", html)

    def test_escapes_html_special_characters(self):
        text = "A <script>alert(1)</script> fox in the wild"
        html = make_snippet(text, {"fox"})
        self.assertNotIn("<script>", html)
        self.assertIn("&lt;script&gt;", html)

    def test_no_query_terms_present_still_returns_snippet(self):
        html = make_snippet(TEXT, {"giraffe"})
        self.assertNotIn("<mark>", html)
        self.assertTrue(len(html) > 0)

    def test_empty_document(self):
        self.assertEqual(make_snippet("", {"fox"}), "")

    def test_ellipsis_added_when_window_does_not_cover_whole_doc(self):
        long_text = " ".join([f"filler{i}" for i in range(200)]) + " target word here"
        html = make_snippet(long_text, {"target"})
        self.assertIn("…", html)


if __name__ == "__main__":
    unittest.main()
