import unittest

from engine import lexer


class TestLexer(unittest.TestCase):
    def kinds(self, text):
        return [t.kind for t in lexer.tokenize(text)]

    def test_numbers(self):
        toks = lexer.tokenize("3.14 + 2e3 + .5")
        vals = [t.value for t in toks if t.kind == lexer.NUMBER]
        self.assertEqual(vals, [3.14, 2000.0, 0.5])

    def test_string_with_escaped_quote(self):
        toks = lexer.tokenize('"say ""hi"""')
        self.assertEqual(toks[0].value, 'say "hi"')

    def test_unterminated_string_raises(self):
        with self.assertRaises(lexer.LexError):
            lexer.tokenize('"unterminated')

    def test_refs_absolute_and_relative(self):
        toks = lexer.tokenize("A1 $A1 A$1 $A$1")
        refs = [t.value for t in toks if t.kind == lexer.REF]
        self.assertEqual(refs, ["A1", "$A1", "A$1", "$A$1"])

    def test_bool_literals_case_insensitive(self):
        toks = lexer.tokenize("true FALSE")
        self.assertEqual([t.value for t in toks if t.kind == lexer.BOOL], [True, False])

    def test_function_name_that_looks_like_a_ref(self):
        # LOG10( must tokenize as a NAME, not a cell reference, because of the '('.
        toks = lexer.tokenize("LOG10(100)")
        self.assertEqual(toks[0].kind, lexer.NAME)
        self.assertEqual(toks[0].value, "LOG10")

    def test_comparison_operators(self):
        self.assertEqual(self.kinds("<> <= >= < > ="),
                          [lexer.NE, lexer.LE, lexer.GE, lexer.LT, lexer.GT, lexer.EQ, lexer.EOF])

    def test_sheet_bang(self):
        toks = lexer.tokenize("Sheet2!A1")
        self.assertEqual([t.kind for t in toks], [lexer.NAME, lexer.BANG, lexer.REF, lexer.EOF])

    def test_unexpected_char(self):
        with self.assertRaises(lexer.LexError):
            lexer.tokenize("A1 @ B1")


if __name__ == "__main__":
    unittest.main()
