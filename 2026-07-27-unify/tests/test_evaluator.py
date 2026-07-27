import os
import sys
import unittest

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

from unify.parser import parse
from unify.infer import infer_program
from unify.evaluator import eval_expr, EvalError, format_value, SomeV, NoneV


def run(src, check_types=True):
    e = parse(src)
    if check_types:
        infer_program(e)  # only run well-typed programs, like the real CLI does
    return eval_expr({}, e)


class TestArithmeticAndControlFlow(unittest.TestCase):
    def test_arithmetic(self):
        self.assertEqual(run("1 + 2 * 3 - 4 / 2"), 5)

    def test_truncating_division_toward_zero(self):
        self.assertEqual(run("7 / 2"), 3)
        self.assertEqual(run("-7 / 2"), -3)  # truncation, not floor (-4)
        self.assertEqual(run("7 / -2"), -3)

    def test_division_by_zero_raises_eval_error(self):
        with self.assertRaises(EvalError):
            run("1 / 0")

    def test_if(self):
        self.assertEqual(run("if 1 < 2 then 10 else 20"), 10)

    def test_boolean_short_circuit_shape_still_evaluates_correctly(self):
        self.assertEqual(run("true || (1 / 0 = 0)", check_types=False), True)


class TestFunctionsAndRecursion(unittest.TestCase):
    def test_factorial(self):
        self.assertEqual(
            run("let rec fact n = if n = 0 then 1 else n * fact (n - 1) in fact 10"),
            3628800,
        )

    def test_fibonacci(self):
        src = (
            "let rec fib n = if n < 2 then n else fib (n - 1) + fib (n - 2) "
            "in fib 10"
        )
        self.assertEqual(run(src), 55)

    def test_closures_capture_environment(self):
        src = "let make_adder = fun x -> fun y -> x + y in let add5 = make_adder 5 in add5 3"
        self.assertEqual(run(src), 8)

    def test_higher_order_map(self):
        src = (
            "let rec map f l = match l with | [] -> [] | h :: t -> f h :: map f t "
            "in map (fun x -> x * 2) [1, 2, 3, 4]"
        )
        self.assertEqual(run(src), [2, 4, 6, 8])


class TestDataStructures(unittest.TestCase):
    def test_tuples(self):
        self.assertEqual(run("let p = (1, 2) in match p with | (a, b) -> a + b"), 3)

    def test_option_some(self):
        self.assertEqual(run("match Some 5 with | Some x -> x | None -> 0"), 5)

    def test_option_none(self):
        self.assertEqual(run("match None with | Some x -> x | None -> -1"), -1)

    def test_list_pattern_head_tail(self):
        self.assertEqual(run("match [1,2,3] with | [] -> 0 | h :: t -> h"), 1)

    def test_nested_pattern_tuple_of_options(self):
        src = "match (Some 1, None) with | (Some a, None) -> a | _ -> -1"
        self.assertEqual(run(src), 1)


class TestRuntimeErrorsOnUnderTypedPrograms(unittest.TestCase):
    """HM does no exhaustiveness checking, so these type-check but can still
    fail at *runtime* -- and must fail with a clear EvalError, not a raw
    Python traceback."""

    def test_non_exhaustive_match_raises_clear_error(self):
        with self.assertRaises(EvalError) as ctx:
            run("match None with | Some x -> x")
        self.assertIn("non-exhaustive", ctx.exception.message)

    def test_comparing_functions_raises_clear_error(self):
        with self.assertRaises(EvalError):
            run("(fun x -> x) = (fun y -> y)")


class TestFormatValue(unittest.TestCase):
    def test_format_various(self):
        self.assertEqual(format_value(True), "true")
        self.assertEqual(format_value(False), "false")
        self.assertEqual(format_value(5), "5")
        self.assertEqual(format_value((1, True)), "(1, true)")
        self.assertEqual(format_value([1, 2]), "[1; 2]")
        self.assertEqual(format_value(SomeV(3)), "Some 3")
        self.assertEqual(format_value(NoneV()), "None")


if __name__ == "__main__":
    unittest.main()
