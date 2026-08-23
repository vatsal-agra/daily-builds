import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.lexer import tokenize, LexError


class LexerTests(unittest.TestCase):
    def test_basic_tokens(self):
        toks = tokenize("fn foo(a, b) { return a + b; }")
        kinds = [t.kind for t in toks]
        self.assertEqual(
            kinds,
            ["fn", "IDENT", "(", "IDENT", ",", "IDENT", ")", "{", "return", "IDENT", "+", "IDENT", ";", "}", "EOF"],
        )

    def test_two_char_operators(self):
        toks = tokenize("a == b != c <= d >= e && f || g")
        kinds = [t.kind for t in toks if t.kind != "IDENT"]
        self.assertEqual(kinds, ["==", "!=", "<=", ">=", "&&", "||", "EOF"])

    def test_integers(self):
        toks = tokenize("0 42 1000000")
        values = [t.value for t in toks if t.kind == "INT"]
        self.assertEqual(values, [0, 42, 1000000])

    def test_line_comment_ignored(self):
        toks = tokenize("1 // this is a comment\n2")
        values = [t.value for t in toks if t.kind == "INT"]
        self.assertEqual(values, [1, 2])

    def test_block_comment_ignored(self):
        toks = tokenize("1 /* comment\nspanning lines */ 2")
        values = [t.value for t in toks if t.kind == "INT"]
        self.assertEqual(values, [1, 2])

    def test_unterminated_block_comment_raises(self):
        with self.assertRaises(LexError):
            tokenize("1 /* never closed")

    def test_float_literal_rejected(self):
        with self.assertRaises(LexError):
            tokenize("3.14")

    def test_unexpected_character_raises(self):
        with self.assertRaises(LexError):
            tokenize("a @ b")

    def test_keywords_vs_identifiers(self):
        toks = tokenize("fn while_x if_y")
        self.assertEqual(toks[0].kind, "fn")
        self.assertEqual(toks[1].kind, "IDENT")  # while_x is not the keyword 'while'
        self.assertEqual(toks[2].kind, "IDENT")

    def test_line_col_tracking(self):
        toks = tokenize("a\nb")
        a_tok = toks[0]
        b_tok = toks[1]
        self.assertEqual(a_tok.line, 1)
        self.assertEqual(b_tok.line, 2)


if __name__ == "__main__":
    unittest.main()
