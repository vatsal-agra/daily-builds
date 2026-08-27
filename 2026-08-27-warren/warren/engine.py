"""Top-level Engine: wires together the parser, the WAM (default
execution backend), and the golden-model interpreter (available as an
oracle / alternate backend), behind one uniform API."""
import os
import sys

from .parser import parse_program, Parser
from .golden import Interpreter as GoldenInterpreter
from .machine import Machine
from .pretty import term_to_str

_BOOTSTRAP_PATH = os.path.join(os.path.dirname(__file__), "bootstrap.pl")


def _load_bootstrap_text():
    with open(_BOOTSTRAP_PATH, encoding="utf-8") as f:
        return f.read()


class Engine:
    """backend: 'wam' (default, real compiled execution) or 'golden'
    (the reference tree-walking SLD interpreter)."""

    def __init__(self, backend="wam", out=None, load_bootstrap=True):
        self.backend = backend
        self.out = out if out is not None else sys.stdout
        if backend == "wam":
            self.impl = Machine(out=self.out)
        elif backend == "golden":
            self.impl = GoldenInterpreter(out=self.out)
        else:
            raise ValueError(f"unknown backend {backend!r}")
        if load_bootstrap:
            self.consult_string(_load_bootstrap_text())

    def consult_string(self, text):
        terms = parse_program(text)
        self.impl.consult_terms(terms)

    def consult_file(self, path):
        with open(path, encoding="utf-8") as f:
            self.consult_string(f.read())

    def query_text(self, text):
        """text is a goal without trailing '.'; returns a generator of
        solution dicts {varname: Term}."""
        p = Parser(text if text.rstrip().endswith(".") else text + ".")
        goal = p.read_clause()
        return self.impl.query(goal)

    def query_term(self, goal):
        return self.impl.query(goal)

    def solve_once_text(self, text):
        for sol in self.query_text(text):
            return sol
        return None


def make_dual_engines(out=None):
    """Convenience for differential testing: two fresh engines sharing
    the same bootstrap library, one on each backend."""
    return Engine(backend="wam", out=out), Engine(backend="golden", out=out)
