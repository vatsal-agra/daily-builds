"""Encoders: turn real combinatorial problems into CNF, and decode models back.

Each encoder returns ``(cnf, meta)`` where ``meta`` carries whatever the matching
decoder needs (variable maps, dimensions). Decoders take a solver model
(``{var: bool}``) and produce a human-readable solution.

Supported problems:
    * Sudoku (any n²×n² grid; default 9×9)
    * Graph k-colouring
    * N-Queens
    * Pigeonhole (m pigeons into n holes — UNSAT iff m > n)
"""

from __future__ import annotations

from typing import Dict, List, Optional, Sequence, Tuple

from .cnf import CNF


# --------------------------------------------------------------------------
# Cardinality building blocks
# --------------------------------------------------------------------------
def at_least_one(cnf: CNF, lits: Sequence[int]):
    cnf.add_clause(list(lits))


def at_most_one_pairwise(cnf: CNF, lits: Sequence[int]):
    """Pairwise (naive) at-most-one: O(k²) binary clauses. Fine for small k."""
    lits = list(lits)
    for i in range(len(lits)):
        for j in range(i + 1, len(lits)):
            cnf.add_clause([-lits[i], -lits[j]])


def at_most_one_sequential(cnf: CNF, lits: Sequence[int], fresh) -> None:
    """Sinz's sequential (ladder) at-most-one: O(k) clauses, k-1 aux vars.

    ``fresh`` is a zero-arg callable returning a new variable index.
    """
    lits = list(lits)
    n = len(lits)
    if n <= 1:
        return
    s = [fresh() for _ in range(n - 1)]
    cnf.add_clause([-lits[0], s[0]])
    cnf.add_clause([-lits[n - 1], -s[n - 2]])
    for i in range(1, n - 1):
        cnf.add_clause([-lits[i], s[i]])
        cnf.add_clause([-s[i - 1], s[i]])
        cnf.add_clause([-lits[i], -s[i - 1]])


def exactly_one(cnf: CNF, lits: Sequence[int], fresh=None, mode: str = "pairwise"):
    at_least_one(cnf, lits)
    if mode == "sequential" and fresh is not None and len(lits) > 5:
        at_most_one_sequential(cnf, lits, fresh)
    else:
        at_most_one_pairwise(cnf, lits)


class _Fresh:
    """Allocates fresh variable indices above an existing maximum."""

    def __init__(self, start: int):
        self.n = start

    def __call__(self) -> int:
        self.n += 1
        return self.n


# --------------------------------------------------------------------------
# Sudoku
# --------------------------------------------------------------------------
def sudoku_encode(grid: List[List[int]], box: Optional[int] = None
                  ) -> Tuple[CNF, dict]:
    """Encode a Sudoku.

    ``grid`` is an N×N matrix of clues, 0 = blank. N must be a perfect square
    (default box size = sqrt(N)). Variable v(r,c,d) is true iff cell (r,c) holds
    digit d (1-indexed everywhere).
    """
    n = len(grid)
    for row in grid:
        if len(row) != n:
            raise ValueError("Sudoku grid must be square")
    if box is None:
        box = int(round(n ** 0.5))
    if box * box != n:
        raise ValueError(f"grid size {n} is not a perfect square (box={box})")

    cnf = CNF()

    def v(r, c, d):
        return (r * n + c) * n + d  # 1-indexed because d in 1..n and r,c>=0 -> >=1

    fresh = _Fresh(n * n * n)

    # each cell has exactly one digit
    for r in range(n):
        for c in range(n):
            exactly_one(cnf, [v(r, c, d) for d in range(1, n + 1)], fresh,
                        mode="sequential")
    # each digit appears once per row, column, box
    for d in range(1, n + 1):
        for r in range(n):
            exactly_one(cnf, [v(r, c, d) for c in range(n)], fresh,
                        mode="sequential")
        for c in range(n):
            exactly_one(cnf, [v(r, c, d) for r in range(n)], fresh,
                        mode="sequential")
        for br in range(0, n, box):
            for bc in range(0, n, box):
                cells = [v(br + i, bc + j, d)
                         for i in range(box) for j in range(box)]
                exactly_one(cnf, cells, fresh, mode="sequential")
    # clues
    for r in range(n):
        for c in range(n):
            if grid[r][c] != 0:
                cnf.add_clause([v(r, c, grid[r][c])])

    cnf.nvars = max(cnf.nvars, fresh.n)
    return cnf, {"n": n, "box": box, "v": v}


def sudoku_decode(model: Dict[int, bool], meta: dict) -> List[List[int]]:
    n = meta["n"]
    v = meta["v"]
    out = [[0] * n for _ in range(n)]
    for r in range(n):
        for c in range(n):
            for d in range(1, n + 1):
                if model.get(v(r, c, d)):
                    out[r][c] = d
                    break
    return out


def sudoku_format(grid: List[List[int]]) -> str:
    n = len(grid)
    box = int(round(n ** 0.5))
    width = len(str(n))
    lines = []
    for r in range(n):
        if r % box == 0 and r != 0:
            sep = "+".join("-" * (box * (width + 1) + 1) for _ in range(box))
            lines.append(sep)
        cells = []
        for c in range(n):
            if c % box == 0 and c != 0:
                cells.append("|")
            x = grid[r][c]
            cells.append((str(x) if x else ".").rjust(width))
        lines.append(" " + " ".join(cells))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Graph colouring
# --------------------------------------------------------------------------
def graph_coloring_encode(n_nodes: int, edges: Sequence[Tuple[int, int]],
                          k: int) -> Tuple[CNF, dict]:
    """k-colour an undirected graph on nodes 0..n_nodes-1.

    Variable c(node, colour) is true iff node has that colour (colours 1..k).
    """
    cnf = CNF()

    def c(node, colour):
        return node * k + colour  # node>=0, colour in 1..k -> >=1

    fresh = _Fresh(n_nodes * k)
    for node in range(n_nodes):
        exactly_one(cnf, [c(node, col) for col in range(1, k + 1)], fresh,
                    mode="sequential")
    for (a, b) in edges:
        if a == b:
            continue
        for col in range(1, k + 1):
            cnf.add_clause([-c(a, col), -c(b, col)])
    cnf.nvars = max(cnf.nvars, fresh.n)
    return cnf, {"n_nodes": n_nodes, "k": k, "c": c}


def graph_coloring_decode(model: Dict[int, bool], meta: dict) -> List[int]:
    n_nodes = meta["n_nodes"]
    k = meta["k"]
    c = meta["c"]
    out = [0] * n_nodes
    for node in range(n_nodes):
        for col in range(1, k + 1):
            if model.get(c(node, col)):
                out[node] = col
                break
    return out


# --------------------------------------------------------------------------
# N-Queens
# --------------------------------------------------------------------------
def nqueens_encode(n: int) -> Tuple[CNF, dict]:
    """Place n non-attacking queens on an n×n board.

    Variable q(r,c) true iff a queen sits at (r,c).
    """
    cnf = CNF()

    def q(r, c):
        return r * n + c + 1  # 1-indexed

    # exactly one queen per row, at most one per column
    for r in range(n):
        exactly_one(cnf, [q(r, c) for c in range(n)], None, mode="pairwise")
    for c in range(n):
        at_most_one_pairwise(cnf, [q(r, c) for r in range(n)])
    # diagonals: at most one per each of the two diagonal families
    for d in range(-(n - 1), n):
        cells = [q(r, r - d) for r in range(n) if 0 <= r - d < n]
        at_most_one_pairwise(cnf, cells)
    for s in range(0, 2 * n - 1):
        cells = [q(r, s - r) for r in range(n) if 0 <= s - r < n]
        at_most_one_pairwise(cnf, cells)
    cnf.nvars = max(cnf.nvars, n * n)
    return cnf, {"n": n, "q": q}


def nqueens_decode(model: Dict[int, bool], meta: dict) -> List[int]:
    """Return a list ``col_of_row`` giving the queen's column in each row."""
    n = meta["n"]
    q = meta["q"]
    out = [-1] * n
    for r in range(n):
        for c in range(n):
            if model.get(q(r, c)):
                out[r] = c
                break
    return out


def nqueens_format(cols: List[int]) -> str:
    n = len(cols)
    lines = []
    for r in range(n):
        lines.append(" ".join("Q" if cols[r] == c else "." for c in range(n)))
    return "\n".join(lines)


# --------------------------------------------------------------------------
# Pigeonhole — the canonical hard UNSAT family
# --------------------------------------------------------------------------
def pigeonhole_encode(m_pigeons: int, n_holes: int) -> Tuple[CNF, dict]:
    """Place m pigeons in n holes, one pigeon per hole. UNSAT iff m > n.

    Variable p(i,j) true iff pigeon i sits in hole j.
    """
    cnf = CNF()

    def p(i, j):
        return i * n_holes + j + 1  # 1-indexed

    # every pigeon is in some hole
    for i in range(m_pigeons):
        at_least_one(cnf, [p(i, j) for j in range(n_holes)])
    # no two pigeons share a hole
    for j in range(n_holes):
        for i1 in range(m_pigeons):
            for i2 in range(i1 + 1, m_pigeons):
                cnf.add_clause([-p(i1, j), -p(i2, j)])
    cnf.nvars = max(cnf.nvars, m_pigeons * n_holes)
    return cnf, {"m": m_pigeons, "n": n_holes, "p": p}
