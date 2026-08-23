import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.lexer import tokenize
from compiler.parser import parse, ParseError
from compiler import ast_nodes as A


def p(src):
    return parse(tokenize(src))


class ParserTests(unittest.TestCase):
    def test_simple_function(self):
        prog = p("fn f(a, b) { return a + b; }")
        self.assertEqual(len(prog.funcs), 1)
        fn = prog.funcs[0]
        self.assertEqual(fn.name, "f")
        self.assertEqual(fn.params, ["a", "b"])
        self.assertEqual(len(fn.body.stmts), 1)
        self.assertIsInstance(fn.body.stmts[0], A.ReturnStmt)

    def test_array_decl_with_initializer(self):
        prog = p("array buf[4] = {1, 2, 3}; fn f() { return 0; }")
        self.assertEqual(len(prog.arrays), 1)
        arr = prog.arrays[0]
        self.assertEqual(arr.name, "buf")
        self.assertEqual(arr.size, 4)
        self.assertEqual(arr.init, [1, 2, 3])

    def test_operator_precedence(self):
        prog = p("fn f() { return 1 + 2 * 3; }")
        ret = prog.funcs[0].body.stmts[0]
        top = ret.expr
        self.assertIsInstance(top, A.BinOp)
        self.assertEqual(top.op, "+")
        self.assertIsInstance(top.right, A.BinOp)
        self.assertEqual(top.right.op, "*")

    def test_if_else_chain(self):
        prog = p("fn f(a) { if (a > 0) { return 1; } else if (a < 0) { return -1; } else { return 0; } }")
        stmt = prog.funcs[0].body.stmts[0]
        self.assertIsInstance(stmt, A.IfStmt)
        self.assertIsNotNone(stmt.else_block)

    def test_array_index_and_assignment(self):
        prog = p("array a[4]; fn f() { a[0] = a[1] + 1; return 0; }")
        assign = prog.funcs[0].body.stmts[0]
        self.assertIsInstance(assign, A.AssignStmt)
        self.assertIsInstance(assign.target, A.Index)

    def test_call_parsing(self):
        prog = p("fn g(x) { return x; } fn f() { return g(1 + 2); }")
        ret = prog.funcs[1].body.stmts[0]
        self.assertIsInstance(ret.expr, A.Call)
        self.assertEqual(ret.expr.name, "g")
        self.assertEqual(len(ret.expr.args), 1)

    def test_assert_statement(self):
        prog = p("fn f(x) { assert(x > 0); return x; }")
        stmt = prog.funcs[0].body.stmts[0]
        self.assertIsInstance(stmt, A.AssertStmt)

    def test_missing_semicolon_raises(self):
        with self.assertRaises(ParseError):
            p("fn f() { return 1 }")

    def test_invalid_assignment_target_raises(self):
        with self.assertRaises(ParseError):
            p("fn f() { 1 = 2; return 0; }")

    def test_missing_function_body_raises(self):
        with self.assertRaises(ParseError):
            p("fn f()")

    def test_unary_and_not(self):
        prog = p("fn f(a) { return !(-a == 0); }")
        ret = prog.funcs[0].body.stmts[0]
        self.assertIsInstance(ret.expr, A.UnaryOp)
        self.assertEqual(ret.expr.op, "!")


if __name__ == "__main__":
    unittest.main()
