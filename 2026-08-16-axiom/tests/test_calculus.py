import random
import unittest

from axiom import parse, sym, differentiate
from axiom.calculus import integrate
from axiom.errors import AxiomError

x = sym("x")


def central_diff(expr, xv, h=1e-6):
    f = lambda v: expr.evalf({"x": v}).real
    return (f(xv + h) - f(xv - h)) / (2 * h)


def simpson(f, a, b, n=4000):
    if n % 2:
        n += 1
    h = (b - a) / n
    s = f(a) + f(b)
    for i in range(1, n):
        s += (4 if i % 2 else 2) * f(a + i * h)
    return s * h / 3


class TestDifferentiationRules(unittest.TestCase):
    def test_power_rule(self):
        self.assertEqual(str(differentiate(parse("x^5"), x)), "5*x^4")

    def test_sum_rule(self):
        self.assertEqual(str(differentiate(parse("x^2 + 3*x + 1"), x)), "2*x + 3")

    def test_product_rule(self):
        self.assertEqual(str(differentiate(parse("x*sin(x)"), x)), "x*cos(x) + sin(x)")

    def test_chain_rule(self):
        self.assertEqual(str(differentiate(parse("sin(x^2)"), x)), "2*x*cos(x^2)")

    def test_quotient_via_negative_power(self):
        d = differentiate(parse("1/x"), x)
        self.assertEqual(str(d), "-1/x^2")

    def test_exponential_rule(self):
        self.assertEqual(str(differentiate(parse("2^x"), x)), "2^x*log(2)")

    def test_generalized_power_rule(self):
        d = differentiate(parse("x^x"), x)
        self.assertEqual(str(d), "x^x*(log(x) + 1)")

    def test_constant_derivative_is_zero(self):
        self.assertEqual(str(differentiate(parse("5"), x)), "0")

    def test_all_builtin_functions_have_correct_derivative_via_finite_diff(self):
        random.seed(11)
        exprs = ["sin(x)", "cos(x)", "tan(x)", "exp(x)", "log(x+3)", "sqrt(x+3)",
                 "abs(x-5)", "asin(x/3)", "acos(x/3)", "atan(x)", "sinh(x)",
                 "cosh(x)", "tanh(x)"]
        for es in exprs:
            e = parse(es)
            d = differentiate(e, x)
            for _ in range(4):
                xv = random.uniform(-1.0, 1.0)
                analytic = d.evalf({"x": xv}).real
                numeric = central_diff(e, xv)
                self.assertAlmostEqual(analytic, numeric, places=3,
                                        msg=f"{es} at x={xv}")

    def test_trace_records_rules(self):
        trace = []
        differentiate(parse("x^2*sin(x)"), x, trace=trace)
        joined = " ".join(trace)
        self.assertIn("power rule", joined)
        self.assertIn("product rule", joined)
        self.assertIn("chain rule", joined)


class TestIntegration(unittest.TestCase):
    def _check_definite_integral(self, expr_str, a=0.15, b=1.3):
        e = parse(expr_str)
        F = integrate(e, x)
        f = lambda v: e.evalf({"x": v}).real
        numeric = simpson(f, a, b)
        exact = F.evalf({"x": b}).real - F.evalf({"x": a}).real
        self.assertAlmostEqual(numeric, exact, places=4, msg=expr_str)

    def test_power_rule(self):
        self._check_definite_integral("x^3 + 2*x")

    def test_linear_substitution(self):
        self._check_definite_integral("sin(3*x + 1)")
        self._check_definite_integral("(2*x+1)^3")
        self._check_definite_integral("1/(x+3)")

    def test_by_parts(self):
        self._check_definite_integral("x*exp(x)")
        self._check_definite_integral("x^2*cos(x)")

    def test_general_substitution(self):
        self._check_definite_integral("x/(x^2+1)")
        self._check_definite_integral("2*x*exp(x^2)")
        self._check_definite_integral("sin(x)*cos(x)")
        self._check_definite_integral("(2*x+1)/(x^2+x+1)")

    def test_arctan_arcsin_patterns(self):
        self.assertEqual(str(integrate(parse("1/(1+x^2)"), x)), "atan(x)")
        self.assertEqual(str(integrate(parse("1/(1-x^2)^(1/2)"), x)), "asin(x)")

    def test_every_result_differentiates_back(self):
        random.seed(3)
        for es in ["x^4", "sin(2*x)", "x*exp(x)", "x/(x^2+1)", "tan(x)",
                   "sinh(x)", "x^2*sin(3*x+1)"]:
            e = parse(es)
            F = integrate(e, x)
            d = differentiate(F, x)
            for _ in range(3):
                xv = random.uniform(0.2, 1.0)
                self.assertAlmostEqual(d.evalf({"x": xv}).real,
                                        e.evalf({"x": xv}).real, places=3, msg=es)

    def test_unsupported_integral_raises_clean_error(self):
        with self.assertRaises(AxiomError):
            integrate(parse("exp(x^2)"), x)

    def test_no_false_positive_substitution(self):
        # x is NOT a constant multiple of d/dx[x^3] = 3x^2 -- must stay unsupported.
        with self.assertRaises(AxiomError):
            integrate(parse("x*exp(x^3)"), x)

    def test_constant_integrand(self):
        self.assertEqual(str(integrate(parse("5"), x)), "5*x")


if __name__ == "__main__":
    unittest.main()
