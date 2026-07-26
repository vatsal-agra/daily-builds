import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from glean.snippet import make_snippet, to_html, to_ansi, to_plain


class TestSnippet(unittest.TestCase):
    def test_highlights_matched_term(self):
        snippet = make_snippet("The raft consensus algorithm is great.", {"raft"})
        self.assertIn("[[raft]]", snippet.lower())

    def test_no_match_falls_back_to_leading_text(self):
        snippet = make_snippet("Nothing relevant here at all.", {"zzz"})
        self.assertNotIn("[[", snippet)
        self.assertIn("Nothing relevant", snippet)

    def test_empty_text(self):
        self.assertEqual(make_snippet("", {"raft"}), "")

    def test_truncates_long_text_with_ellipsis(self):
        long_text = "word " * 200 + "raft " + "word " * 200
        snippet = make_snippet(long_text, {"raft"}, window=60)
        self.assertTrue(snippet.startswith("…"))
        self.assertTrue(snippet.endswith("…"))

    def test_strips_markdown_heading_and_bold(self):
        snippet = make_snippet("# Raft Consensus\n**important** details here.", {"raft"})
        self.assertNotIn("#", snippet.split("[[")[0])  # heading marker gone before match
        self.assertNotIn("**", snippet)

    def test_preserves_dunder_identifiers(self):
        text = "See glean/__init__.py for the raft package entry point."
        snippet = make_snippet(text, {"raft"})
        self.assertIn("__init__.py", snippet)

    def test_to_html_wraps_marks(self):
        snippet = "before [[raft]] after"
        self.assertEqual(to_html(snippet), "before <mark>raft</mark> after")

    def test_to_ansi_wraps_escape_codes(self):
        snippet = "before [[raft]] after"
        result = to_ansi(snippet)
        self.assertIn("\033[1m", result)
        self.assertIn("raft", result)

    def test_to_plain_strips_markers(self):
        snippet = "before [[raft]] after"
        self.assertEqual(to_plain(snippet), "before raft after")


if __name__ == "__main__":
    unittest.main()
