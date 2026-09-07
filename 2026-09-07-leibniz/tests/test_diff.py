import random
import unittest

from leibniz.diff import diff
from leibniz.expr import Symbol, evalf
from leibniz.parser import parse
from leibniz.render import to_str
from leibniz.simplify import equal


class TestDiffRules(unittest.TestCase):
    def test_constant(self):
        self.assertEqual(to_str(diff(parse("5"), "x")), "0")

    def test_power_rule(self):
        self.assertEqual(to_str(diff(parse("x^3"), "x")), "3*x^2")

    def test_wrt_other_symbol_is_zero(self):
        self.assertEqual(to_str(diff(parse("y"), "x")), "0")

    def test_sum_rule(self):
        self.assertEqual(to_str(diff(parse("x^2 + 3*x"), "x")), "2*x + 3")

    def test_product_rule(self):
        self.assertTrue(equal(diff(parse("x*sin(x)"), "x"), parse("sin(x)+x*cos(x)")))

    def test_quotient_via_division(self):
        self.assertTrue(equal(diff(parse("1/x"), "x"), parse("-1/x^2")))

    def test_chain_rule(self):
        self.assertTrue(equal(diff(parse("sin(x^2)"), "x"), parse("2*x*cos(x^2)")))

    def test_exponential_rule_constant_base(self):
        self.assertTrue(equal(diff(parse("2^x"), "x"), parse("ln(2)*2^x")))

    def test_generalized_power_rule(self):
        self.assertTrue(equal(diff(parse("x^x"), "x"), parse("x^x*(ln(x)+1)")))

    def test_ln_rule(self):
        self.assertTrue(equal(diff(parse("ln(x)"), "x"), parse("1/x")))

    def test_sqrt_rule(self):
        self.assertTrue(equal(diff(parse("sqrt(x)"), "x"), parse("1/(2*sqrt(x))")))

    def test_tan_rule(self):
        self.assertTrue(equal(diff(parse("tan(x)"), "x"), parse("1/cos(x)^2")))


class TestDiffFiniteDifference(unittest.TestCase):
    """Cross-check symbolic derivatives against numerical finite
    differences at random points -- an independent oracle, not just
    hand-checked expected strings."""

    def test_against_numeric_gradient(self):
        random.seed(2024)
        exprs = [
            "x^3 - 2*x^2 + x - 5",
            "sin(x)*cos(x)",
            "exp(2*x)*x",
            "ln(x+2)/x",
            "sqrt(x^2+1)",
            "x^x",
            "2^x",
            "tan(x)/2",
        ]
        for s in exprs:
            e = parse(s)
            d = diff(e, "x")
            for _ in range(6):
                xv = random.uniform(0.3, 2.0)
                h = 1e-6
                numeric = (evalf(e, {"x": xv + h}) - evalf(e, {"x": xv - h})) / (2 * h)
                exact = evalf(d, {"x": xv})
                self.assertAlmostEqual(numeric, exact, delta=1e-3 * max(1, abs(exact)),
                                        msg=f"{s} at x={xv}")


if __name__ == "__main__":
    unittest.main()
