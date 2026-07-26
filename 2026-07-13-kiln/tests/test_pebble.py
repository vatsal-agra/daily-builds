import unittest

from .helpers import run_pebble, compile_pebble, instantiate
from kiln.pebble.lexer import PebbleSyntaxError
from kiln.pebble.compiler import PebbleCompileError


class TestPebble(unittest.TestCase):
    def test_recursion(self):
        src = """
        fn fib(n) -> i32 {
            if (n < 2) { return n; }
            return fib(n - 1) + fib(n - 2);
        }
        """
        for n, want in enumerate([0, 1, 1, 2, 3, 5, 8, 13, 21, 34, 55]):
            self.assertEqual(run_pebble(src, "fib", [n]), [want])

    def test_while_loop_and_mutation(self):
        src = """
        fn sum_to(n) -> i32 {
            let total = 0;
            let i = 1;
            while (i <= n) {
                total = total + i;
                i = i + 1;
            }
            return total;
        }
        """
        self.assertEqual(run_pebble(src, "sum_to", [0]), [0])
        self.assertEqual(run_pebble(src, "sum_to", [1]), [1])
        self.assertEqual(run_pebble(src, "sum_to", [100]), [5050])

    def test_short_circuit_and_or(self):
        src = """
        fn f(a, b) -> i32 {
            if (a > 0 && b > 0) { return 1; }
            if (a > 0 || b > 0) { return 2; }
            return 0;
        }
        """
        self.assertEqual(run_pebble(src, "f", [1, 1]), [1])
        self.assertEqual(run_pebble(src, "f", [1, 0xFFFFFFFF]), [2])  # b = -1
        self.assertEqual(run_pebble(src, "f", [0, 0]), [0])

    def test_arithmetic_precedence(self):
        src = """
        fn f() -> i32 {
            return 2 + 3 * 4 - (1 + 1) * 2;
        }
        """
        self.assertEqual(run_pebble(src, "f", []), [10])  # 2+12-4

    def test_negative_literal_and_unary(self):
        src = """
        fn f(x) -> i32 {
            return -x + 5;
        }
        """
        self.assertEqual(run_pebble(src, "f", [3]), [2])

    def test_mutual_recursion(self):
        src = """
        fn is_even(n) -> i32 {
            if (n == 0) { return 1; }
            return is_odd(n - 1);
        }
        fn is_odd(n) -> i32 {
            if (n == 0) { return 0; }
            return is_even(n - 1);
        }
        """
        self.assertEqual(run_pebble(src, "is_even", [10]), [1])
        self.assertEqual(run_pebble(src, "is_even", [7]), [0])

    def test_print_calls_host_import(self):
        src = """
        fn f(x) -> i32 {
            print(x);
            print(x * 2);
            return 0;
        }
        """
        wasm_bytes, _ = compile_pebble(src)
        seen = []
        from kiln.wasm.interpreter import HostFunc, Instance
        from kiln.wasm.decoder import decode_module
        module = decode_module(wasm_bytes)
        imports = {"env": {"print": HostFunc(lambda x: (seen.append(x), [])[1], [0x7F], [])}}
        inst = Instance(module, imports)
        inst.call("f", [21])
        self.assertEqual(seen, [21, 42])

    def test_undefined_variable_raises(self):
        src = "fn f() -> i32 { return y; }"
        with self.assertRaises(PebbleCompileError):
            compile_pebble(src)

    def test_undefined_function_call_raises(self):
        src = "fn f() -> i32 { return g(); }"
        with self.assertRaises(PebbleCompileError):
            compile_pebble(src)

    def test_syntax_error_raises(self):
        src = "fn f( -> i32 { return 1; }"
        with self.assertRaises(PebbleSyntaxError):
            compile_pebble(src)

    def test_division_by_zero_traps(self):
        from kiln.wasm.interpreter import WasmTrap
        src = "fn f(x) -> i32 { return 10 / x; }"
        with self.assertRaises(WasmTrap):
            run_pebble(src, "f", [0])

    def test_modulo(self):
        src = "fn f(a, b) -> i32 { return a % b; }"
        self.assertEqual(run_pebble(src, "f", [17, 5]), [2])


if __name__ == "__main__":
    unittest.main()
