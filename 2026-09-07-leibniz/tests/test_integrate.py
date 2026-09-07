import random
import unittest

from leibniz.diff import diff
from leibniz.expr import evalf
from leibniz.integrate import CannotIntegrate, integrate
from leibniz.parser import parse
from leibniz.render import to_str


class TestIntegrateRules(unittest.TestCase):
    def test_power_rule(self):
        self.assertEqual(to_str(integrate(parse("x^3"), "x")), "1/4*x^4")

    def test_power_rule_minus_one_is_ln(self):
        self.assertEqual(to_str(integrate(parse("1/x"), "x")), "ln(abs(x))")

    def test_constant(self):
        self.assertEqual(to_str(integrate(parse("5"), "x")), "5*x")

    def test_sum_rule(self):
        self.assertEqual(to_str(integrate(parse("x + 1"), "x")), "1/2*x^2 + x")

    def test_affine_trig_and_exp(self):
        self.assertEqual(to_str(integrate(parse("sin(2*x+1)"), "x")), "-1/2*cos(2*x + 1)")
        self.assertEqual(to_str(integrate(parse("cos(3*x)"), "x")), "1/3*sin(3*x)")
        self.assertEqual(to_str(integrate(parse("exp(-2*x)"), "x")), "-1/2*exp(-2*x)")

    def test_exponential_base_rule(self):
        self.assertEqual(to_str(integrate(parse("2^x"), "x")), "2^x/ln(2)")

    def test_tabular_by_parts(self):
        result = integrate(parse("x^2*exp(x)"), "x")
        self.assertEqual(to_str(result), "exp(x)*x^2 - 2*x*exp(x) + 2*exp(x)")

    def test_cannot_integrate_raises_cleanly(self):
        with self.assertRaises(CannotIntegrate):
            integrate(parse("exp(x^2)"), "x")
        with self.assertRaises(CannotIntegrate):
            integrate(parse("sin(x)*ln(x)"), "x")


class TestIntegrateSelfConsistency(unittest.TestCase):
    """The real oracle: differentiate the antiderivative and check it
    matches the original integrand numerically."""

    def test_diff_of_integral_matches_integrand(self):
        random.seed(99)
        cases = [
            "x^3", "1/x", "sin(3*x+1)", "cos(x)", "exp(-2*x)", "x^2*exp(x)",
            "x*sin(x)", "x^2*cos(2*x)", "ln(x)", "sqrt(x)", "1/(2*x+3)",
            "tan(x)", "5", "3*x+2", "x^3*exp(-x)", "x^2*sin(x)+x*cos(x)",
        ]
        for s in cases:
            e = parse(s)
            big_f = integrate(e, "x")
            d = diff(big_f, "x")
            for _ in range(4):
                xv = random.uniform(0.4, 1.7)
                a = evalf(d, {"x": xv})
                b = evalf(e, {"x": xv})
                self.assertAlmostEqual(a, b, delta=1e-4 * max(1, abs(b)), msg=s)


if __name__ == "__main__":
    unittest.main()
