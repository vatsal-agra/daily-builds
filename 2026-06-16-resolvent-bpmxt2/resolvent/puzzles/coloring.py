"""Graph K-coloring <-> CNF. c[v][k] true iff vertex v has color k."""
from __future__ import annotations

from typing import Dict, List, Optional, Tuple

from ..model import Model
from ..solver import solve_cnf

Edge = Tuple[int, int]


class Coloring:
    def __init__(self, n_vertices: int, edges: List[Edge], k: int):
        if k < 1:
            raise ValueError("k must be >= 1")
        self.n = n_vertices
        self.k = k
        self.edges = [(min(a, b), max(a, b)) for a, b in edges]
        for a, b in self.edges:
            if not (0 <= a < n_vertices and 0 <= b < n_vertices):
                raise ValueError(f"edge ({a},{b}) out of range")
        self.model = Model()
        self.c = [[self.model.new_var(f"v{v}_c{col}") for col in range(k)]
                  for v in range(n_vertices)]
        self._encode()

    def _encode(self) -> None:
        m = self.model
        for v in range(self.n):
            m.exactly_one(self.c[v])
        for a, b in self.edges:
            if a == b:
                continue  # self-loops can't be properly colored; skip (handled by solve being UNSAT only if forced)
            for col in range(self.k):
                m.cnf.add_clause([-self.c[a][col], -self.c[b][col]])

    def decode(self, model: Dict[int, bool]) -> List[int]:
        out = [-1] * self.n
        for v in range(self.n):
            for col in range(self.k):
                if model.get(self.c[v][col]):
                    out[v] = col
                    break
        return out

    def solve(self, **kw) -> Optional[List[int]]:
        res, model, _ = solve_cnf(self.model.cnf, **kw)
        if res is not True:
            return None
        return self.decode(model)


def is_valid(coloring: List[int], edges: List[Edge], k: int) -> bool:
    if any(c < 0 or c >= k for c in coloring):
        return False
    for a, b in edges:
        if a == b:
            continue
        if coloring[a] == coloring[b]:
            return False
    return True


def parse_graph(text: str) -> Tuple[int, List[Edge]]:
    """Parse a simple edge-list. First non-comment token line may be ``n``;
    otherwise n is inferred. Each subsequent line is ``a b`` (0-indexed)."""
    edges: List[Edge] = []
    n = 0
    explicit_n = None
    lines = [ln.strip() for ln in text.splitlines()
             if ln.strip() and not ln.strip().startswith("#")]
    i = 0
    if lines and len(lines[0].split()) == 1:
        explicit_n = int(lines[0])
        i = 1
    for ln in lines[i:]:
        toks = ln.replace(",", " ").split()
        if len(toks) < 2:
            continue
        a, b = int(toks[0]), int(toks[1])
        edges.append((a, b))
        n = max(n, a + 1, b + 1)
    if explicit_n is not None:
        n = max(n, explicit_n)
    return n, edges
