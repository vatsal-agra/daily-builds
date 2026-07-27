import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unify.lexer import tokenize, LexError


def kinds(source):
    return [(t.kind, t.text) for t in tokenize(source) if t.kind != "EOF"]


class TestLexer(unittest.TestCase):
    def test_integers_and_idents(self):
        self.assertEqual(kinds("42 foo"), [("INT", "42"), ("IDENT", "foo")])

    def test_keywords_are_not_idents(self):
        self.assertEqual(kinds("let x"), [("KEYWORD", "let"), ("IDENT", "x")])

    def test_string_literal_with_escapes(self):
        toks = tokenize(r'"a\nb\"c"')
        self.assertEqual(toks[0].kind, "STRING")
        self.assertEqual(toks[0].value, 'a\nb"c')

    def test_unterminated_string_raises(self):
        with self.assertRaises(LexError):
            tokenize('"unterminated')

    def test_longest_match_symbols(self):
        # "->" must not lex as "-" then ">" (there is no ">" alone token here).
        self.assertEqual(kinds("->"), [("SYMBOL", "->")])
        self.assertEqual(kinds("<="), [("SYMBOL", "<=")])
        self.assertEqual(kinds("::"), [("SYMBOL", "::")])
        self.assertEqual(kinds("-"), [("SYMBOL", "-")])

    def test_comments_are_skipped(self):
        self.assertEqual(kinds("1 # this is a comment\n+ 2"), [
            ("INT", "1"), ("SYMBOL", "+"), ("INT", "2"),
        ])

    def test_underscore_is_symbol_not_ident(self):
        self.assertEqual(kinds("_"), [("SYMBOL", "_")])

    def test_unexpected_character_raises(self):
        with self.assertRaises(LexError):
            tokenize("1 @ 2")

    def test_line_col_tracking(self):
        toks = tokenize("1\n  2")
        two = [t for t in toks if t.text == "2"][0]
        self.assertEqual((two.line, two.col), (2, 3))


if __name__ == "__main__":
    unittest.main()
