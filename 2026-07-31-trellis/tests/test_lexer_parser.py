import unittest

from trellis.lexer import tokenize, LexError
from trellis.parser import parse, ParseError, NameRef
from trellis.ast_nodes import (
    NumberLit, StringLit, BoolLit, CellRef, RangeRef, BinOp, UnaryOp, FuncCall,
)


class TestLexer(unittest.TestCase):
    def test_numbers(self):
        toks = tokenize("1 2.5 3e2 3E-2 .5")
        types = [t.type for t in toks if t.type != "EOF"]
        self.assertEqual(types, ["NUMBER"] * 5)

    def test_string_with_escapes(self):
        toks = tokenize(r'"a\"b\\c"')
        self.assertEqual(toks[0].text, 'a"b\\c')

    def test_unterminated_string(self):
        with self.assertRaises(LexError):
            tokenize('"unterminated')

    def test_comparison_operators(self):
        toks = tokenize("<= >= <> < > =")
        types = [t.type for t in toks if t.type != "EOF"]
        self.assertEqual(types, ["LE", "GE", "NE", "LT", "GT", "EQ"])

    def test_unknown_char(self):
        with self.assertRaises(LexError):
            tokenize("1 @ 2")


class TestParser(unittest.TestCase):
    def test_number_literal(self):
        self.assertIsInstance(parse("42"), NumberLit)
        self.assertEqual(parse("42").value, 42)
        self.assertEqual(parse("3.5").value, 3.5)

    def test_string_literal(self):
        node = parse('"hi"')
        self.assertIsInstance(node, StringLit)
        self.assertEqual(node.value, "hi")

    def test_bool_literal_case_insensitive(self):
        self.assertTrue(parse("true").value)
        self.assertFalse(parse("FALSE").value)

    def test_cell_ref(self):
        node = parse("A1")
        self.assertIsInstance(node, CellRef)
        self.assertEqual((node.row, node.col), (1, 1))

    def test_cell_ref_lowercase(self):
        node = parse("b12")
        self.assertEqual((node.row, node.col), (12, 2))

    def test_absolute_ref(self):
        node = parse("$A$1")
        self.assertEqual((node.row, node.col), (1, 1))

    def test_range_ref(self):
        node = parse("A1:B10")
        self.assertIsInstance(node, RangeRef)
        self.assertEqual((node.start.row, node.start.col), (1, 1))
        self.assertEqual((node.end.row, node.end.col), (10, 2))

    def test_sheet_qualified_ref(self):
        node = parse("Data!A1")
        self.assertEqual(node.sheet, "Data")

    def test_sheet_qualified_range(self):
        node = parse("Data!A1:B2")
        self.assertIsInstance(node, RangeRef)
        self.assertEqual(node.sheet, "Data")

    def test_function_call(self):
        node = parse("SUM(A1,B1,10)")
        self.assertIsInstance(node, FuncCall)
        self.assertEqual(node.name, "SUM")
        self.assertEqual(len(node.args), 3)

    def test_function_call_no_args(self):
        node = parse("NOW()")
        self.assertEqual(node.args, [])

    def test_unknown_bareword_is_nameref(self):
        node = parse("bogus")
        self.assertIsInstance(node, NameRef)

    def test_precedence_mul_over_add(self):
        node = parse("1+2*3")
        self.assertIsInstance(node, BinOp)
        self.assertEqual(node.op, "+")
        self.assertIsInstance(node.right, BinOp)
        self.assertEqual(node.right.op, "*")

    def test_precedence_power_over_unary(self):
        # -2^2 should parse as -(2^2), matching this engine's documented
        # math-convention choice (unlike real Excel's -2^2 = 4).
        node = parse("-2^2")
        self.assertIsInstance(node, UnaryOp)
        self.assertEqual(node.op, "-")
        self.assertIsInstance(node.operand, BinOp)
        self.assertEqual(node.operand.op, "^")

    def test_power_right_associative(self):
        node = parse("2^3^2")
        self.assertEqual(node.op, "^")
        self.assertIsInstance(node.right, BinOp)  # 2^(3^2), not (2^3)^2

    def test_percent_postfix(self):
        node = parse("50%")
        self.assertIsInstance(node, UnaryOp)
        self.assertEqual(node.op, "%")

    def test_parens(self):
        node = parse("(1+2)*3")
        self.assertEqual(node.op, "*")
        self.assertIsInstance(node.left, BinOp)
        self.assertEqual(node.left.op, "+")

    def test_string_concat_and_comparison_precedence(self):
        node = parse('1+1&"x"="2x"')
        self.assertEqual(node.op, "=")

    def test_unbalanced_parens_raises(self):
        with self.assertRaises(ParseError):
            parse("(1+2")

    def test_trailing_garbage_raises(self):
        with self.assertRaises(ParseError):
            parse("1 2")

    def test_empty_formula_raises(self):
        with self.assertRaises(ParseError):
            parse("")

    def test_deep_paren_nesting_raises_cleanly(self):
        formula = "(" * 500 + "1" + ")" * 500
        with self.assertRaises(ParseError):
            parse(formula)

    def test_moderate_paren_nesting_still_works(self):
        formula = "(" * 30 + "1" + ")" * 30
        self.assertEqual(parse(formula).value, 1)

    def test_deep_unary_chain_raises_cleanly(self):
        with self.assertRaises(ParseError):
            parse("-" * 500 + "1")

    def test_deep_power_chain_raises_cleanly(self):
        with self.assertRaises(ParseError):
            parse("^".join(["2"] * 500))

    def test_long_flat_chain_parses_without_recursion(self):
        # The +/- production is iterative, not recursive, so this must
        # succeed at parse time even though it's a deep tree once built.
        node = parse("+".join(["1"] * 3000))
        self.assertIsInstance(node, BinOp)


if __name__ == "__main__":
    unittest.main()
