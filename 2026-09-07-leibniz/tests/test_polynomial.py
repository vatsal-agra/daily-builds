import random
import unittest

from leibniz.expr import Num, Symbol, add, evalf, pow_
from leibniz.parser import parse
from leibniz.polynomial import NotPolynomial, expand, factor, simplify_rational
from leibniz.render import to_str
from leibniz.simplify import equal, simplify


class TestExpand(unittest.TestCase):
    def test_binomial(self):
        self.assertEqual(to_str(expand(parse("(x+1)*(x+2)"))), "x^2 + 3*x + 2")

    def test_power_of_binomial(self):
        self.assertEqual(to_str(expand(parse("(x+1)^3"))), "x^3 + 3*x^2 + 3*x + 1")

    def test_already_expanded_is_a_no_op(self):
        e = parse("x^2 + 1")
        self.assertEqual(expand(e), e)


class TestFactor(unittest.TestCase):
    def test_simple_quadratic(self):
        self.assertEqual(to_str(factor(parse("x^2 - 5*x + 6"))), "(x - 2)*(x - 3)")

    def test_pulls_out_gcd_and_clears_root_denominators(self):
        self.assertEqual(to_str(factor(parse("2*x^2 + 3*x + 1"))), "(x + 1)*(2*x + 1)")

    def test_common_variable_factor(self):
        self.assertEqual(to_str(factor(parse("x^3 - x"))), "x*(x - 1)*(x + 1)")

    def test_double_root(self):
        self.assertEqual(to_str(factor(parse("x^2 - 4*x + 4"))), "(x - 2)^2")

    def test_negative_leading_coefficient(self):
        self.assertEqual(to_str(factor(parse("-3*x - 9"))), "-3*(x + 3)")

    def test_zero_polynomial_does_not_crash(self):
        self.assertEqual(factor(parse("0*x")), Num(0))
        self.assertEqual(factor(parse("x - x")), Num(0))

    def test_constant_has_no_variable_to_factor(self):
        with self.assertRaises(NotPolynomial):
            factor(parse("5"))

    def test_multivariate_rejected(self):
        with self.assertRaises(NotPolynomial):
            factor(parse("x*y + 1"))

    def test_irrational_quadratic_remainder(self):
        f = factor(parse("x^4 - 1"))
        self.assertEqual(expand(f), parse("x^4-1"))


class TestFactorExpandFuzz(unittest.TestCase):
    def test_random_integer_polynomials_round_trip(self):
        random.seed(3)
        x = Symbol("x")
        checked = 0
        for _ in range(200):
            deg = random.randint(1, 5)
            coeffs = [random.randint(-6, 6) for _ in range(deg + 1)]
            if coeffs[-1] == 0:
                coeffs[-1] = 1
            e = add(*[Num(c) * pow_(x, Num(i)) for i, c in enumerate(coeffs)])
            if simplify(e) == Num(0):
                continue
            self.assertTrue(equal(expand(factor(e)), e), msg=to_str(e))
            checked += 1
        self.assertGreater(checked, 100)


class TestSimplifyRational(unittest.TestCase):
    def test_full_cancellation(self):
        self.assertEqual(to_str(simplify_rational(parse("(x^2-1)/(x-1)"))), "x + 1")

    def test_common_denominator(self):
        self.assertEqual(to_str(simplify_rational(parse("1/x + 1/(x+1)"))), "(2*x + 1)/(x^2 + x)")

    def test_partial_cancellation(self):
        self.assertEqual(to_str(simplify_rational(parse("(x^2-4)/(x^2-x-2)"))), "(x + 2)/(x + 1)")

    def test_leaves_non_rational_expressions_alone(self):
        e = parse("sin(x)/x")
        self.assertEqual(simplify_rational(e), e)

    def test_no_denominator_is_a_no_op(self):
        e = parse("x + 1")
        self.assertEqual(simplify_rational(e), e)

    def test_numerically_equivalent(self):
        random.seed(11)
        cases = ["(x^2-1)/(x-1)", "1/x + 1/(x+1)", "(x^2-4)/(x^2-x-2)",
                 "(x^3-1)/(x-1)", "2/(x+1) - 2/(x-1)"]
        for s in cases:
            e = parse(s)
            r = simplify_rational(e)
            for _ in range(5):
                xv = random.uniform(2.5, 6.0)
                self.assertAlmostEqual(evalf(e, {"x": xv}), evalf(r, {"x": xv}), places=6, msg=s)


if __name__ == "__main__":
    unittest.main()
