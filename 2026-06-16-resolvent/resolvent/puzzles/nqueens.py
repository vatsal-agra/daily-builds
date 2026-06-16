"""N-Queens <-> CNF. q[r][c] true iff a queen sits on (r,c)."""
from __future__ import annotations

from typing import Dict, List, Optional

from ..model import Model
from ..solver import solve_cnf


class NQueens:
    def __init__(self, n: int):
        if n < 1:
            raise ValueError("n must be >= 1")
        self.n = n
        self.model = Model()
        self.q = [[self.model.new_var(f"q{r}_{c}") for c in range(n)] for r in range(n)]
        self._encode()

    def _encode(self) -> None:
        n = self.n
        m = self.model
        # exactly one queen per row
        for r in range(n):
            m.exactly_one(self.q[r])
        # at most one per column
        for c in range(n):
            m.at_most_one([self.q[r][c] for r in range(n)])
        # at most one per diagonal (both directions)
        diags: Dict[int, List[int]] = {}
        anti: Dict[int, List[int]] = {}
        for r in range(n):
            for c in range(n):
                diags.setdefault(r - c, []).append(self.q[r][c])
                anti.setdefault(r + c, []).append(self.q[r][c])
        for cells in diags.values():
            m.at_most_one(cells)
        for cells in anti.values():
            m.at_most_one(cells)

    def decode(self, model: Dict[int, bool]) -> List[int]:
        """Return a list ``cols`` where cols[r] is the queen's column in row r."""
        n = self.n
        cols = [-1] * n
        for r in range(n):
            for c in range(n):
                if model.get(self.q[r][c]):
                    cols[r] = c
        return cols

    def solve(self, **kw) -> Optional[List[int]]:
        res, model, _ = solve_cnf(self.model.cnf, **kw)
        if res is not True:
            return None
        return self.decode(model)


def is_valid(cols: List[int]) -> bool:
    n = len(cols)
    if any(c < 0 or c >= n for c in cols):
        return False
    if len(set(cols)) != n:
        return False
    for r1 in range(n):
        for r2 in range(r1 + 1, n):
            if abs(cols[r1] - cols[r2]) == abs(r1 - r2):
                return False
    return True


def render(cols: List[int]) -> str:
    n = len(cols)
    lines = []
    for r in range(n):
        row = ["Q" if cols[r] == c else "." for c in range(n)]
        lines.append(" ".join(row))
    return "\n".join(lines)
