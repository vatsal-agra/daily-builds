"""Prolog-level and Python-level exceptions shared by both engines."""
from .terms import Atom, Struct, Num, Var


class PrologError(Exception):
    """Wraps a Prolog error term thrown by throw/1 or a built-in."""

    def __init__(self, term):
        self.term = term
        super().__init__(str(term))


class Cut(Exception):
    """Internal control-flow signal used by both the golden-model
    interpreter and the WAM's meta-call helpers to implement `!`."""

    def __init__(self, barrier):
        self.barrier = barrier


def type_error(kind, culprit):
    return PrologError(Struct("error", (Struct("type_error", (Atom(kind), culprit)), Var())))


def instantiation_error():
    return PrologError(Struct("error", (Atom("instantiation_error"), Var())))


def existence_error(kind, culprit):
    return PrologError(Struct("error", (Struct("existence_error", (Atom(kind), culprit)), Var())))


def evaluation_error(kind):
    return PrologError(Struct("error", (Struct("evaluation_error", (Atom(kind),)), Var())))


def domain_error(domain, culprit):
    return PrologError(Struct("error", (Struct("domain_error", (Atom(domain), culprit)), Var())))
