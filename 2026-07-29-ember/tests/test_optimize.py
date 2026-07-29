import unittest

from ember.parser import parse
from ember.interpreter import Interpreter
from ember.codegen_x64 import compile_program
from ember.optimize import fold_constants
from ember.ast_nodes import IntLit
from ember.errors import EmberRuntimeError


class TestConstantFolding(unittest.TestCase):
    def test_arithmetic_folds_to_single_literal(self):
        program = parse("fn f() { return 2 + 3 * 4; }")
        folded = fold_constants(program)
        expr = folded.functions[0].body.stmts[0].expr
        self.assertIsInstance(expr, IntLit)
        self.assertEqual(expr.value, 14)

    def test_comparison_folds(self):
        program = parse("fn f() { return 3 < 5; }")
        folded = fold_constants(program)
        expr = folded.functions[0].body.stmts[0].expr
        self.assertIsInstance(expr, IntLit)
        self.assertEqual(expr.value, 1)

    def test_and_with_false_constant_drops_right_side_entirely(self):
        program = parse("fn f(x) { return 0 && (10 / x > 1); }")
        folded = fold_constants(program)
        expr = folded.functions[0].body.stmts[0].expr
        self.assertIsInstance(expr, IntLit)
        self.assertEqual(expr.value, 0)
        # with the division gone, this must not raise even for x == 0
        self.assertEqual(compile_program(folded).call("f", [0]), 0)

    def test_or_with_true_constant_drops_right_side_entirely(self):
        program = parse("fn f(x) { return 1 || (10 / x > 1); }")
        folded = fold_constants(program)
        expr = folded.functions[0].body.stmts[0].expr
        self.assertIsInstance(expr, IntLit)
        self.assertEqual(expr.value, 1)
        self.assertEqual(compile_program(folded).call("f", [0]), 1)

    def test_variable_reference_is_not_folded(self):
        program = parse("fn f(x) { return x + 1; }")
        folded = fold_constants(program)
        expr = folded.functions[0].body.stmts[0].expr
        self.assertEqual(expr.op, "+")  # not folded, x is not a constant

    def test_division_by_constant_zero_is_not_folded(self):
        program = parse("fn f() { return 5 / 0; }")
        folded = fold_constants(program)
        expr = folded.functions[0].body.stmts[0].expr
        self.assertEqual(expr.op, "/")  # left as a runtime op
        with self.assertRaises(EmberRuntimeError):
            compile_program(folded).call("f", [])
        with self.assertRaises(EmberRuntimeError):
            Interpreter(folded).call("f", [])

    def test_int64_min_over_neg1_is_not_folded(self):
        program = parse(f"fn f() {{ return ({-(2**63)}) / (0 - 1); }}")
        folded = fold_constants(program)
        with self.assertRaises(EmberRuntimeError):
            compile_program(folded).call("f", [])

    def test_folded_program_matches_original_across_recursive_function(self):
        program = parse("""
        fn fib(n) {
            let base = 2 - 1;
            if (n < base + 1) { return n; }
            return fib(n - 1) + fib(n - 2);
        }
        """)
        folded = fold_constants(program)
        for n in range(10):
            self.assertEqual(
                Interpreter(program).call("fib", [n]),
                compile_program(folded).call("fib", [n]),
            )

    def test_original_program_is_not_mutated(self):
        program = parse("fn f() { return 2 + 3; }")
        original_expr = program.functions[0].body.stmts[0].expr
        fold_constants(program)
        self.assertEqual(original_expr.op, "+")  # still unfolded


if __name__ == "__main__":
    unittest.main()
