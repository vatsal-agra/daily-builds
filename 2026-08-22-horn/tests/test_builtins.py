"""Builtin-predicate edge cases not already covered incidentally by
test_engine.py's broader engine-behavior tests."""

import pytest

from conftest import fails, succeeds
from horn.engine import make_engine
from horn.errors import HaltSignal
from horn.parser import parse_term


def test_all_comparison_operators(engine):
    assert succeeds(engine, "1 < 2.")
    assert fails(engine, "2 < 1.")
    assert succeeds(engine, "2 > 1.")
    assert succeeds(engine, "1 =< 1.")
    assert succeeds(engine, "1 >= 1.")
    assert succeeds(engine, "1 =:= 1.0.")
    assert succeeds(engine, "1 =\\= 2.")
    assert fails(engine, "1 =\\= 1.")


def test_struct_eq_and_neq(engine):
    assert succeeds(engine, "f(1,2) == f(1,2).")
    assert fails(engine, "f(1,2) == f(1,3).")
    assert succeeds(engine, "f(1,2) \\== f(1,3).")


def test_atomic_compound_callable(engine):
    assert succeeds(engine, "atomic(a).")
    assert succeeds(engine, "atomic(1).")
    assert fails(engine, "atomic(f(1)).")
    assert succeeds(engine, "compound(f(1)).")
    assert fails(engine, "compound(a).")
    assert succeeds(engine, "callable(a).")
    assert succeeds(engine, "callable(f(1)).")
    assert fails(engine, "callable(1).")


def test_true_and_fail(engine):
    assert succeeds(engine, "true.")
    assert fails(engine, "fail.")
    assert fails(engine, "false.")


def test_write_and_nl_produce_output(engine, capsys):
    assert succeeds(engine, "write(hello), nl.")
    out = capsys.readouterr().out
    assert out == "hello\n"


def test_halt_raises_halt_signal_with_code():
    eng = make_engine()
    with pytest.raises(HaltSignal) as exc:
        list(eng.solve_top(parse_term("halt.")))
    assert exc.value.code == 0

    eng2 = make_engine()
    with pytest.raises(HaltSignal) as exc2:
        list(eng2.solve_top(parse_term("halt(7).")))
    assert exc2.value.code == 7


def test_zero_and_negative_arithmetic_edge_cases(engine):
    from conftest import solutions

    assert solutions(engine, "X is 0 * 5.") == ["X = 0."]
    assert solutions(engine, "X is abs(-5).") == ["X = 5."]
    assert solutions(engine, "X is -(-3).") == ["X = 3."]


def test_division_by_zero_raises(engine):
    from horn.errors import HornError

    with pytest.raises(HornError, match="zero_divisor"):
        list(engine.solve_top(parse_term("X is 1 / 0.")))
    with pytest.raises(HornError, match="zero_divisor"):
        list(engine.solve_top(parse_term("X is 1 // 0.")))
    with pytest.raises(HornError, match="zero_divisor"):
        list(engine.solve_top(parse_term("X is 1 mod 0.")))
