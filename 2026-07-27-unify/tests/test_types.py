import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unify.types import (
    TVar, TFun, TTuple, TList, TOption, TINT, TBOOL,
    unify_raw, UnifyError, apply, compose, pretty, pretty_pair, occurs,
)


class TestUnify(unittest.TestCase):
    def test_unify_identical_cons(self):
        self.assertEqual(unify_raw(TINT, TINT), {})

    def test_unify_mismatched_cons_raises(self):
        with self.assertRaises(UnifyError):
            unify_raw(TINT, TBOOL)

    def test_unify_var_binds(self):
        v = TVar(1)
        s = unify_raw(v, TINT)
        self.assertEqual(s, {1: TINT})

    def test_unify_var_on_right(self):
        v = TVar(1)
        s = unify_raw(TINT, v)
        self.assertEqual(s, {1: TINT})

    def test_occurs_check_direct(self):
        v = TVar(1)
        self.assertTrue(occurs(1, TFun(v, TINT)))
        with self.assertRaises(UnifyError) as ctx:
            unify_raw(v, TFun(v, TINT))
        self.assertTrue(ctx.exception.infinite)

    def test_unify_functions_threads_substitution(self):
        # (a -> a) unified with (int -> b) must force b = int too.
        a, b = TVar(1), TVar(2)
        s = unify_raw(TFun(a, a), TFun(TINT, b))
        self.assertEqual(apply(s, b), TINT)
        self.assertEqual(apply(s, a), TINT)

    def test_tuple_arity_mismatch(self):
        with self.assertRaises(UnifyError):
            unify_raw(TTuple((TINT, TINT)), TTuple((TINT,)))

    def test_list_and_option_recurse_into_element(self):
        v = TVar(1)
        s = unify_raw(TList(v), TList(TINT))
        self.assertEqual(apply(s, v), TINT)
        s2 = unify_raw(TOption(v), TOption(TBOOL))
        self.assertEqual(apply(s2, v), TBOOL)

    def test_compose_applies_left_to_right_values(self):
        s1 = {1: TINT}
        s2 = {2: TVar(1)}
        composed = compose(s1, s2)
        self.assertEqual(composed[2], TINT)
        self.assertEqual(composed[1], TINT)


class TestPretty(unittest.TestCase):
    def test_simple_types(self):
        self.assertEqual(pretty(TINT), "int")
        self.assertEqual(pretty(TFun(TINT, TBOOL)), "int -> bool")

    def test_curried_function_no_parens(self):
        self.assertEqual(pretty(TFun(TINT, TFun(TINT, TINT))), "int -> int -> int")

    def test_function_argument_gets_parens(self):
        self.assertEqual(
            pretty(TFun(TFun(TINT, TINT), TBOOL)), "(int -> int) -> bool"
        )

    def test_list_and_option(self):
        self.assertEqual(pretty(TList(TINT)), "int list")
        self.assertEqual(pretty(TOption(TBOOL)), "bool option")

    def test_tuple(self):
        self.assertEqual(pretty(TTuple((TINT, TBOOL))), "(int, bool)")

    def test_var_naming_is_stable_within_one_call(self):
        v1, v2 = TVar(5), TVar(9)
        self.assertEqual(pretty(TFun(v1, v2)), "'a -> 'b")

    def test_pretty_pair_shares_variable_names_across_both_sides(self):
        # A variable shared by both types in an error message must print
        # with the SAME letter on both sides, or the message misleadingly
        # suggests two unrelated types.
        v = TVar(42)
        sa, sb = pretty_pair(TFun(v, TINT), TFun(v, TBOOL))
        self.assertEqual(sa, "'a -> int")
        self.assertEqual(sb, "'a -> bool")

    def test_unify_error_message_uses_shared_variable_names(self):
        # A mismatch between two altogether-incompatible shapes (function
        # vs. tuple) is reported at the top level, so both full types --
        # including their shared variable -- appear in one message.
        v = TVar(1)
        with self.assertRaises(UnifyError) as ctx:
            unify_raw(TFun(v, TINT), TTuple((v, TBOOL)))
        msg = ctx.exception.message
        self.assertIn("'a -> int", msg)
        self.assertIn("('a, bool)", msg)


if __name__ == "__main__":
    unittest.main()
