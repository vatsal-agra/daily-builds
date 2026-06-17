"""High-level constraint modeling layer that compiles to CNF.

Provides:
  * fresh boolean variables (optionally named),
  * Tseitin encoding of boolean expressions (AND/OR/NOT/XOR/IMPLIES/IFF) into
    CNF with auxiliary variables,
  * cardinality constraints: at_least_one, at_most_one (pairwise + commander),
    exactly_one, and at_most_k / at_least_k / exactly_k via the
    sequential-counter encoding.

Everything ultimately appends clauses to an underlying :class:`CNF`.
"""
from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Union

from .cnf import CNF


class Expr:
    """A boolean expression node for Tseitin encoding.

    Leaves are literals (signed ints). Internal nodes combine sub-expressions.
    Build with the operators below or the module-level helpers.
    """

    __slots__ = ("op", "args")

    def __init__(self, op: str, args):
        self.op = op
        self.args = args

    # operator sugar -------------------------------------------------- #
    def __and__(self, other): return Expr("and", [self, _lift(other)])
    def __or__(self, other): return Expr("or", [self, _lift(other)])
    def __xor__(self, other): return Expr("xor", [self, _lift(other)])
    def __invert__(self): return Expr("not", [self])

    def implies(self, other): return Expr("or", [Expr("not", [self]), _lift(other)])
    def iff(self, other): return Expr("xor", [Expr("not", [self]), _lift(other)])


def _lift(x) -> Expr:
    if isinstance(x, Expr):
        return x
    return Expr("lit", int(x))


def lit(x: int) -> Expr:
    return Expr("lit", int(x))


def AND(*xs) -> Expr: return Expr("and", [_lift(x) for x in xs])
def OR(*xs) -> Expr: return Expr("or", [_lift(x) for x in xs])
def NOT(x) -> Expr: return Expr("not", [_lift(x)])
def XOR(a, b) -> Expr: return Expr("xor", [_lift(a), _lift(b)])
def IMPLIES(a, b) -> Expr: return _lift(a).implies(b)
def IFF(a, b) -> Expr: return _lift(a).iff(b)


class Model:
    def __init__(self):
        self.cnf = CNF()
        self.names: Dict[int, str] = {}

    # ------------------------------------------------------------------ #
    # variables                                                          #
    # ------------------------------------------------------------------ #
    def new_var(self, name: Optional[str] = None) -> int:
        v = self.cnf.new_var()
        if name:
            self.names[v] = name
        return v

    def new_vars(self, n: int, prefix: str = "") -> List[int]:
        return [self.new_var(f"{prefix}{i}" if prefix else None) for i in range(n)]

    def add_clause(self, lits: Sequence[int]) -> None:
        self.cnf.add_clause(lits)

    # ------------------------------------------------------------------ #
    # Tseitin encoding of arbitrary boolean expressions                  #
    # ------------------------------------------------------------------ #
    def encode(self, expr: Union[Expr, int]) -> int:
        """Return a literal equivalent to ``expr``, adding defining clauses."""
        expr = _lift(expr)
        return self._tseitin(expr)

    def add(self, expr: Union[Expr, int]) -> None:
        """Assert that ``expr`` is true."""
        lit_ = self.encode(expr)
        self.cnf.add_clause([lit_])

    def _tseitin(self, e: Expr) -> int:
        if e.op == "lit":
            return e.args
        if e.op == "not":
            return -self._tseitin(e.args[0])
        sub = [self._tseitin(a) for a in e.args]
        if e.op == "and":
            return self._and(sub)
        if e.op == "or":
            return self._or(sub)
        if e.op == "xor":
            assert len(sub) == 2
            return self._xor(sub[0], sub[1])
        raise ValueError(f"unknown op {e.op}")

    def _and(self, lits: List[int]) -> int:
        if len(lits) == 1:
            return lits[0]
        z = self.cnf.new_var()
        # z <-> AND(lits): (z -> each lit) and (all lits -> z)
        for l in lits:
            self.cnf.add_clause([-z, l])
        self.cnf.add_clause([z] + [-l for l in lits])
        return z

    def _or(self, lits: List[int]) -> int:
        if len(lits) == 1:
            return lits[0]
        z = self.cnf.new_var()
        # z <-> OR(lits)
        for l in lits:
            self.cnf.add_clause([z, -l])
        self.cnf.add_clause([-z] + list(lits))
        return z

    def _xor(self, a: int, b: int) -> int:
        z = self.cnf.new_var()
        # z <-> (a XOR b)
        self.cnf.add_clause([-z, -a, -b])
        self.cnf.add_clause([-z, a, b])
        self.cnf.add_clause([z, -a, b])
        self.cnf.add_clause([z, a, -b])
        return z

    # ------------------------------------------------------------------ #
    # cardinality constraints                                            #
    # ------------------------------------------------------------------ #
    def at_least_one(self, lits: Sequence[int]) -> None:
        if not lits:
            self.cnf.add_clause([])  # empty -> UNSAT
            return
        self.cnf.add_clause(list(lits))

    def at_most_one(self, lits: Sequence[int]) -> None:
        """At most one of ``lits`` is true.

        Pairwise for small sets; a commander/sequential encoding for large sets
        to keep the clause count near-linear.
        """
        lits = list(lits)
        if len(lits) <= 1:
            return
        if len(lits) <= 5:
            for i in range(len(lits)):
                for j in range(i + 1, len(lits)):
                    self.cnf.add_clause([-lits[i], -lits[j]])
            return
        self._amo_sequential(lits)

    def _amo_sequential(self, lits: List[int]) -> None:
        # sequential counter (Sinz) for k=1
        n = len(lits)
        s = [self.cnf.new_var() for _ in range(n - 1)]
        self.cnf.add_clause([-lits[0], s[0]])
        for i in range(1, n - 1):
            self.cnf.add_clause([-lits[i], s[i]])
            self.cnf.add_clause([-s[i - 1], s[i]])
            self.cnf.add_clause([-lits[i], -s[i - 1]])
        self.cnf.add_clause([-lits[n - 1], -s[n - 2]])

    def exactly_one(self, lits: Sequence[int]) -> None:
        self.at_least_one(lits)
        self.at_most_one(lits)

    def at_most_k(self, lits: Sequence[int], k: int) -> None:
        """Sinz sequential-counter encoding of sum(lits) <= k."""
        lits = list(lits)
        n = len(lits)
        if k < 0:
            self.cnf.add_clause([])
            return
        if k >= n:
            return
        if k == 0:
            for l in lits:
                self.cnf.add_clause([-l])
            return
        # register s[i][j] meaning "at least j+1 of the first i+1 lits are true"
        s = [[self.cnf.new_var() for _ in range(k)] for _ in range(n)]
        # first variable
        self.cnf.add_clause([-lits[0], s[0][0]])
        for j in range(1, k):
            self.cnf.add_clause([-s[0][j]])
        for i in range(1, n):
            self.cnf.add_clause([-lits[i], s[i][0]])
            self.cnf.add_clause([-s[i - 1][0], s[i][0]])
            for j in range(1, k):
                self.cnf.add_clause([-lits[i], -s[i - 1][j - 1], s[i][j]])
                self.cnf.add_clause([-s[i - 1][j], s[i][j]])
            self.cnf.add_clause([-lits[i], -s[i - 1][k - 1]])

    def at_least_k(self, lits: Sequence[int], k: int) -> None:
        # sum(lits) >= k  <=>  sum(not lits) <= n-k
        lits = list(lits)
        self.at_most_k([-l for l in lits], len(lits) - k)

    def exactly_k(self, lits: Sequence[int], k: int) -> None:
        self.at_least_k(lits, k)
        self.at_most_k(lits, k)
