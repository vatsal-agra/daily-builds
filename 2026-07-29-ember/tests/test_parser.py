import unittest
from ember.parser import parse, ParseError
from ember.ast_nodes import BinOp, IntLit, UnaryOp, VarRef


class TestParser(unittest.TestCase):
    def test_precedence_mul_over_add(self):
        prog = parse("fn f() { return 2 + 3 * 4; }")
        expr = prog.functions[0].body.stmts[0].expr
        self.assertEqual(expr.op, "+")
        self.assertIsInstance(expr.right, BinOp)
        self.assertEqual(expr.right.op, "*")

    def test_left_associativity_of_subtraction(self):
        # a - b - c must parse as (a - b) - c, not a - (b - c)
        prog = parse("fn f(a,b,c) { return a - b - c; }")
        expr = prog.functions[0].body.stmts[0].expr
        self.assertEqual(expr.op, "-")
        self.assertIsInstance(expr.left, BinOp)
        self.assertEqual(expr.left.op, "-")
        self.assertIsInstance(expr.right, VarRef)
        self.assertEqual(expr.right.name, "c")

    def test_comparison_binds_looser_than_additive(self):
        prog = parse("fn f(a,b) { return a + 1 < b - 1; }")
        expr = prog.functions[0].body.stmts[0].expr
        self.assertEqual(expr.op, "<")
        self.assertEqual(expr.left.op, "+")
        self.assertEqual(expr.right.op, "-")

    def test_and_binds_tighter_than_or(self):
        prog = parse("fn f(a,b,c) { return a || b && c; }")
        expr = prog.functions[0].body.stmts[0].expr
        self.assertEqual(expr.op, "||")
        self.assertEqual(expr.right.op, "&&")

    def test_parenthesized_overrides_precedence(self):
        prog = parse("fn f() { return (2 + 3) * 4; }")
        expr = prog.functions[0].body.stmts[0].expr
        self.assertEqual(expr.op, "*")
        self.assertEqual(expr.left.op, "+")

    def test_unary_minus_and_not(self):
        prog = parse("fn f(x) { return -!x; }")
        expr = prog.functions[0].body.stmts[0].expr
        self.assertIsInstance(expr, UnaryOp)
        self.assertEqual(expr.op, "-")
        self.assertEqual(expr.operand.op, "!")

    def test_else_if_chain(self):
        prog = parse("""
        fn f(x) {
            if (x == 1) { return 1; }
            else if (x == 2) { return 2; }
            else { return 3; }
        }
        """)
        stmt = prog.functions[0].body.stmts[0]
        self.assertIsNotNone(stmt.else_block)
        nested_if = stmt.else_block.stmts[0]
        self.assertEqual(nested_if.__class__.__name__, "IfStmt")

    def test_call_with_args(self):
        prog = parse("fn f() { return g(1, 2+3); }")
        call = prog.functions[0].body.stmts[0].expr
        self.assertEqual(call.name, "g")
        self.assertEqual(len(call.args), 2)

    def test_too_many_params_rejected(self):
        with self.assertRaises(ParseError):
            parse("fn f(a,b,c,d,e,f,g) { return a; }")

    def test_duplicate_params_rejected(self):
        with self.assertRaises(ParseError):
            parse("fn f(a,a) { return a; }")

    def test_too_many_call_args_rejected(self):
        with self.assertRaises(ParseError):
            parse("fn f() { return g(1,2,3,4,5,6,7); }")

    def test_unterminated_block_rejected(self):
        with self.assertRaises(ParseError):
            parse("fn f() { return 1;")

    def test_missing_semicolon_rejected(self):
        with self.assertRaises(ParseError):
            parse("fn f() { return 1 }")

    def test_bool_literals(self):
        prog = parse("fn f() { return true; }")
        lit = prog.functions[0].body.stmts[0].expr
        self.assertTrue(lit.value)

    def test_error_message_has_line_col(self):
        try:
            parse("fn f() {\n  return 1\n}")
            self.fail("expected ParseError")
        except ParseError as e:
            self.assertEqual(e.line, 3)


if __name__ == "__main__":
    unittest.main()
