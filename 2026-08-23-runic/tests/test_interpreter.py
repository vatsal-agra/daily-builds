import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from compiler.frontend import compile_source, CompileError
from compiler.interpreter import Instance, WasmTrap


def run(src, func, args):
    inst = Instance(compile_source(src).wasm_bytes)
    return inst.call_by_name(func, args)


class InterpreterTests(unittest.TestCase):
    def test_arithmetic(self):
        src = "fn f(a, b) { return a * b + a - b; }"
        self.assertEqual(run(src, "f", [3, 4]), 3 * 4 + 3 - 4)

    def test_recursion_fib(self):
        src = "fn fib(n) { if (n < 2) { return n; } return fib(n-1)+fib(n-2); }"
        self.assertEqual(run(src, "fib", [15]), 610)

    def test_while_loop(self):
        src = "fn f(n) { let s = 0; let i = 0; while (i < n) { s = s + i; i = i + 1; } return s; }"
        self.assertEqual(run(src, "f", [100]), sum(range(100)))

    def test_nested_loops_regression(self):
        # Regression test for the control-flow frame-leak bug (REVIEW.md #1):
        # an if with no else, nested two while-loops deep, must not corrupt
        # later branch depth math.
        src = """
        fn count_if(n) {
            let total = 0;
            let i = 0;
            while (i < n) {
                let j = 0;
                while (j < n) {
                    if (j > i) {
                        total = total + 1;
                    }
                    j = j + 1;
                }
                i = i + 1;
            }
            return total;
        }
        """
        for n in range(0, 8):
            expected = sum(1 for i in range(n) for j in range(n) if j > i)
            self.assertEqual(run(src, "count_if", [n]), expected, f"n={n}")

    def test_literal_wraparound_regression(self):
        # Regression test for the non-canonical LEB128 bug (REVIEW.md #2).
        src = "fn f() { return 4294967295; }"
        self.assertEqual(run(src, "f", []), -1)

    def test_short_circuit_and_skips_rhs(self):
        src = """
        array flag[1];
        fn side(v) { flag[0] = v; return 1; }
        fn test(a) { if (a > 0 && side(1) == 1) { return 1; } return 0; }
        fn get() { return flag[0]; }
        """
        inst = Instance(compile_source(src).wasm_bytes)
        inst.call_by_name("test", [-1])
        self.assertEqual(inst.call_by_name("get", []), 0, "RHS must not run when LHS is false")
        inst.call_by_name("test", [1])
        self.assertEqual(inst.call_by_name("get", []), 1, "RHS must run when LHS is true")

    def test_short_circuit_or_skips_rhs(self):
        src = """
        array flag[1];
        fn side(v) { flag[0] = v; return 1; }
        fn test(a) { if (a > 0 || side(1) == 1) { return 1; } return 0; }
        fn get() { return flag[0]; }
        """
        inst = Instance(compile_source(src).wasm_bytes)
        inst.call_by_name("test", [1])
        self.assertEqual(inst.call_by_name("get", []), 0, "RHS must not run when LHS is true")

    def test_array_read_write(self):
        src = "array a[5]; fn set(i, v) { a[i] = v; return 0; } fn get(i) { return a[i]; }"
        inst = Instance(compile_source(src).wasm_bytes)
        for i in range(5):
            inst.call_by_name("set", [i, i * i])
        self.assertEqual([inst.call_by_name("get", [i]) for i in range(5)], [0, 1, 4, 9, 16])

    def test_array_initializer_data_segment(self):
        src = "array a[3] = {7, 8, 9}; fn get(i) { return a[i]; }"
        inst = Instance(compile_source(src).wasm_bytes)
        self.assertEqual([inst.call_by_name("get", [i]) for i in range(3)], [7, 8, 9])

    def test_div_by_zero_traps(self):
        src = "fn f(a, b) { return a / b; }"
        inst = Instance(compile_source(src).wasm_bytes)
        with self.assertRaises(WasmTrap):
            inst.call_by_name("f", [1, 0])

    def test_int_min_div_neg_one_traps(self):
        src = "fn f(a, b) { return a / b; }"
        inst = Instance(compile_source(src).wasm_bytes)
        with self.assertRaises(WasmTrap):
            inst.call_by_name("f", [-2147483648, -1])

    def test_int_min_rem_neg_one_is_zero_no_trap(self):
        src = "fn f(a, b) { return a % b; }"
        self.assertEqual(run(src, "f", [-2147483648, -1]), 0)

    def test_signed_division_truncates_toward_zero(self):
        src = "fn f(a, b) { return a / b; }"
        self.assertEqual(run(src, "f", [-7, 2]), -3)
        self.assertEqual(run(src, "f", [7, -2]), -3)

    def test_assert_pass(self):
        src = "fn f(x) { assert(x > 0); return x; }"
        self.assertEqual(run(src, "f", [5]), 5)

    def test_assert_fail_traps(self):
        src = "fn f(x) { assert(x > 0); return x; }"
        inst = Instance(compile_source(src).wasm_bytes)
        with self.assertRaises(WasmTrap):
            inst.call_by_name("f", [-1])

    def test_out_of_bounds_memory_traps(self):
        src = "array a[4]; fn f(i) { return a[i]; }"
        inst = Instance(compile_source(src).wasm_bytes)
        with self.assertRaises(WasmTrap):
            inst.call_by_name("f", [100000])

    def test_deep_recursion_traps_cleanly(self):
        src = "fn f(n) { if (n == 0) { return 0; } return 1 + f(n - 1); }"
        inst = Instance(compile_source(src).wasm_bytes)
        with self.assertRaises(WasmTrap):
            inst.call_by_name("f", [1000000])

    def test_unary_negation_and_not(self):
        src = "fn f(a) { return -a; } fn g(a) { return !a; }"
        self.assertEqual(run(src, "f", [5]), -5)
        self.assertEqual(run(src, "g", [0]), 1)
        self.assertEqual(run(src, "g", [7]), 0)

    def test_compile_error_on_bad_syntax(self):
        with self.assertRaises(CompileError):
            compile_source("fn f( { return 1; }")

    def test_wasm_bytes_have_correct_magic_and_version(self):
        wasm = compile_source("fn f() { return 0; }").wasm_bytes
        self.assertEqual(wasm[0:4], b"\x00asm")
        self.assertEqual(wasm[4:8], b"\x01\x00\x00\x00")


if __name__ == "__main__":
    unittest.main()
