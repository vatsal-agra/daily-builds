import unittest
from ember.parser import parse
from ember.interpreter import Interpreter, wrap64, c_div, c_mod
from ember.errors import EmberRuntimeError

INT64_MIN = -(2 ** 63)
INT64_MAX = 2 ** 63 - 1


class TestWrap64(unittest.TestCase):
    def test_in_range_unchanged(self):
        self.assertEqual(wrap64(0), 0)
        self.assertEqual(wrap64(INT64_MAX), INT64_MAX)
        self.assertEqual(wrap64(INT64_MIN), INT64_MIN)

    def test_overflow_wraps_like_twos_complement(self):
        self.assertEqual(wrap64(INT64_MAX + 1), INT64_MIN)
        self.assertEqual(wrap64(2 ** 64), 0)
        self.assertEqual(wrap64(-(2 ** 63) - 1), INT64_MAX)


class TestTruncatingDivision(unittest.TestCase):
    def test_matches_c_truncation_toward_zero(self):
        # -7 / 2 == -3 in C (truncate toward zero), not -4 (Python's floor div)
        self.assertEqual(c_div(-7, 2), -3)
        self.assertEqual(c_div(7, -2), -3)
        self.assertEqual(c_div(-7, -2), 3)
        self.assertEqual(c_div(7, 2), 3)

    def test_mod_sign_matches_dividend(self):
        self.assertEqual(c_mod(-7, 2), -1)
        self.assertEqual(c_mod(7, -2), 1)
        self.assertEqual(c_mod(-7, -2), -1)

    def test_div_mod_identity(self):
        for a, b in [(17, 5), (-17, 5), (17, -5), (-17, -5)]:
            self.assertEqual(c_div(a, b) * b + c_mod(a, b), a)

    def test_division_by_zero_raises(self):
        with self.assertRaises(EmberRuntimeError):
            c_div(5, 0)
        with self.assertRaises(EmberRuntimeError):
            c_mod(5, 0)

    def test_int64_min_over_neg1_raises(self):
        with self.assertRaises(EmberRuntimeError):
            c_div(INT64_MIN, -1)


class TestInterpreterControlFlow(unittest.TestCase):
    def _call(self, src, fn, args):
        return Interpreter(parse(src)).call(fn, args)

    def test_if_else(self):
        src = "fn f(x) { if (x > 0) { return 1; } else { return -1; } }"
        self.assertEqual(self._call(src, "f", [5]), 1)
        self.assertEqual(self._call(src, "f", [-5]), -1)

    def test_while_loop(self):
        src = "fn f(n) { let acc = 0; while (n > 0) { acc = acc + n; n = n - 1; } return acc; }"
        self.assertEqual(self._call(src, "f", [5]), 15)

    def test_recursion(self):
        src = "fn f(n) { if (n <= 1) { return 1; } return n * f(n - 1); }"
        self.assertEqual(self._call(src, "f", [5]), 120)

    def test_falls_off_end_returns_zero(self):
        src = "fn f() { let x = 1; }"
        self.assertEqual(self._call(src, "f", []), 0)

    def test_short_circuit_and_skips_right_side_effect(self):
        # if && weren't short-circuiting, this would divide by zero
        src = "fn f(a, b) { return a != 0 && (b / a) > 1; }"
        self.assertEqual(self._call(src, "f", [0, 5]), 0)

    def test_short_circuit_or_skips_right_side_effect(self):
        src = "fn f(a, b) { return a == 0 || (b / a) > 1; }"
        self.assertEqual(self._call(src, "f", [0, 5]), 1)

    def test_wrong_arg_count_raises(self):
        src = "fn f(a, b) { return a + b; }"
        with self.assertRaises(EmberRuntimeError):
            self._call(src, "f", [1])


if __name__ == "__main__":
    unittest.main()
