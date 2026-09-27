import unittest

from engine import parser as P
from engine import refs
from engine.tokenizer import tokenize, TokenizeError


class TestTokenizer(unittest.TestCase):
    def test_basic_tokens(self):
        toks = tokenize("A1+B2*3")
        kinds = [t.kind for t in toks]
        self.assertEqual(kinds, ["CELLREF", "OP", "CELLREF", "OP", "NUMBER", "EOF"])

    def test_string_with_escaped_quote(self):
        toks = tokenize('"a""b"')
        self.assertEqual(toks[0].kind, "STRING")
        self.assertEqual(toks[0].text, 'a"b')

    def test_unterminated_string(self):
        with self.assertRaises(TokenizeError):
            tokenize('"abc')

    def test_two_char_ops(self):
        toks = tokenize("A1<=B1<>C1>=D1")
        ops = [t.text for t in toks if t.kind == "OP"]
        self.assertEqual(ops, ["<=", "<>", ">="])

    def test_cellref_not_confused_with_function_name(self):
        toks = tokenize("SUM(A1)")
        self.assertEqual(toks[0].kind, "IDENT")
        self.assertEqual(toks[0].text, "SUM")

    def test_multi_letter_column(self):
        toks = tokenize("AA10")
        self.assertEqual(toks[0].kind, "CELLREF")
        self.assertEqual(toks[0].text, "AA10")

    def test_bool_literal(self):
        toks = tokenize("TRUE")
        self.assertEqual(toks[0].kind, "BOOL")

    def test_unexpected_char(self):
        with self.assertRaises(TokenizeError):
            tokenize("A1 @ B1")


class TestParserPrecedence(unittest.TestCase):
    def ev(self, formula):
        """Parse and evaluate with no cell lookups needed (pure literals)."""
        from engine.evaluator import EvalContext, evaluate
        ast = P.parse(formula)
        ctx = EvalContext(lambda c, r: None)
        return evaluate(ast, ctx)

    def test_arith_precedence(self):
        self.assertEqual(self.ev("2+3*4"), 14.0)
        self.assertEqual(self.ev("(2+3)*4"), 20.0)
        self.assertEqual(self.ev("2*3+4"), 10.0)
        self.assertEqual(self.ev("10-2-3"), 5.0)  # left-assoc: (10-2)-3
        self.assertEqual(self.ev("10-(2-3)"), 11.0)

    def test_power_right_assoc(self):
        self.assertEqual(self.ev("2^3^2"), 512.0)  # 2^(3^2) = 2^9

    def test_unary_binds_tighter_than_power(self):
        # Real spreadsheet semantics: unary minus binds tighter than '^',
        # so -2^2 == (-2)^2 == 4, not -(2^2) == -4.
        self.assertEqual(self.ev("-2^2"), 4.0)
        self.assertEqual(self.ev("2^-2"), 0.25)

    def test_double_unary(self):
        self.assertEqual(self.ev("--5"), 5.0)
        self.assertEqual(self.ev("-(2^2)"), -4.0)

    def test_concat_precedence(self):
        self.assertEqual(self.ev('"x"&1+1'), "x2")

    def test_comparison_lowest(self):
        self.assertEqual(self.ev("1+1=2"), True)
        self.assertEqual(self.ev('"abc">5'), True)  # text ranks above number

    def test_division(self):
        self.assertEqual(self.ev("10/2/5"), 1.0)

    def test_range_parses(self):
        ast = P.parse("SUM(A1:B10)")
        self.assertIsInstance(ast, P.FuncCall)
        self.assertEqual(ast.name, "SUM")
        self.assertIsInstance(ast.args[0], P.RangeRefNode)

    def test_unknown_bareword_is_name_error(self):
        from engine.evaluator import EvalContext, evaluate
        ast = P.parse("FOOBAR")
        ctx = EvalContext(lambda c, r: None)
        from engine import values as V
        self.assertEqual(evaluate(ast, ctx), V.NAME)


class TestFormulaRoundTrip(unittest.TestCase):
    """to_formula(parse(f)) must always reparse to an AST that evaluates
    identically to the original — the correctness property copy/paste and
    fill depend on."""

    FORMULAS = [
        "2+3*4",
        "(2+3)*4",
        "10-2-3",
        "10-(2-3)",
        "2^3^2",
        "(2^3)^2",
        "-2^2",
        "2^-2",
        "-(2^2)",
        "--5",
        '"x"&1+1&"y"',
        "1+1=2",
        "A1+B1*C1",
        "(A1+B1)*C1",
        "SUM(A1:B10)*2",
        "IF(A1>0,B1,C1)",
        "A1-B1-C1",
        "A1/(B1/C1)",
        "-A1^2",
        "(-A1)^2",
    ]

    def test_round_trip_preserves_value(self):
        from engine.evaluator import EvalContext, evaluate
        values_by_ref = {(1, 1): 3.0, (2, 1): 5.0, (3, 1): 7.0}
        lookup = lambda c, r: values_by_ref.get((c, r))
        ctx = EvalContext(lookup)
        for f in self.FORMULAS:
            ast1 = P.parse(f)
            text2 = P.to_formula(ast1)
            ast2 = P.parse(text2)
            v1 = evaluate(ast1, ctx)
            v2 = evaluate(ast2, ctx)
            self.assertEqual(v1, v2, f"round-trip changed value: {f!r} -> {text2!r}")

    def test_round_trip_is_idempotent_text(self):
        for f in self.FORMULAS:
            ast1 = P.parse(f)
            text2 = P.to_formula(ast1)
            ast2 = P.parse(text2)
            text3 = P.to_formula(ast2)
            self.assertEqual(text2, text3)


class TestRefs(unittest.TestCase):
    def test_col_letters_round_trip(self):
        for n in [1, 2, 26, 27, 28, 51, 52, 53, 702, 703, 704, 18278]:
            letters = refs.col_to_letters(n)
            self.assertEqual(refs.letters_to_col(letters), n)

    def test_parse_and_format(self):
        r = refs.parse_cell_ref("$A$1")
        self.assertEqual(r.to_a1(), "$A$1")
        r2 = refs.parse_cell_ref("B$2")
        self.assertEqual((r2.col, r2.row, r2.col_abs, r2.row_abs), (2, 2, False, True))

    def test_translate_relative(self):
        r = refs.parse_cell_ref("A1")
        t = r.translate(2, 3)
        self.assertEqual(t.to_a1(), "C4")

    def test_translate_absolute_locked(self):
        r = refs.parse_cell_ref("$A$1")
        t = r.translate(2, 3)
        self.assertEqual(t.to_a1(), "$A$1")

    def test_translate_mixed(self):
        r = refs.parse_cell_ref("$A1")
        t = r.translate(5, 5)
        self.assertEqual(t.to_a1(), "$A6")
        r2 = refs.parse_cell_ref("A$1")
        t2 = r2.translate(5, 5)
        self.assertEqual(t2.to_a1(), "F$1")

    def test_translate_off_grid_is_none(self):
        r = refs.parse_cell_ref("A1")
        self.assertIsNone(r.translate(-1, 0))
        self.assertIsNone(r.translate(0, -1))

    def test_range_cells(self):
        rng = refs.RangeRef(refs.parse_cell_ref("A1"), refs.parse_cell_ref("B2"))
        self.assertEqual(rng.cells(), [(1, 1), (2, 1), (1, 2), (2, 2)])

    def test_range_reversed_corners(self):
        rng = refs.RangeRef(refs.parse_cell_ref("B2"), refs.parse_cell_ref("A1"))
        self.assertEqual(sorted(rng.cells()), [(1, 1), (1, 2), (2, 1), (2, 2)])


if __name__ == "__main__":
    unittest.main()
