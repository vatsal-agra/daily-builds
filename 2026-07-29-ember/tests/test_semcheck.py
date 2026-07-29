"""Regression tests for the 4 bugs found during Phase 3 adversarial
review -- see REVIEW.md. Each one is checked against *both* backends,
since the original bugs were specifically about the two backends
disagreeing with each other."""

import unittest

from ember.parser import parse
from ember.interpreter import Interpreter
from ember.codegen_x64 import compile_program
from ember.semcheck import SemanticError


class TestSemanticChecks(unittest.TestCase):
    def test_undeclared_var_in_untaken_branch_rejected_by_both_backends(self):
        # REVIEW.md #1: interpreter used to silently return 1 here (never
        # walks the untaken branch); JIT used to raise. Both must now
        # reject the program itself, regardless of which branch runs.
        program = parse("fn f(x) { if (x > 100) { y = 5; } return x; }")
        with self.assertRaises(SemanticError):
            Interpreter(program)
        with self.assertRaises(SemanticError):
            compile_program(program)

    def test_duplicate_function_rejected(self):
        # REVIEW.md #2: used to raise a raw AssertionError from the JIT.
        program = parse("fn foo(x) { return x; }\nfn foo(x) { return x + 1; }\n")
        with self.assertRaises(SemanticError):
            Interpreter(program)
        with self.assertRaises(SemanticError):
            compile_program(program)

    def test_call_to_undefined_function_rejected(self):
        # REVIEW.md #3: used to raise a raw KeyError from the JIT.
        program = parse("fn f(x) { return g(x); }")
        with self.assertRaises(SemanticError):
            Interpreter(program)
        with self.assertRaises(SemanticError):
            compile_program(program)

    def test_call_with_wrong_arity_rejected_statically(self):
        program = parse("fn g(a, b) { return a + b; }\nfn f(x) { return g(x); }\n")
        with self.assertRaises(SemanticError):
            Interpreter(program)

    def test_deeply_nested_expression_rejected_cleanly(self):
        # REVIEW.md #4: used to raise a raw RecursionError from both backends.
        chain = " + ".join(["1"] * 3000)
        program = parse(f"fn f() {{ return {chain}; }}")
        with self.assertRaises(SemanticError):
            Interpreter(program)
        with self.assertRaises(SemanticError):
            compile_program(program)

    def test_sequential_non_nested_statements_do_not_trip_the_depth_cap(self):
        lines = [f"let v{i} = {i};" for i in range(1000)]
        lines.append("return v999;")
        program = parse("fn f() {\n" + "\n".join(lines) + "\n}\n")
        self.assertEqual(Interpreter(program).call("f", []), 999)
        self.assertEqual(compile_program(program).call("f", []), 999)

    def test_valid_program_passes(self):
        program = parse("fn f(x) { let y = x + 1; return y; }")
        Interpreter(program)  # must not raise
        compile_program(program)  # must not raise


if __name__ == "__main__":
    unittest.main()
