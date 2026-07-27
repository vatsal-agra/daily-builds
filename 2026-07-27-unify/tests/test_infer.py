import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unify.parser import parse
from unify.infer import infer_program, InferError
from unify.types import pretty, Scheme, free_vars


def infer(src):
    ty, _judgment, _counter = infer_program(parse(src))
    return pretty(ty)


class TestBasicTypes(unittest.TestCase):
    def test_literals(self):
        self.assertEqual(infer("42"), "int")
        self.assertEqual(infer("true"), "bool")
        self.assertEqual(infer('"hi"'), "string")

    def test_arithmetic(self):
        self.assertEqual(infer("1 + 2 * 3"), "int")

    def test_comparison_is_bool(self):
        self.assertEqual(infer("1 < 2"), "bool")

    def test_if(self):
        self.assertEqual(infer("if true then 1 else 2"), "int")

    def test_tuple(self):
        self.assertEqual(infer("(1, true)"), "(int, bool)")

    def test_list(self):
        self.assertEqual(infer("[1, 2, 3]"), "int list")

    def test_empty_list_is_polymorphic_until_used(self):
        # [] alone: 'a list (some fresh variable name).
        t = infer("[]")
        self.assertTrue(t.endswith("list"))

    def test_option(self):
        self.assertEqual(infer("Some 5"), "int option")
        self.assertEqual(infer("None") .endswith("option"), True)


class TestLetPolymorphism(unittest.TestCase):
    def test_id_used_at_two_types(self):
        self.assertEqual(infer("let id = fun x -> x in (id 1, id true)"), "(int, bool)")

    def test_lambda_bound_var_is_not_generalized(self):
        # Here `id` is a LAMBDA parameter, not a let-binding, so it must NOT
        # be polymorphic: using it at two different types must be rejected.
        with self.assertRaises(InferError):
            infer_helper = infer("(fun id -> (id 1, id true)) (fun x -> x)")

    def test_recursive_function_polymorphic_at_use_site_not_definition(self):
        src = "let rec len l = match l with | [] -> 0 | _ :: t -> 1 + len t in (len [1,2], len [true,false,true])"
        self.assertEqual(infer(src), "(int, int)")


class TestOccursCheck(unittest.TestCase):
    def test_self_application_rejected(self):
        with self.assertRaises(InferError) as ctx:
            infer("fun x -> x x")
        self.assertTrue(ctx.exception.infinite)

    def test_y_combinator_shape_rejected(self):
        with self.assertRaises(InferError):
            infer("fun f -> (fun x -> f (x x)) (fun x -> f (x x))")


class TestErrorMessages(unittest.TestCase):
    def test_arithmetic_type_mismatch_message(self):
        with self.assertRaises(InferError) as ctx:
            infer("1 + true")
        msg = ctx.exception.message
        self.assertIn("expected int", msg)
        self.assertIn("found bool", msg)

    def test_if_branch_mismatch(self):
        with self.assertRaises(InferError):
            infer("if true then 1 else false")

    def test_if_condition_must_be_bool(self):
        with self.assertRaises(InferError):
            infer("if 1 then 2 else 3")

    def test_unbound_variable(self):
        with self.assertRaises(InferError) as ctx:
            infer("x + 1")
        self.assertIn("unbound variable", ctx.exception.message)

    def test_application_of_non_function(self):
        with self.assertRaises(InferError):
            infer("1 2")

    def test_error_span_points_at_culprit(self):
        # `true` is the culprit in `1 + true`; span should cover just it.
        try:
            infer("1 + true")
            self.fail("expected InferError")
        except InferError as e:
            src = "1 + true"
            self.assertEqual(src[e.span[0]:e.span[1]], "true")


class TestPersistedEnvAcrossCalls(unittest.TestCase):
    """A REPL calls infer_program repeatedly against a persisted env of
    Schemes from earlier statements, each call getting a fresh Infer with
    its own counter. If that counter always restarts at 0, a freshly-minted
    variable can numerically collide with a scheme's own bound-variable
    label, so instantiate() builds a *self-referential* substitution
    ({1: TVar(1)}) and apply() recurses forever. Threading a running
    counter via start_counter/next_counter is what prevents this."""

    def test_without_threaded_counter_instantiation_can_self_reference(self):
        ty1, _j1, _c1 = infer_program(parse("fun x -> x"))
        scheme_f = Scheme(frozenset(free_vars(ty1)), ty1)
        ty2, _j2, _c2 = infer_program(parse("fun x -> x + 1"))
        scheme_g = Scheme(frozenset(free_vars(ty2)), ty2)

        with self.assertRaises(RecursionError):
            infer_program(
                parse("(f true, g 5)"),
                base_env={"f": scheme_f, "g": scheme_g},
                start_counter=0,
            )

    def test_threaded_counter_avoids_the_collision(self):
        counter = 0
        ty1, _j1, counter = infer_program(parse("fun x -> x"), start_counter=counter)
        scheme_f = Scheme(frozenset(free_vars(ty1)), ty1)
        ty2, _j2, counter = infer_program(parse("fun x -> x + 1"), start_counter=counter)
        scheme_g = Scheme(frozenset(free_vars(ty2)), ty2)

        ty3, _j3, counter = infer_program(
            parse("(f true, g 5)"),
            base_env={"f": scheme_f, "g": scheme_g},
            start_counter=counter,
        )
        self.assertEqual(pretty(ty3), "(bool, int)")


class TestListsTuplesOptionsTogether(unittest.TestCase):
    def test_assoc_list_lookup(self):
        src = (
            "let rec assoc key l = match l with "
            "| [] -> None "
            "| (k, v) :: rest -> if k = key then Some v else assoc key rest "
            "in assoc 2 [(1, 10), (2, 42)]"
        )
        self.assertEqual(infer(src), "int option")

    def test_mismatched_tuple_arity_in_match(self):
        with self.assertRaises(InferError):
            infer("match (1, 2) with | (a, b, c) -> a")

    def test_cons_element_type_mismatch(self):
        with self.assertRaises(InferError):
            infer("1 :: true :: []")

    def test_non_exhaustive_shape_still_type_checks(self):
        # HM doesn't do exhaustiveness checking -- this SHOULD type-check
        # even though it can crash at runtime on None (covered in eval tests).
        self.assertEqual(infer("match Some 1 with | Some x -> x"), "int")


if __name__ == "__main__":
    unittest.main()
