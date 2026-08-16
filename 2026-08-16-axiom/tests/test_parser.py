import unittest

from axiom import parse
from axiom.errors import ParseError


class TestPrecedence(unittest.TestCase):
    def test_operator_precedence(self):
        self.assertEqual(str(parse("2 + 3 * 4")), "14")
        self.assertEqual(str(parse("2 * 3 + 4")), "10")
        self.assertEqual(str(parse("2 ^ 3 * 2")), "16")
        self.assertEqual(str(parse("2 * 2 ^ 3")), "16")

    def test_right_associative_power(self):
        # 2^3^2 == 2^(3^2) == 2^9 == 512, NOT (2^3)^2 == 64
        self.assertEqual(str(parse("2^3^2")), "512")

    def test_unary_minus_binds_looser_than_power(self):
        self.assertEqual(parse("-2^2").evalf().real, -4.0)
        self.assertEqual(parse("(-2)^2").evalf().real, 4.0)

    def test_implicit_multiplication(self):
        self.assertEqual(parse("2x"), parse("2*x"))
        self.assertEqual(parse("3(x+1)"), parse("3*(x+1)"))
        self.assertEqual(parse("(x+1)(x-1)"), parse("(x+1)*(x-1)"))
        self.assertEqual(parse("2sin(x)"), parse("2*sin(x)"))

    def test_negative_exponent_via_caret_minus(self):
        self.assertEqual(parse("2^-3").evalf().real, 0.125)


class TestDecimals(unittest.TestCase):
    def test_decimal_is_exact_rational(self):
        from fractions import Fraction
        self.assertEqual(parse("0.25").value, Fraction(1, 4))


class TestErrors(unittest.TestCase):
    def test_empty_string(self):
        with self.assertRaises(ParseError):
            parse("")

    def test_unbalanced_parens(self):
        with self.assertRaises(ParseError):
            parse("(x + 1")

    def test_unknown_function(self):
        with self.assertRaises(ParseError):
            parse("foo(x)")

    def test_trailing_operator(self):
        with self.assertRaises(ParseError):
            parse("x +")

    def test_bad_character(self):
        with self.assertRaises(ParseError):
            parse("x!")

    def test_error_has_position(self):
        try:
            parse("x + )")
        except ParseError as ex:
            self.assertIn("^", str(ex))

    def test_deep_nesting_raises_clean_error_not_recursion_error(self):
        text = "(" * 500 + "x" + ")" * 500
        with self.assertRaises(ParseError):
            parse(text)

    def test_moderate_nesting_still_works(self):
        text = "(" * 50 + "x" + ")" * 50
        self.assertEqual(parse(text), parse("x"))

    def test_deep_function_nesting_raises_clean_error(self):
        text = "sin(" * 300 + "x" + ")" * 300
        with self.assertRaises(ParseError):
            parse(text)


if __name__ == "__main__":
    unittest.main()
