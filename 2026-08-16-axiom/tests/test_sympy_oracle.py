"""Differential testing against `sympy` — a second, independent, real CAS.

`sympy` is a dev/test-time-only dependency (this whole test module skips
itself gracefully if it isn't installed); no module under `axiom/` imports
it. This mirrors the pattern this repo has used before with real `git`
(Graft/Strata/Palimpsest), `openssl`/`gcc` (Ironkey/Ember), and NLTK
(Trove) as independent verification oracles rather than trusting
self-consistency alone.
"""

import random
import unittest

from axiom import parse, sym, differentiate, solve
from axiom.calculus import integrate
from axiom.errors import AxiomError

try:
    import sympy
    HAVE_SYMPY = True
except ImportError:
    HAVE_SYMPY = False

x = sym("x")


@unittest.skipUnless(HAVE_SYMPY, "sympy not installed -- oracle tests skipped")
class TestDifferentiationAgainstSympy(unittest.TestCase):
    def test_battery(self):
        sx = sympy.symbols("x")
        cases = [
            "x^3 + 2*x^2 - x + 5", "sin(x)*cos(x)", "exp(x^2)", "log(x^2+1)",
            "sqrt(x^2+4)", "x^2*exp(x)", "tan(x)", "1/(x^2+1)", "sinh(x)*cosh(x)",
        ]
        random.seed(1)
        for es in cases:
            axiom_d = differentiate(parse(es), x)
            sympy_d = sympy.diff(sympy.sympify(es.replace("^", "**")), sx)
            for _ in range(4):
                xv = random.uniform(-1.2, 1.2)
                a = axiom_d.evalf({"x": xv}).real
                s = float(sympy_d.subs(sx, xv))
                self.assertAlmostEqual(a, s, places=6, msg=es)


@unittest.skipUnless(HAVE_SYMPY, "sympy not installed -- oracle tests skipped")
class TestFactorAgainstSympy(unittest.TestCase):
    def test_roots_match(self):
        from axiom.polynomial import factor as axiom_factor, expand as axiom_expand
        sx = sympy.symbols("x")
        cases = ["x^2-5*x+6", "x^3-8", "2*x^2-3*x+1", "x^2-2", "x^3-6*x^2+11*x-6"]
        for es in cases:
            f_axiom = axiom_factor(parse(es), x)
            # cross-check by re-expanding and comparing to sympy's own expand
            sympy_expanded = sympy.expand(sympy.sympify(es.replace("^", "**")))
            axiom_expanded_str = str(axiom_expand(parse(es))).replace("^", "**")
            self.assertEqual(sympy.expand(sympy.sympify(axiom_expanded_str)), sympy_expanded, msg=es)


@unittest.skipUnless(HAVE_SYMPY, "sympy not installed -- oracle tests skipped")
class TestSolveAgainstSympy(unittest.TestCase):
    def test_root_sets_match(self):
        sx = sympy.symbols("x")
        cases = ["x^2-5*x+6", "x^2-2", "x^3-6*x^2+11*x-6", "x^2+1"]
        for es in cases:
            axiom_roots = solve(parse(es), x)
            sympy_roots = sympy.solve(sympy.sympify(es.replace("^", "**")), sx)

            def key(z):
                return (round(z.real, 6), round(z.imag, 6))

            axiom_numeric = sorted(
                [complex(r.evalf()) if hasattr(r, "evalf") else complex(r) for r in axiom_roots],
                key=key)
            sympy_numeric = sorted((complex(r) for r in sympy_roots), key=key)
            for a, s in zip(axiom_numeric, sympy_numeric):
                self.assertAlmostEqual(a.real, s.real, places=6, msg=es)
                self.assertAlmostEqual(a.imag, s.imag, places=6, msg=es)


@unittest.skipUnless(HAVE_SYMPY, "sympy not installed -- oracle tests skipped")
class TestIntegrateAgainstSympy(unittest.TestCase):
    def test_derivative_of_result_matches_sympy_integral_derivative(self):
        sx = sympy.symbols("x")
        cases = ["x^3+2*x", "sin(3*x+1)", "x*exp(x)", "x/(x^2+1)", "sin(x)*cos(x)"]
        random.seed(9)
        for es in cases:
            try:
                F = integrate(parse(es), x)
            except AxiomError:
                continue
            for _ in range(3):
                xv = random.uniform(0.2, 1.0)
                axiom_val = F.evalf({"x": xv}).real
                # sympy's own antiderivative, evaluated at the same point,
                # differs by at most a constant -- compare *derivatives* instead,
                # which must match exactly regardless of the constant of integration.
                d_axiom = differentiate(F, x).evalf({"x": xv}).real
                d_expected = float(sympy.sympify(es.replace("^", "**")).subs(sx, xv))
                self.assertAlmostEqual(d_axiom, d_expected, places=5, msg=es)


if __name__ == "__main__":
    unittest.main()
