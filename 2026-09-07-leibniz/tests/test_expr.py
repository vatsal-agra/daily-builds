import unittest
from fractions import Fraction

from leibniz.expr import (
    E, I, PI, Num, Symbol, evalf, free_symbols, mul, pow_, subs,
)


class TestConstruction(unittest.TestCase):
    def test_operators_build_expressions(self):
        x = Symbol("x")
        e = 2 * x + 3 * x - 1
        self.assertEqual(str(e), "5*x - 1")

    def test_num_exact_fraction_arithmetic(self):
        x = Symbol("x")
        e = (x / 3) * 6
        self.assertEqual(str(e), "2*x")

    def test_structural_equality(self):
        x = Symbol("x")
        self.assertEqual(x + 1, Num(1) + x)
        self.assertNotEqual(x + 1, x + 2)

    def test_hashable(self):
        x, y = Symbol("x"), Symbol("y")
        s = {x + 1, y + 1, x + 1}
        self.assertEqual(len(s), 2)


class TestZero(unittest.TestCase):
    def test_zero_times_anything_is_zero(self):
        x = Symbol("x")
        self.assertEqual(mul(Num(0), x, x + 1), Num(0))

    def test_zero_to_positive_power_is_zero(self):
        self.assertEqual(pow_(Num(0), Num(3)), Num(0))

    def test_zero_to_zero_is_one_by_convention(self):
        self.assertEqual(pow_(Num(0), Num(0)), Num(1))

    def test_zero_to_negative_power_raises(self):
        with self.assertRaises(ZeroDivisionError):
            pow_(Num(0), Num(-1))
        with self.assertRaises(ZeroDivisionError):
            Num(1) / Num(0)


class TestExactPowers(unittest.TestCase):
    def test_sqrt_of_perfect_square(self):
        from leibniz.expr import func_

        self.assertEqual(func_("sqrt", Num(4)), Num(2))
        self.assertEqual(func_("sqrt", Num(Fraction(9, 4))), Num(Fraction(3, 2)))

    def test_sqrt_extracts_square_factor(self):
        from leibniz.expr import func_

        self.assertEqual(str(func_("sqrt", Num(8))), "2*sqrt(2)")
        self.assertEqual(str(func_("sqrt", Num(12))), "2*sqrt(3)")

    def test_sqrt_of_negative_uses_i(self):
        from leibniz.expr import func_

        self.assertEqual(func_("sqrt", Num(-4)), mul(Num(2), I))
        self.assertEqual(str(func_("sqrt", Num(-8))), "2*i*sqrt(2)")

    def test_sqrt_squared_cancels_exactly(self):
        from leibniz.expr import func_

        s = func_("sqrt", Num(19))
        self.assertEqual(pow_(s, Num(2)), Num(19))
        self.assertEqual(pow_(s, Num(3)), mul(Num(19), s))

    def test_imaginary_power_cycle(self):
        self.assertEqual(pow_(I, Num(0)), Num(1))
        self.assertEqual(pow_(I, Num(1)), I)
        self.assertEqual(pow_(I, Num(2)), Num(-1))
        self.assertEqual(pow_(I, Num(3)), mul(Num(-1), I))
        self.assertEqual(pow_(I, Num(4)), Num(1))
        self.assertEqual(pow_(I, Num(-1)), mul(Num(-1), I))
        self.assertEqual(pow_(I, Num(-2)), Num(-1))

    def test_power_of_product_distributes_for_integer_exponent(self):
        x, y = Symbol("x"), Symbol("y")
        self.assertEqual(str(pow_(mul(Num(2), x), Num(3))), "8*x^3")
        self.assertEqual(str(pow_(mul(x, y), Num(2))), "x^2*y^2")


class TestSubsEvalf(unittest.TestCase):
    def test_subs(self):
        x, y = Symbol("x"), Symbol("y")
        e = x**2 + y
        self.assertEqual(subs(e, {"x": Num(3), "y": Num(1)}), Num(10))

    def test_free_symbols_excludes_constants(self):
        x = Symbol("x")
        self.assertEqual(free_symbols(x + PI + E + I), {"x"})

    def test_evalf(self):
        x = Symbol("x")
        self.assertAlmostEqual(evalf(x**2 + 1, {"x": 3}), 10.0)

    def test_evalf_missing_binding_raises(self):
        from leibniz.expr import CannotEvaluate

        x = Symbol("x")
        with self.assertRaises(CannotEvaluate):
            evalf(x, {})


if __name__ == "__main__":
    unittest.main()
