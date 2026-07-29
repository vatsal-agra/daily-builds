import unittest
from ember.lexer import tokenize, LexError


class TestLexer(unittest.TestCase):
    def test_basic_tokens(self):
        toks = tokenize("fn f(x) { return x + 1; }")
        kinds_texts = [(t.kind, t.text) for t in toks if t.kind != "EOF"]
        self.assertEqual(kinds_texts, [
            ("KW", "fn"), ("IDENT", "f"), ("SYM", "("), ("IDENT", "x"), ("SYM", ")"),
            ("SYM", "{"), ("KW", "return"), ("IDENT", "x"), ("SYM", "+"),
            ("INT", "1"), ("SYM", ";"), ("SYM", "}"),
        ])

    def test_int_value(self):
        toks = tokenize("12345")
        self.assertEqual(toks[0].value, 12345)

    def test_two_char_operators_prefer_longest_match(self):
        toks = tokenize("a == b != c <= d >= e && f || g")
        syms = [t.text for t in toks if t.kind == "SYM"]
        self.assertEqual(syms, ["==", "!=", "<=", ">=", "&&", "||"])

    def test_line_comment_skipped(self):
        toks = tokenize("1 // this is a comment\n+ 2")
        vals = [t.value for t in toks if t.kind == "INT"]
        self.assertEqual(vals, [1, 2])

    def test_line_col_tracking(self):
        toks = tokenize("a\nb")
        b_tok = [t for t in toks if t.kind == "IDENT" and t.text == "b"][0]
        self.assertEqual((b_tok.line, b_tok.col), (2, 1))

    def test_malformed_literal_raises(self):
        with self.assertRaises(LexError):
            tokenize("123abc")

    def test_unexpected_char_raises(self):
        with self.assertRaises(LexError):
            tokenize("a $ b")

    def test_empty_source(self):
        toks = tokenize("")
        self.assertEqual([t.kind for t in toks], ["EOF"])

    def test_keywords_recognized(self):
        toks = tokenize("fn let if else while return true false")
        self.assertTrue(all(t.kind == "KW" for t in toks if t.kind != "EOF"))


if __name__ == "__main__":
    unittest.main()
