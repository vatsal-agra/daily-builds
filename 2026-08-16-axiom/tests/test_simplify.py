import unittest

from axiom import parse, sym
from axiom.simplify import simplify

x, y = sym("x"), sym("y")


class TestPythagoreanIdentity(unittest.TestCase):
    def test_basic(self):
        self.assertEqual(simplify(parse("sin(x)^2 + cos(x)^2")), parse("1"))

    def test_with_extra_constant(self):
        self.assertEqual(simplify(parse("sin(x)^2 + cos(x)^2 + 5")), parse("6"))

    def test_scaled_by_common_coefficient(self):
        self.assertEqual(simplify(parse("3*sin(x)^2 + 3*cos(x)^2")), parse("3"))

    def test_mismatched_arguments_not_combined(self):
        result = simplify(parse("sin(x)^2 + cos(y)^2"))
        self.assertNotEqual(result, parse("1"))

    def test_mismatched_coefficients_not_combined(self):
        result = simplify(parse("2*sin(x)^2 + 3*cos(x)^2"))
        self.assertNotEqual(result, parse("1"))
        self.assertNotEqual(result, parse("5"))


class TestRationalReduction(unittest.TestCase):
    def test_cancels_common_factor(self):
        self.assertEqual(simplify(parse("(x^2-1)/(x-1)")), parse("x+1"))

    def test_full_cancellation_to_one(self):
        self.assertEqual(simplify(parse("(x-1)/(x-1)")), parse("1"))

    def test_no_common_factor_left_alone(self):
        e = parse("(x^2+1)/(x-2)")
        self.assertEqual(simplify(e), e)

    def test_leftover_constant_factor(self):
        self.assertEqual(simplify(parse("(2*x-2)/(x-1)")), parse("2"))

    def test_multivariable_denominator_skipped_gracefully(self):
        # simplify() shouldn't crash on a denominator/numerator that isn't a
        # single-variable polynomial pair -- it should just leave it alone.
        e = parse("(x*y - 1)/(x - 2)")
        result = simplify(e)
        self.assertIsNotNone(result)


class TestReturnsCanonical(unittest.TestCase):
    def test_simplify_of_already_canonical_is_idempotent(self):
        e = parse("2*x + 3")
        self.assertEqual(simplify(e), e)

    def test_trace_records_steps(self):
        trace = []
        simplify(parse("sin(x)^2 + cos(x)^2"), trace=trace)
        self.assertTrue(any("sin" in s or "cos" in s for s in trace))


if __name__ == "__main__":
    unittest.main()
