import random
import unittest

from leibniz.expr import Num, Symbol, pow_, subs
from leibniz.parser import parse, parse_equation
from leibniz.polynomial import expand
from leibniz.render import to_str
from leibniz.solve import (
    LinearSystemError, SolveError, solve, solve_linear_system, solve_quadratic,
)


class TestSolveLinear(unittest.TestCase):
    def test_simple_linear(self):
        res = solve(*parse_equation("2*x + 4 = 0"), "x")
        self.assertEqual([to_str(r) for r in res.roots], ["-2"])

    def test_infinite_solutions(self):
        res = solve(*parse_equation("x = x"), "x")
        self.assertTrue(res.infinite)

    def test_no_solution(self):
        res = solve(*parse_equation("0*x + 1 = 0"), "x")
        self.assertTrue(res.no_solution)


class TestSolveQuadratic(unittest.TestCase):
    def test_two_rational_roots(self):
        res = solve(*parse_equation("x^2 - 5*x + 6 = 0"), "x")
        self.assertEqual(sorted(to_str(r) for r in res.roots), ["2", "3"])

    def test_irrational_roots_are_exact_sqrt(self):
        res = solve(*parse_equation("x^2 - 2 = 0"), "x")
        self.assertEqual(sorted(to_str(r) for r in res.roots), ["-sqrt(2)", "sqrt(2)"])

    def test_complex_roots_use_i(self):
        res = solve(*parse_equation("x^2 + 1 = 0"), "x")
        self.assertEqual(sorted(to_str(r) for r in res.roots), ["-i", "i"])

    def test_double_root(self):
        r1, r2 = solve_quadratic(Num(1), Num(-4), Num(4))
        self.assertEqual(r1, r2)
        self.assertEqual(to_str(r1), "2")


class TestSolveGeneralPolynomial(unittest.TestCase):
    def test_cubic_with_rational_roots(self):
        res = solve(*parse_equation("x^3 - 6*x^2 + 11*x - 6 = 0"), "x")
        self.assertEqual(sorted(to_str(r) for r in res.roots), ["1", "2", "3"])

    def test_cubic_falls_back_to_numeric(self):
        res = solve(*parse_equation("x^3 - 2 = 0"), "x")
        self.assertEqual(res.roots, [])
        self.assertEqual(len(res.numeric_roots), 3)
        reals = [r for r in res.numeric_roots if r.imag == 0]
        self.assertEqual(len(reals), 1)
        self.assertAlmostEqual(reals[0].real, 2 ** (1 / 3), places=6)


class TestSolveErrors(unittest.TestCase):
    def test_non_polynomial_raises(self):
        with self.assertRaises(SolveError):
            solve(*parse_equation("sin(x) = 0"), "x")


class TestSolveVerificationFuzz(unittest.TestCase):
    """The real oracle: substitute every returned root back into the
    original equation and expand -- it must be exactly zero."""

    def test_random_quadratics(self):
        random.seed(3)
        x = Symbol("x")
        for _ in range(150):
            a = random.randint(-5, 5) or 1
            b = random.randint(-5, 5)
            c = random.randint(-5, 5)
            lhs = Num(a) * pow_(x, Num(2)) + Num(b) * x + Num(c)
            res = solve(lhs, Num(0), "x")
            for r in res.roots:
                val = expand(subs(lhs, {"x": r}))
                self.assertEqual(val, Num(0), msg=f"{a}x^2+{b}x+{c}, root {to_str(r)}")

    def test_random_higher_degree_rational_roots(self):
        random.seed(5)
        x = Symbol("x")
        for _ in range(80):
            roots = [random.randint(-4, 4) or 1 for _ in range(random.randint(1, 4))]
            poly = Num(1)
            for r in roots:
                poly = poly * (x - Num(r))
            poly = expand(poly)
            res = solve(poly, Num(0), "x")
            for r in res.roots:
                val = expand(subs(poly, {"x": r}))
                self.assertEqual(val, Num(0))


class TestLinearSystem(unittest.TestCase):
    def test_unique_solution(self):
        res = solve_linear_system(
            [(parse("2*x+y"), Num(5)), (parse("x-y"), Num(1))], ["x", "y"]
        )
        self.assertEqual(to_str(res.solution["x"]), "2")
        self.assertEqual(to_str(res.solution["y"]), "1")

    def test_inconsistent(self):
        res = solve_linear_system(
            [(parse("x+y"), Num(2)), (parse("x+y"), Num(3))], ["x", "y"]
        )
        self.assertTrue(res.inconsistent)

    def test_underdetermined(self):
        res = solve_linear_system([(parse("x+y"), Num(2))], ["x", "y"])
        self.assertTrue(res.infinite)

    def test_nonlinear_term_raises(self):
        with self.assertRaises(LinearSystemError):
            solve_linear_system([(parse("x*y"), Num(1))], ["x", "y"])


if __name__ == "__main__":
    unittest.main()
