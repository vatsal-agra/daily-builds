import unittest

from engine import parser
from engine.ast_nodes import BinOp, CellRef, FuncCall, unparse


class TestParser(unittest.TestCase):
    def test_precedence_add_mul(self):
        ast = parser.parse_formula("1+2*3")
        self.assertEqual(unparse(ast), "1+2*3")
        self.assertIsInstance(ast, BinOp)
        self.assertEqual(ast.op, "+")

    def test_precedence_power_binds_tighter_than_unary_minus(self):
        # Excel: -2^2 == -4 (unary minus applies to the result of 2^2)
        ast = parser.parse_formula("-2^2")
        self.assertEqual(unparse(ast), "-2^2")

    def test_power_right_associative(self):
        ast = parser.parse_formula("2^3^2")
        # 2^(3^2) = 512, not (2^3)^2 = 64
        from engine.evaluator import evaluate, EvalContext
        self.assertEqual(_eval_no_ctx(ast), 512.0)

    def test_percent_postfix(self):
        ast = parser.parse_formula("50%")
        self.assertEqual(_eval_no_ctx(ast), 0.5)

    def test_concat_lower_precedence_than_arithmetic(self):
        ast = parser.parse_formula('"x"&1+1')
        self.assertEqual(_eval_no_ctx(ast), "x2")

    def test_range_parses(self):
        ast = parser.parse_formula("SUM(A1:B2)")
        self.assertIsInstance(ast, FuncCall)
        self.assertEqual(unparse(ast), "SUM(A1:B2)")

    def test_absolute_refs_roundtrip(self):
        ast = parser.parse_formula("$A$1+A1")
        self.assertEqual(unparse(ast), "$A$1+A1")

    def test_sheet_qualified_ref(self):
        # Sheet names are case-sensitive and must round-trip exactly (unlike
        # function names, which are case-insensitive).
        ast = parser.parse_formula("Sheet2!A1+1")
        ref = ast.left
        self.assertIsInstance(ref, CellRef)
        self.assertEqual(ref.sheet, "Sheet2")

    def test_parenthesized_expression(self):
        ast = parser.parse_formula("(1+2)*3")
        self.assertEqual(_eval_no_ctx(ast), 9.0)

    def test_function_call_multiple_args(self):
        ast = parser.parse_formula("IF(1>0,2,3)")
        self.assertEqual(_eval_no_ctx(ast), 2)

    def test_trailing_garbage_raises(self):
        with self.assertRaises(parser.ParseError):
            parser.parse_formula("1+1)")

    def test_unclosed_paren_raises(self):
        with self.assertRaises(parser.ParseError):
            parser.parse_formula("(1+1")

    def test_unknown_name_not_ref_or_call_raises(self):
        with self.assertRaises(parser.ParseError):
            parser.parse_formula("FOO")


def _eval_no_ctx(ast):
    from engine.evaluator import evaluate

    class DummyCtx:
        sheet_name = "Sheet1"

        def get_value(self, sheet, row, col):
            return None

        def get_range(self, sheet, r1, c1, r2, c2):
            raise AssertionError("no refs expected")

    return evaluate(ast, DummyCtx())


if __name__ == "__main__":
    unittest.main()
