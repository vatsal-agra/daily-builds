import random
import unittest

from axiom import parse, sym, solve
from axiom.errors import AxiomError

x = sym("x")


def residual(root, poly_str):
    e = parse(poly_str)
    if isinstance(root, complex):
        # substitute manually via complex evalf isn't directly supported for
        # complex bindings through the public evalf() signature restricted to
        # real/complex numbers -- evalf already accepts complex bindings.
        return abs(e.evalf({"x": root}))
    return abs(e.evalf({"x": root}))


class TestLinearQuadratic(unittest.TestCase):
    def test_linear(self):
        self.assertEqual(solve(parse("2*x - 6"), x), [parse("3")])

    def test_quadratic_real_rational_roots(self):
        roots = solve(parse("x^2 - 5*x + 6"), x)
        self.assertEqual(set(str(r) for r in roots), {"2", "3"})

    def test_quadratic_irrational_roots_exact_radical(self):
        roots = solve(parse("x^2 - 2"), x)
        self.assertEqual({str(r) for r in roots}, {"2^(1/2)", "-2^(1/2)"})

    def test_quadratic_complex_roots(self):
        roots = solve(parse("x^2 + 1"), x)
        self.assertEqual(len(roots), 2)
        for r in roots:
            self.assertLess(residual(r, "x^2+1"), 1e-9)
        self.assertEqual({r.imag for r in roots}, {1.0, -1.0})

    def test_double_root_multiplicity_preserved(self):
        roots = solve(parse("x^2 - 4*x + 4"), x)
        self.assertEqual(roots, [parse("2"), parse("2")])

    def test_symbolic_quadratic_formula(self):
        a, b, c = sym("a"), sym("b"), sym("c")
        roots = solve((parse("a*x^2 + b*x + c"), parse("0")), x)
        self.assertEqual(len(roots), 2)
        # substitute a=1,b=-5,c=6 and check we recover the numeric roots
        vals = {str(r.subs({"a": 1, "b": -5, "c": 6}).evalf().real) for r in roots}
        # evalf gives floats -- just check they're close to 2 and 3
        nums = sorted(r.subs({"a": 1, "b": -5, "c": 6}).evalf().real for r in roots)
        self.assertAlmostEqual(nums[0], 2.0)
        self.assertAlmostEqual(nums[1], 3.0)


class TestHigherDegree(unittest.TestCase):
    def test_cubic_all_rational(self):
        roots = solve(parse("x^3 - 6*x^2 + 11*x - 6"), x)
        self.assertEqual(sorted(str(r) for r in roots), ["1", "2", "3"])

    def test_quartic_mixed_real_complex(self):
        roots = solve(parse("x^4 - 1"), x)
        reals = {str(r) for r in roots if isinstance(r, type(parse("1")))}
        self.assertEqual(reals, {"1", "-1"})
        complexes = [r for r in roots if isinstance(r, complex)]
        self.assertEqual(len(complexes), 2)

    def test_quintic_no_rational_roots_numeric(self):
        roots = solve(parse("x^5 - x - 1"), x)
        self.assertEqual(len(roots), 5)
        for r in roots:
            self.assertLess(residual(r, "x^5-x-1"), 1e-8)

    def test_all_roots_of_random_polynomials_verified_by_residual(self):
        random.seed(99)
        for _ in range(8):
            deg = random.randint(3, 6)
            coeffs = [random.randint(-4, 4) for _ in range(deg)] + [random.choice([1, -1, 2])]
            terms = []
            for i, c in enumerate(coeffs):
                if c == 0:
                    continue
                terms.append(f"({c})*x^{i}" if i else f"({c})")
            poly = " + ".join(terms) or "1"
            e = parse(poly)
            if e.free_symbols() == set():
                continue
            roots = solve(e, x)
            for r in roots:
                self.assertLess(abs(e.evalf({"x": r})), 1e-6, msg=poly)


class TestEquationForms(unittest.TestCase):
    def test_equals_string_form(self):
        roots = solve("x^2 = 4", x)
        self.assertEqual({str(r) for r in roots}, {"2", "-2"})

    def test_tuple_form(self):
        roots = solve((parse("x^2"), parse("4")), x)
        self.assertEqual({str(r) for r in roots}, {"2", "-2"})

    def test_var_as_string(self):
        roots = solve(parse("x-1"), "x")
        self.assertEqual(roots, [parse("1")])


class TestEdgeCases(unittest.TestCase):
    def test_identity_equation_raises(self):
        with self.assertRaises(AxiomError):
            solve(parse("0"), x)
        with self.assertRaises(AxiomError):
            solve(parse("x - x"), x)

    def test_no_solution_constant_nonzero(self):
        self.assertEqual(solve(parse("5"), x), [])

    def test_higher_degree_needs_numeric_coefficients(self):
        a = sym("a")
        with self.assertRaises(AxiomError):
            solve(parse("a*x^3 + x - 1"), x)


if __name__ == "__main__":
    unittest.main()
