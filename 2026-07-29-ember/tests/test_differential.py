"""The core correctness gate: for every example program, the interpreter,
the JIT, and (when available) real gcc must agree bit-for-bit."""

import os
import unittest

from ember.parser import parse
from ember.interpreter import Interpreter
from ember.codegen_x64 import compile_program
from ember.transpile_c import run_via_gcc, gcc_available
from ember.errors import EmberRuntimeError

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")

CASES = [
    ("fib.em", "fib", [0]), ("fib.em", "fib", [1]), ("fib.em", "fib", [2]),
    ("fib.em", "fib", [15]), ("fib.em", "fib", [23]),
    ("factorial.em", "factorial", [0]), ("factorial.em", "factorial", [1]),
    ("factorial.em", "factorial", [12]), ("factorial.em", "factorial_rec", [12]),
    ("gcd.em", "gcd", [1071, 462]), ("gcd.em", "gcd", [0, 7]), ("gcd.em", "gcd", [7, 0]),
    ("gcd.em", "gcd", [17, 13]),
    ("parity.em", "is_even", [0]), ("parity.em", "is_even", [1]),
    ("parity.em", "is_even", [50]), ("parity.em", "is_odd", [51]),
    ("primes.em", "is_prime", [0]), ("primes.em", "is_prime", [1]),
    ("primes.em", "is_prime", [2]), ("primes.em", "is_prime", [97]),
    ("primes.em", "is_prime", [100]), ("primes.em", "count_primes_below", [30]),
    ("ackermann.em", "ackermann", [0, 5]), ("ackermann.em", "ackermann", [1, 3]),
    ("ackermann.em", "ackermann", [2, 4]), ("ackermann.em", "ackermann", [3, 3]),
    ("args6.em", "weighted_sum", [1, 2, 3, 4, 5, 6]),
    ("args6.em", "weighted_sum", [-6, -5, -4, -3, -2, -1]),
    ("args6.em", "call_weighted_sum", [1]), ("args6.em", "call_weighted_sum", [-3]),
    ("logic.em", "guard", [0, 100]), ("logic.em", "guard", [1, 100]), ("logic.em", "guard", [5, 3]),
    ("logic.em", "either", [0, 100]), ("logic.em", "either", [5, 3]),
    ("logic.em", "logical_not", [0]), ("logic.em", "logical_not", [1]), ("logic.em", "logical_not", [-5]),
]

_cache = {}


def _load(fname):
    if fname not in _cache:
        with open(os.path.join(EXAMPLES, fname)) as f:
            _cache[fname] = parse(f.read())
    return _cache[fname]


class TestDifferential(unittest.TestCase):
    pass


def _make_test(fname, fn, args):
    def test(self):
        program = _load(fname)
        interp_r = Interpreter(program).call(fn, args)
        jit_r = compile_program(program).call(fn, args)
        self.assertEqual(interp_r, jit_r, f"{fname}:{fn}{tuple(args)} interpreter vs JIT mismatch")
        if gcc_available():
            gcc_r = run_via_gcc(program, fn, args)
            self.assertEqual(interp_r, gcc_r, f"{fname}:{fn}{tuple(args)} interpreter vs gcc mismatch")
    return test


for _fname, _fn, _args in CASES:
    _name = f"test_{_fname.replace('.em', '')}_{_fn}_{'_'.join(str(a).replace('-', 'neg') for a in _args)}"
    setattr(TestDifferential, _name, _make_test(_fname, _fn, _args))


class TestRuntimeErrorGuards(unittest.TestCase):
    def setUp(self):
        self.program = parse("fn d(a, b) { return a / b; }\nfn m(a, b) { return a % b; }\n")

    def test_division_by_zero_interpreter(self):
        with self.assertRaises(EmberRuntimeError):
            Interpreter(self.program).call("d", [10, 0])

    def test_division_by_zero_jit(self):
        with self.assertRaises(EmberRuntimeError):
            compile_program(self.program).call("d", [10, 0])

    def test_modulo_by_zero_jit(self):
        with self.assertRaises(EmberRuntimeError):
            compile_program(self.program).call("m", [10, 0])

    def test_int64_min_over_neg1_interpreter(self):
        with self.assertRaises(EmberRuntimeError):
            Interpreter(self.program).call("d", [-(2 ** 63), -1])

    def test_int64_min_over_neg1_jit(self):
        with self.assertRaises(EmberRuntimeError):
            compile_program(self.program).call("d", [-(2 ** 63), -1])

    def test_jit_survives_the_error_and_can_be_called_again(self):
        """The error-flag cell must be cleared after raising, or a later
        successful call would spuriously look like it errored too."""
        compiled = compile_program(self.program)
        with self.assertRaises(EmberRuntimeError):
            compiled.call("d", [10, 0])
        self.assertEqual(compiled.call("d", [10, 5]), 2)

    def test_wrong_arg_count_jit(self):
        with self.assertRaises(EmberRuntimeError):
            compile_program(self.program).call("d", [10])


if __name__ == "__main__":
    unittest.main()
