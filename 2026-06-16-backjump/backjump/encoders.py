"""Encode real combinatorial problems into CNF, and decode models back.

Every encoder produces genuine CNF that is handed to the CDCL solver — there is
no special-case puzzle logic.  The decoders translate a satisfying assignment
back into a human-readable solution.
"""

from __future__ import annotations

from typing import List, Tuple, Dict, Optional
from .cnf import CNF


# --------------------------------------------------------------------------
# helpers for cardinality constraints
# --------------------------------------------------------------------------
def at_least_one(cnf: CNF, lits: List[int]) -> None:
    cnf.add_clause(list(lits))


def at_most_one_pairwise(cnf: CNF, lits: List[int]) -> None:
    for i in range(len(lits)):
        for j in range(i + 1, len(lits)):
            cnf.add_clause([-lits[i], -lits[j]])


def exactly_one(cnf: CNF, lits: List[int]) -> None:
    at_least_one(cnf, lits)
    at_most_one_pairwise(cnf, lits)


# --------------------------------------------------------------------------
# Sudoku  (generalised to n*n grids; n=9 by default, also 4 and 16)
# --------------------------------------------------------------------------
class Sudoku:
    def __init__(self, n: int = 9):
        import math
        self.n = n
        self.box = int(round(math.isqrt(n)))
        if self.box * self.box != n:
            raise ValueError("Sudoku size must be a perfect square (4, 9, 16, ...)")

    def var(self, r: int, c: int, d: int) -> int:
        # r,c in 0..n-1 ; d in 1..n
        return (r * self.n + c) * self.n + d

    def encode(self, givens: Optional[List[List[int]]] = None) -> CNF:
        n = self.n
        cnf = CNF(n * n * n)
        # each cell has exactly one digit
        for r in range(n):
            for c in range(n):
                exactly_one(cnf, [self.var(r, c, d) for d in range(1, n + 1)])
        # each digit appears once per row
        for r in range(n):
            for d in range(1, n + 1):
                exactly_one(cnf, [self.var(r, c, d) for c in range(n)])
        # each digit appears once per column
        for c in range(n):
            for d in range(1, n + 1):
                exactly_one(cnf, [self.var(r, c, d) for r in range(n)])
        # each digit appears once per box
        b = self.box
        for br in range(b):
            for bc in range(b):
                for d in range(1, n + 1):
                    cells = [
                        self.var(br * b + i, bc * b + j, d)
                        for i in range(b) for j in range(b)
                    ]
                    exactly_one(cnf, cells)
        # givens
        if givens:
            for r in range(n):
                for c in range(n):
                    d = givens[r][c]
                    if d != 0:
                        cnf.add_clause([self.var(r, c, d)])
        return cnf

    def decode(self, model) -> List[List[int]]:
        val = _model_set(model)
        n = self.n
        grid = [[0] * n for _ in range(n)]
        for r in range(n):
            for c in range(n):
                for d in range(1, n + 1):
                    if self.var(r, c, d) in val:
                        grid[r][c] = d
                        break
        return grid

    @staticmethod
    def parse_grid(text: str, n: int = 9) -> List[List[int]]:
        """Parse a puzzle from a string.  '.' or '0' are blanks; whitespace and
        newlines are ignored.  For n<=9 it reads single chars; otherwise expects
        whitespace-separated tokens."""
        if n <= 9:
            chars = [ch for ch in text if not ch.isspace()]
            if len(chars) != n * n:
                raise ValueError(f"expected {n*n} cells, got {len(chars)}")
            cells = [0 if ch in ".0" else int(ch) for ch in chars]
        else:
            toks = text.split()
            if len(toks) != n * n:
                raise ValueError(f"expected {n*n} cells, got {len(toks)}")
            cells = [0 if t in (".", "0") else int(t) for t in toks]
        return [cells[i * n:(i + 1) * n] for i in range(n)]

    def render(self, grid: List[List[int]]) -> str:
        n, b = self.n, self.box
        w = len(str(n))
        lines = []
        for r in range(n):
            if r % b == 0 and r != 0:
                seg = "-" * ((w + 1) * b)
                lines.append("+".join([seg[:-1]] * b))
            row = []
            for c in range(n):
                cell = "." if grid[r][c] == 0 else str(grid[r][c])
                row.append(cell.rjust(w))
                if (c + 1) % b == 0 and c != n - 1:
                    row.append("|")
            lines.append(" ".join(row))
        return "\n".join(lines)


# --------------------------------------------------------------------------
# N-Queens
# --------------------------------------------------------------------------
class NQueens:
    def __init__(self, n: int):
        self.n = n

    def var(self, r: int, c: int) -> int:
        return r * self.n + c + 1

    def encode(self) -> CNF:
        n = self.n
        cnf = CNF(n * n)
        # exactly one queen per row
        for r in range(n):
            exactly_one(cnf, [self.var(r, c) for c in range(n)])
        # at most one per column
        for c in range(n):
            at_most_one_pairwise(cnf, [self.var(r, c) for r in range(n)])
        # at most one per diagonal (both directions)
        diag1: Dict[int, List[int]] = {}
        diag2: Dict[int, List[int]] = {}
        for r in range(n):
            for c in range(n):
                diag1.setdefault(r - c, []).append(self.var(r, c))
                diag2.setdefault(r + c, []).append(self.var(r, c))
        for lits in diag1.values():
            if len(lits) > 1:
                at_most_one_pairwise(cnf, lits)
        for lits in diag2.values():
            if len(lits) > 1:
                at_most_one_pairwise(cnf, lits)
        return cnf

    def decode(self, model) -> List[int]:
        """Return a list `cols` where cols[r] is the queen's column in row r."""
        val = _model_set(model)
        n = self.n
        cols = [-1] * n
        for r in range(n):
            for c in range(n):
                if self.var(r, c) in val:
                    cols[r] = c
                    break
        return cols

    def render(self, cols: List[int]) -> str:
        n = self.n
        lines = []
        for r in range(n):
            lines.append(" ".join("Q" if cols[r] == c else "." for c in range(n)))
        return "\n".join(lines)


# --------------------------------------------------------------------------
# Graph k-colouring
# --------------------------------------------------------------------------
class GraphColoring:
    def __init__(self, num_vertices: int, edges: List[Tuple[int, int]], k: int):
        self.v = num_vertices
        self.edges = edges
        self.k = k

    def var(self, vertex: int, color: int) -> int:
        # vertex in 0..v-1 ; color in 0..k-1
        return vertex * self.k + color + 1

    def encode(self) -> CNF:
        cnf = CNF(self.v * self.k)
        # each vertex gets exactly one colour
        for vtx in range(self.v):
            exactly_one(cnf, [self.var(vtx, col) for col in range(self.k)])
        # adjacent vertices differ
        for (a, b) in self.edges:
            for col in range(self.k):
                cnf.add_clause([-self.var(a, col), -self.var(b, col)])
        return cnf

    def decode(self, model) -> List[int]:
        val = _model_set(model)
        colors = [-1] * self.v
        for vtx in range(self.v):
            for col in range(self.k):
                if self.var(vtx, col) in val:
                    colors[vtx] = col
                    break
        return colors


# --------------------------------------------------------------------------
# Pigeonhole principle  (p pigeons into h holes; UNSAT iff p > h)
# --------------------------------------------------------------------------
class Pigeonhole:
    def __init__(self, pigeons: int, holes: int):
        self.p = pigeons
        self.h = holes

    def var(self, pigeon: int, hole: int) -> int:
        return pigeon * self.h + hole + 1

    def encode(self) -> CNF:
        cnf = CNF(self.p * self.h)
        # every pigeon is in at least one hole
        for p in range(self.p):
            at_least_one(cnf, [self.var(p, h) for h in range(self.h)])
        # no two pigeons share a hole
        for h in range(self.h):
            for a in range(self.p):
                for b in range(a + 1, self.p):
                    cnf.add_clause([-self.var(a, h), -self.var(b, h)])
        return cnf


def _model_set(model) -> set:
    if isinstance(model, dict):
        return {v for v, val in model.items() if val}
    return {lit for lit in model if lit > 0}
