"""Sudoku <-> CNF.

Supports any N²×N² board (N=3 is classic 9×9). Variable x(r,c,d) is true iff
cell (r,c) holds digit d (1..N²).
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Tuple

from ..model import Model
from ..solver import solve_cnf


def _box_dim(size: int) -> int:
    b = int(round(math.sqrt(size)))
    if b * b != size:
        raise ValueError(f"board size {size} is not a perfect square")
    return b


def parse_grid(text: str) -> List[List[int]]:
    """Parse a grid. Accepts rows of space/comma separated ints, or a single
    string of digits with '.'/'0' for blanks (9×9 only for the compact form)."""
    text = text.strip()
    rows: List[List[int]] = []
    lines = [ln for ln in text.splitlines() if ln.strip() and not ln.strip().startswith("#")]
    # Single compact line of digits/dots (e.g. an 81-char 9x9 string).
    if len(lines) == 1 and " " not in lines[0] and "," not in lines[0]:
        s = lines[0].strip()
        size = int(round(math.sqrt(len(s))))
        if size * size != len(s):
            raise ValueError("compact grid length is not a perfect square")
        for r in range(size):
            rows.append([0 if ch in ".0" else int(ch) for ch in s[r * size:(r + 1) * size]])
        return rows
    for ln in lines:
        ln = ln.strip()
        if "," in ln or " " in ln:
            toks = ln.replace(",", " ").split()
            rows.append([0 if t in (".", "0") else int(t) for t in toks])
        else:
            # contiguous string of single-character cells, one row per line
            rows.append([0 if ch in ".0" else int(ch) for ch in ln])
    return rows


class Sudoku:
    def __init__(self, given: List[List[int]]):
        self.size = len(given)
        if any(len(row) != self.size for row in given):
            raise ValueError("grid must be square")
        self.box = _box_dim(self.size)
        self.given = given
        self.model = Model()
        n = self.size
        # x[r][c][d] for d in 1..n
        self.x = [[[self.model.new_var(f"x{r}_{c}_{d}") for d in range(1, n + 1)]
                   for c in range(n)] for r in range(n)]
        self._encode()

    def var(self, r: int, c: int, d: int) -> int:
        return self.x[r][c][d - 1]

    def _encode(self) -> None:
        n = self.size
        m = self.model
        # each cell exactly one digit
        for r in range(n):
            for c in range(n):
                m.exactly_one(self.x[r][c])
        # each digit exactly once per row and per column
        for d in range(n):
            for r in range(n):
                m.exactly_one([self.x[r][c][d] for c in range(n)])
            for c in range(n):
                m.exactly_one([self.x[r][c][d] for r in range(n)])
        # each digit exactly once per box
        b = self.box
        for d in range(n):
            for br in range(0, n, b):
                for bc in range(0, n, b):
                    cells = [self.x[br + i][bc + j][d]
                             for i in range(b) for j in range(b)]
                    m.exactly_one(cells)
        # givens as unit clauses
        for r in range(n):
            for c in range(n):
                g = self.given[r][c]
                if g:
                    if not (1 <= g <= n):
                        raise ValueError(f"given {g} out of range at ({r},{c})")
                    m.cnf.add_clause([self.var(r, c, g)])

    def decode(self, model: Dict[int, bool]) -> List[List[int]]:
        n = self.size
        out = [[0] * n for _ in range(n)]
        for r in range(n):
            for c in range(n):
                for d in range(1, n + 1):
                    if model.get(self.var(r, c, d)):
                        out[r][c] = d
                        break
        return out

    def solve(self, **kw) -> Optional[List[List[int]]]:
        res, model, _ = solve_cnf(self.model.cnf, **kw)
        if res is not True:
            return None
        return self.decode(model)


def is_valid_solution(grid: List[List[int]]) -> bool:
    n = len(grid)
    b = _box_dim(n)
    full = set(range(1, n + 1))
    for r in range(n):
        if set(grid[r]) != full:
            return False
    for c in range(n):
        if set(grid[r][c] for r in range(n)) != full:
            return False
    for br in range(0, n, b):
        for bc in range(0, n, b):
            cells = {grid[br + i][bc + j] for i in range(b) for j in range(b)}
            if cells != full:
                return False
    return True


def render(grid: List[List[int]]) -> str:
    n = len(grid)
    b = _box_dim(n)
    w = len(str(n))
    lines = []
    for r in range(n):
        if r and r % b == 0:
            sep = "+".join(["-" * ((w + 1) * b + 1) for _ in range(b)])
            lines.append(sep)
        cells = []
        for c in range(n):
            if c and c % b == 0:
                cells.append("|")
            v = grid[r][c]
            cells.append(str(v).rjust(w) if v else "." * w)
        lines.append(" " + " ".join(cells))
    return "\n".join(lines)
