import unittest
from fractions import Fraction

from axiom import parse, sym, num, add, mul, power, func
from axiom.errors import AxiomError, DomainError
from axiom.expr import Num, Symbol, Add, Mul, Pow, Func


class TestExactArithmetic(unittest.TestCase):
    def test_float_addition_is_exact(self):
        # The classic float trap: 0.1 + 0.2 != 0.3 in IEEE754. Axiom's kernel
        # is Fraction-based, so this must be exactly 3/10, not 0.30000000000000004.
        e = parse("0.1 + 0.2")
        self.assertIsInstance(e, Num)
        self.assertEqual(e.value, Fraction(3, 10))

    def test_large_integer_no_overflow(self):
        e = parse("99999999999999999999 * 99999999999999999999")
        self.assertEqual(e.value, Fraction(99999999999999999999 ** 2))

    def test_rational_reduction(self):
        self.assertEqual(parse("6/8").value, Fraction(3, 4))


class TestCanonicalization(unittest.TestCase):
    def test_like_terms_collected(self):
        self.assertEqual(str(parse("2*x + 3*x - x")), "4*x")

    def test_constants_folded(self):
        self.assertEqual(str(parse("2 + 3 * 4 - 1")), "13")

    def test_zero_terms_vanish(self):
        self.assertEqual(str(parse("x + y - x - y")), "0")

    def test_identity_removal(self):
        self.assertEqual(str(parse("x*1 + 0")), "x")
        self.assertEqual(str(parse("x^1")), "x")
        self.assertEqual(str(parse("x^0")), "1")
        self.assertEqual(str(parse("0*x")), "0")

    def test_exponent_laws(self):
        self.assertEqual(str(parse("x^2 * x^3")), "x^5")
        self.assertEqual(str(parse("(x^2)^3")), "x^6")
        self.assertEqual(str(parse("x^5 / x^2")), "x^3")

    def test_descending_degree_order(self):
        self.assertEqual(str(parse("1 + 3*x^2 + x + 5*x^3")), "5*x^3 + 3*x^2 + x + 1")

    def test_exact_perfect_square_root(self):
        self.assertEqual(str(parse("sqrt(4)")), "2")
        self.assertEqual(str(parse("sqrt(9/4)")), "3/2")

    def test_partial_radical_extraction(self):
        self.assertEqual(str(parse("sqrt(8)")), "2*2^(1/2)")
        self.assertEqual(str(parse("sqrt(8) + sqrt(2)")), "3*2^(1/2)")

    def test_odd_root_of_negative_is_exact(self):
        self.assertEqual(str(parse("(-8)^(1/3)")), "-2")

    def test_even_root_of_negative_stays_symbolic(self):
        e = parse("sqrt(-4)")
        self.assertIsInstance(e, Pow)

    def test_double_reciprocal(self):
        self.assertEqual(str(parse("1/(1/x)")), "x")

    def test_special_func_values(self):
        self.assertEqual(str(parse("sin(0)")), "0")
        self.assertEqual(str(parse("cos(0)")), "1")
        self.assertEqual(str(parse("log(1)")), "0")
        self.assertEqual(str(parse("log(exp(x))")), "x")
        self.assertEqual(str(parse("exp(log(x))")), "x")


class TestPrintingRoundTrip(unittest.TestCase):
    def test_roundtrip_battery(self):
        cases = [
            "x - 2", "-x^2", "(-2)^2", "x^(1/2)", "x^(-1/2)", "2^(1/2)",
            "x^-3", "(x + 1)^2", "2*x*y", "x/(x-1)", "sin(x)^2 + cos(x)^2",
            "1/2*x + 1/3", "-3*x - 5", "x^y^2",
        ]
        for text in cases:
            e = parse(text)
            reparsed = parse(str(e))
            self.assertEqual(e, reparsed, f"round-trip failed for {text!r}: {e} -> {reparsed}")

    def test_negative_pow_base_parens_needed_and_present(self):
        # power(-2, 2) folds to the exact Num 4 (nothing to print parens
        # around) — the real case where a literal negative base survives as
        # an unfolded Pow node is an even root of a negative number, which
        # stays symbolic (not a real number) rather than being computed.
        e = power(num(-2), num(Fraction(1, 2)))
        self.assertEqual(str(e), "(-2)^(1/2)")
        self.assertEqual(parse(str(e)), e)

    def test_repr_uses_pretty_printer_not_dataclass_repr(self):
        # dataclass(repr=True) would shadow Expr.__repr__ and show
        # "Num(value=Fraction(3, 1))" instead of "3".
        self.assertEqual(repr(parse("3")), "3")
        self.assertEqual(repr([parse("3"), parse("x")]), "[3, x]")


class TestSubsEvalFreeSymbols(unittest.TestCase):
    def test_subs(self):
        e = parse("x^2 + y")
        self.assertEqual(str(e.subs({"x": parse("3")})), "y + 9")

    def test_free_symbols(self):
        e = parse("x^2 + y*z")
        self.assertEqual({s.name for s in e.free_symbols()}, {"x", "y", "z"})

    def test_evalf_basic(self):
        self.assertAlmostEqual(parse("x^2+1").evalf({"x": 3}).real, 10.0)

    def test_evalf_pi_e_default_constants(self):
        import math
        self.assertAlmostEqual(parse("pi").evalf().real, math.pi)
        self.assertAlmostEqual(parse("e").evalf().real, math.e)
        # explicit binding overrides the default
        self.assertAlmostEqual(parse("pi").evalf({"pi": 1}).real, 1.0)

    def test_evalf_unbound_symbol_raises_domain_error(self):
        with self.assertRaises(DomainError):
            parse("x+y").evalf({"x": 1})

    def test_evalf_log_zero_raises(self):
        with self.assertRaises(DomainError):
            parse("log(x)").evalf({"x": 0})

    def test_evalf_division_by_zero_raises(self):
        with self.assertRaises(DomainError):
            parse("1/x").evalf({"x": 0})


class TestHashEquality(unittest.TestCase):
    def test_structural_equality(self):
        self.assertEqual(parse("x+y"), parse("y+x"))
        self.assertEqual(parse("2*x*y"), parse("y*2*x"))

    def test_usable_as_dict_key(self):
        d = {parse("x^2"): "squared"}
        self.assertEqual(d[parse("x^2")], "squared")

    def test_inequality(self):
        self.assertNotEqual(parse("x"), parse("y"))


class TestDomainErrors(unittest.TestCase):
    def test_zero_to_negative_power(self):
        with self.assertRaises(DomainError):
            parse("0^-1")

    def test_zero_zero_is_one_by_convention(self):
        self.assertEqual(str(parse("0^0")), "1")


if __name__ == "__main__":
    unittest.main()
