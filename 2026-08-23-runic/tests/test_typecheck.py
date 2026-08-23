import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.lexer import tokenize
from compiler.parser import parse
from compiler.typecheck import check, SemanticError


def checked(src):
    return check(parse(tokenize(src)))


class TypecheckTests(unittest.TestCase):
    def test_valid_program_passes(self):
        c = checked("fn f(a, b) { return a + b; }")
        self.assertIn("f", c.funcs_by_name)
        self.assertEqual(c.funcs_by_name["f"].arity, 2)

    def test_undeclared_variable(self):
        with self.assertRaisesRegex(SemanticError, "undeclared variable"):
            checked("fn f() { return x; }")

    def test_undeclared_function_call(self):
        with self.assertRaisesRegex(SemanticError, "undeclared function"):
            checked("fn f() { return g(); }")

    def test_arity_mismatch(self):
        with self.assertRaisesRegex(SemanticError, "expects 2 argument"):
            checked("fn g(a, b) { return a + b; } fn f() { return g(1); }")

    def test_duplicate_function(self):
        with self.assertRaisesRegex(SemanticError, "more than once"):
            checked("fn f() { return 1; } fn f() { return 2; }")

    def test_duplicate_param(self):
        with self.assertRaisesRegex(SemanticError, "duplicate parameter"):
            checked("fn f(a, a) { return a; }")

    def test_redeclared_let(self):
        with self.assertRaisesRegex(SemanticError, "already declared"):
            checked("fn f() { let x = 1; let x = 2; return x; }")

    def test_missing_return_path(self):
        with self.assertRaisesRegex(SemanticError, "does not return on every path"):
            checked("fn f(a) { if (a > 0) { return 1; } }")

    def test_return_in_both_branches_ok(self):
        checked("fn f(a) { if (a > 0) { return 1; } else { return 0; } }")  # should not raise

    def test_while_alone_does_not_satisfy_return(self):
        with self.assertRaisesRegex(SemanticError, "does not return on every path"):
            checked("fn f(a) { while (a > 0) { a = a - 1; } }")

    def test_unreachable_code_after_return(self):
        with self.assertRaisesRegex(SemanticError, "unreachable code"):
            checked("fn f() { return 1; let x = 2; }")

    def test_undeclared_array(self):
        with self.assertRaisesRegex(SemanticError, "not a declared array"):
            checked("fn f() { return arr[0]; }")

    def test_array_and_function_name_collision(self):
        with self.assertRaisesRegex(SemanticError, "both a function and an array"):
            checked("array f[4]; fn f() { return 0; }")

    def test_assign_to_undeclared_variable(self):
        with self.assertRaisesRegex(SemanticError, "undeclared variable"):
            checked("fn f() { x = 1; return 0; }")

    def test_empty_program_rejected(self):
        with self.assertRaisesRegex(SemanticError, "at least one function"):
            checked("")

    def test_recursion_allowed(self):
        checked("fn fib(n) { if (n < 2) { return n; } return fib(n-1) + fib(n-2); }")

    def test_forward_reference_allowed(self):
        # f calls g, which is declared *after* f — must work (two-pass sig collection)
        checked("fn f() { return g(); } fn g() { return 1; }")


if __name__ == "__main__":
    unittest.main()
