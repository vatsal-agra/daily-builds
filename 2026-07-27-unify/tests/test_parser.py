import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unify.parser import parse, ParseError
from unify.evaluator import eval_expr, format_value
from unify import nodes as N


def run(src):
    return eval_expr({}, parse(src))


class TestParserPrecedence(unittest.TestCase):
    def test_mul_binds_tighter_than_add(self):
        self.assertEqual(run("1 + 2 * 3"), 7)
        self.assertEqual(run("(1 + 2) * 3"), 9)

    def test_application_binds_tighter_than_operators(self):
        self.assertEqual(run("let f = fun x -> x + 1 in f 2 + 3"), 6)  # (f 2) + 3, not f (2+3)

    def test_unary_minus(self):
        self.assertEqual(run("- 3 + 5"), 2)

    def test_cons_is_right_associative(self):
        self.assertEqual(run("1 :: 2 :: [] "), [1, 2])

    def test_comparison_chain_left_assoc_parses(self):
        # `1 < 2` alone must parse fine; verifies cmp level reachable.
        self.assertEqual(run("1 < 2"), True)

    def test_and_or_precedence(self):
        self.assertEqual(run("true || false && false"), True)  # && binds tighter than ||

    def test_if_then_else_extends_maximally(self):
        self.assertEqual(run("if true then 1 else 2 + 100"), 1)

    def test_let_multi_arg_sugar(self):
        self.assertEqual(run("let add x y = x + y in add 3 4"), 7)

    def test_fun_multi_arg_sugar(self):
        self.assertEqual(run("(fun x y -> x - y) 10 3"), 7)

    def test_tuple_literal(self):
        self.assertEqual(run("(1, true, \"x\")"), (1, True, "x"))

    def test_parenthesized_single_expr_is_not_a_tuple(self):
        self.assertEqual(run("(1 + 2)"), 3)

    def test_list_literal_desugars_to_cons_nil(self):
        self.assertEqual(run("[1, 2, 3]"), [1, 2, 3])

    def test_some_none(self):
        e = parse("Some 5")
        self.assertIsInstance(e, N.SomeExpr)
        e2 = parse("None")
        self.assertIsInstance(e2, N.NoneExpr)


class TestParserErrors(unittest.TestCase):
    def test_unexpected_token(self):
        with self.assertRaises(ParseError):
            parse("let x = in x")

    def test_trailing_garbage(self):
        with self.assertRaises(ParseError):
            parse("1 2 )")

    def test_let_rec_requires_function(self):
        with self.assertRaises(ParseError):
            parse("let rec x = 5 in x")

    def test_let_rec_with_fun_rhs_is_fine(self):
        e = parse("let rec f = fun x -> x in f")
        self.assertIsInstance(e, N.LetRec)

    def test_fun_requires_param(self):
        with self.assertRaises(ParseError):
            parse("fun -> 1")

    def test_match_requires_case(self):
        with self.assertRaises(ParseError):
            parse("match 1 with")


class TestSpans(unittest.TestCase):
    def test_span_widens_through_parens(self):
        e = parse("(1 + 2)")
        self.assertEqual(e.span, (0, 7))


if __name__ == "__main__":
    unittest.main()
