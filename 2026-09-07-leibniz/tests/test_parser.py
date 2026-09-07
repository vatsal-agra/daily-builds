import unittest

from leibniz.expr import Num, Symbol
from leibniz.parser import ParseError, parse, parse_equation
from leibniz.render import to_str


class TestParser(unittest.TestCase):
    def test_basic_arithmetic(self):
        self.assertEqual(to_str(parse("2*x + 3*x - 1")), "5*x - 1")

    def test_implicit_multiplication_number_symbol(self):
        self.assertEqual(parse("2x"), parse("2*x"))

    def test_implicit_multiplication_symbol_paren(self):
        self.assertEqual(parse("x(x+1)"), parse("x*(x+1)"))

    def test_implicit_multiplication_paren_paren(self):
        self.assertEqual(parse("2(x+1)"), parse("2*(x+1)"))

    def test_caret_and_double_star_equivalent(self):
        self.assertEqual(parse("x^3"), parse("x**3"))

    def test_unary_minus_binds_tighter_than_multiplication(self):
        self.assertEqual(to_str(parse("-2*x")), "-2*x")

    def test_power_before_unary_minus(self):
        # -x^2 means -(x^2), not (-x)^2
        x = Symbol("x")
        self.assertEqual(parse("-x^2"), Num(-1) * x**2)

    def test_right_associative_power(self):
        # 2^3^2 = 2^(3^2) = 2^9 = 512
        self.assertEqual(parse("2^3^2"), Num(512))

    def test_functions(self):
        self.assertEqual(to_str(parse("sin(x)+cos(x)")), "cos(x) + sin(x)")

    def test_constants(self):
        from leibniz.expr import E, I, PI

        self.assertEqual(parse("pi"), PI)
        self.assertEqual(parse("e"), E)
        self.assertEqual(parse("i"), I)

    def test_decimal_literal_is_exact(self):
        self.assertEqual(to_str(parse("0.5*x")), "1/2*x")

    def test_division(self):
        self.assertEqual(to_str(parse("1/x")), "1/x")

    def test_equation_split_on_equals(self):
        lhs, rhs = parse_equation("x + 1 = 2*x")
        self.assertEqual(lhs, parse("x+1"))
        self.assertEqual(rhs, parse("2*x"))

    def test_equation_without_equals_defaults_rhs_zero(self):
        lhs, rhs = parse_equation("x - 3")
        self.assertEqual(rhs, Num(0))

    def test_parse_errors_do_not_crash(self):
        for bad in ["", "2+*3", "sin(x", "((x)", "2 3 +", "@"]:
            with self.assertRaises(ParseError):
                parse(bad)


if __name__ == "__main__":
    unittest.main()
