import random
import unittest

from axiom import parse, sym
from axiom.polynomial import expand, factor, poly_gcd, poly_coeffs, poly_degree
from axiom.errors import AxiomError

x, y = sym("x"), sym("y")


class TestExpand(unittest.TestCase):
    def test_binomial_expansion(self):
        self.assertEqual(str(expand(parse("(x+1)^3"))), "x^3 + 3*x^2 + 3*x + 1")

    def test_distributes_products(self):
        self.assertEqual(expand(parse("(x+1)*(x-1)")), parse("x^2-1"))

    def test_nested_functions_expand_inside(self):
        self.assertEqual(expand(parse("sin((x+1)^2)")), parse("sin(x^2+2*x+1)"))

    def test_multivariate(self):
        self.assertEqual(expand(parse("(x+y)^2")), parse("x^2 + 2*x*y + y^2"))


class TestFactor(unittest.TestCase):
    def _check_reexpands(self, text, var=None):
        original = expand(parse(text))
        factored = factor(parse(text), var)
        self.assertEqual(expand(factored), original, msg=f"{text} -> {factored}")

    def test_simple_quadratic(self):
        self._check_reexpands("x^2 - 5*x + 6")
        self.assertEqual(set(str(factor(parse("x^2-5*x+6"), x)).replace("(", "").replace(")", "").split("*")),
                          {"x - 2", "x - 3"})

    def test_difference_of_squares_emerges_from_rational_roots(self):
        self._check_reexpands("x^2 - 4")

    def test_cubic_with_quadratic_remainder(self):
        self._check_reexpands("x^3 - 8")

    def test_negative_leading_coefficient(self):
        self._check_reexpands("-x^2 + 1")

    def test_fractional_coefficient_quadratic(self):
        self._check_reexpands("2*x^2 - 3*x + 1")

    def test_irreducible_quadratic_via_radical(self):
        self._check_reexpands("x^2 - 2")

    def test_repeated_root_multiplicity(self):
        f = factor(parse("x^2 - 4*x + 4"), x)
        self.assertEqual(str(f), "(x - 2)^2")

    def test_random_battery_reexpands_exactly(self):
        random.seed(17)
        for _ in range(15):
            deg = random.randint(1, 4)
            coeffs = [random.randint(-5, 5) for _ in range(deg)] + [random.choice([1, -1, 2, 3])]
            terms = [f"({c})*x^{i}" for i, c in enumerate(coeffs) if c != 0]
            text = " + ".join(terms) or "0"
            e = parse(text)
            if x not in e.free_symbols():
                continue
            f = factor(e, x)
            self.assertEqual(expand(f), expand(e), msg=text)

    def test_constant_polynomial(self):
        self.assertEqual(factor(parse("7")), parse("7"))

    def test_multivariate_requires_explicit_var(self):
        with self.assertRaises(AxiomError):
            factor(parse("x*y + 1"))

    def test_non_polynomial_raises(self):
        with self.assertRaises(AxiomError):
            factor(parse("sin(x) + 1"), x)

    def test_unfactorable_over_rationals_left_unchanged_not_wrong(self):
        # x^4+4 factors over Q via Sophie Germain, but that's out of this
        # build's disclosed scope (rational roots + one final quadratic only)
        # -- it must come back unchanged, never something *incorrect*.
        f = factor(parse("x^4 + 4"), x)
        self.assertEqual(expand(f), parse("x^4+4"))


class TestGCD(unittest.TestCase):
    def test_common_linear_factor(self):
        g = poly_gcd(parse("x^2-1"), parse("x^2-3*x+2"), x)
        self.assertEqual(g, parse("x-1"))

    def test_coprime_gives_one(self):
        g = poly_gcd(parse("x+1"), parse("x^2+1"), x)
        self.assertEqual(g, parse("1"))

    def test_gcd_of_zero_and_p_is_p(self):
        g = poly_gcd(parse("0"), parse("x^2-1"), x)
        self.assertEqual(g, parse("x^2-1"))


class TestCoeffsAndDegree(unittest.TestCase):
    def test_degree(self):
        self.assertEqual(poly_degree(parse("x^3+2*x"), x), 3)

    def test_coeffs_dict(self):
        coeffs = poly_coeffs(parse("3*x^2 - x + 5"), x)
        self.assertEqual(coeffs[2], parse("3"))
        self.assertEqual(coeffs[1], parse("-1"))
        self.assertEqual(coeffs[0], parse("5"))

    def test_multivariate_coeffs_allowed(self):
        # coefficients can be expressions in other symbols
        coeffs = poly_coeffs(parse("y*x^2 + x + 1"), x)
        self.assertEqual(coeffs[2], parse("y"))

    def test_negative_exponent_not_a_polynomial(self):
        with self.assertRaises(AxiomError):
            poly_coeffs(parse("1/x"), x)


if __name__ == "__main__":
    unittest.main()
