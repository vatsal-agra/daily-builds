import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from horn.engine import make_engine
from horn.parser import parse_term
from horn.repl import format_solution, query_vars

EXAMPLES = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "examples")


@pytest.fixture
def engine():
    return make_engine()


def consult_example(engine, name):
    with open(os.path.join(EXAMPLES, name), encoding="utf-8") as f:
        engine.consult_text(f.read())


def solutions(engine, text, cap=1000):
    """Run a query text against engine, return a list of formatted solution
    strings ("X = 1, Y = 2."), up to `cap` of them."""
    goal = parse_term(text)
    vars_ = query_vars(goal)
    out = []
    for _ in engine.solve_top(goal):
        out.append(format_solution(vars_))
        if len(out) >= cap:
            break
    return out


def succeeds(engine, text):
    return len(solutions(engine, text, cap=1)) == 1


def fails(engine, text):
    return not succeeds(engine, text)
