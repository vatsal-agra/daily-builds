"""The pigeonhole principle PHP(m, n): place m pigeons into n holes with no two
pigeons sharing a hole. Satisfiable iff m <= n; PHP(n+1, n) is the classic
exponentially-hard UNSAT family for resolution.

p[i][j] true iff pigeon i is in hole j.
"""
from __future__ import annotations

from typing import Dict, List, Optional

from ..model import Model
from ..solver import solve_cnf


class Pigeonhole:
    def __init__(self, pigeons: int, holes: int):
        if pigeons < 0 or holes < 0:
            raise ValueError("counts must be non-negative")
        self.m = pigeons
        self.n = holes
        self.model = Model()
        self.p = [[self.model.new_var(f"p{i}_{j}") for j in range(holes)]
                  for i in range(pigeons)]
        self._encode()

    def _encode(self) -> None:
        m = self.model
        # every pigeon is in at least one hole
        for i in range(self.m):
            m.at_least_one(self.p[i]) if self.n > 0 else m.cnf.add_clause([])
        # no hole holds two pigeons
        for j in range(self.n):
            m.at_most_one([self.p[i][j] for i in range(self.m)])

    def decode(self, model: Dict[int, bool]) -> List[int]:
        out = [-1] * self.m
        for i in range(self.m):
            for j in range(self.n):
                if model.get(self.p[i][j]):
                    out[i] = j
        return out

    def solve(self, **kw) -> Optional[List[int]]:
        res, model, _ = solve_cnf(self.model.cnf, **kw)
        if res is not True:
            return None
        return self.decode(model)
