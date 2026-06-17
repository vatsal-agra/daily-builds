"""Reductions of real problems to CNF, each with a decoder and an *independent*
validator (we never trust "the solver said so" — we check the decoded solution
against the problem's own rules).

Every encoder returns (CNF, meta) where `meta` carries whatever the matching
decoder needs to turn a SAT model back into a solution.
"""
from __future__ import annotations

import math
from itertools import combinations
from typing import List, Tuple, Dict, Optional

from .cnf import CNF


# ---- generic helpers -----------------------------------------------------
def at_least_one(cnf: CNF, lits: List[int]) -> None:
    cnf.add_clause(list(lits))


def at_most_one(cnf: CNF, lits: List[int]) -> None:
    for a, b in combinations(lits, 2):
        cnf.add_clause([-a, -b])


def exactly_one(cnf: CNF, lits: List[int]) -> None:
    at_least_one(cnf, lits)
    at_most_one(cnf, lits)


# =========================================================================
# Sudoku
# =========================================================================
def _sudoku_var(r: int, c: int, d: int, n: int) -> int:
    # r,c in 0..n-1 ; d in 1..n
    return r * n * n + c * n + (d - 1) + 1


def parse_sudoku(text: str, n: int = 9) -> List[List[int]]:
    """Parse a grid from a string of n*n cells. '.', '0' and '_' are blanks.
    For n>9, cells must be whitespace-separated."""
    if n <= 9:
        chars = [ch for ch in text if not ch.isspace()]
        if len(chars) != n * n:
            raise ValueError(f"expected {n*n} cells, got {len(chars)}")
        vals = [0 if ch in ".0_" else int(ch) for ch in chars]
    else:
        toks = text.split()
        if len(toks) != n * n:
            raise ValueError(f"expected {n*n} cells, got {len(toks)}")
        vals = [0 if t in (".", "0", "_") else int(t) for t in toks]
    grid = [vals[i * n:(i + 1) * n] for i in range(n)]
    return grid


def encode_sudoku(givens: List[List[int]], n: int = 9) -> Tuple[CNF, Dict]:
    box = int(round(math.sqrt(n)))
    if box * box != n:
        raise ValueError("sudoku size must be a perfect square")
    cnf = CNF()
    cnf.num_vars = n * n * n
    cnf.comments.append(f"sudoku {n}x{n}")

    # each cell has exactly one digit
    for r in range(n):
        for c in range(n):
            exactly_one(cnf, [_sudoku_var(r, c, d, n) for d in range(1, n + 1)])
    # each digit at most once per row / column
    for d in range(1, n + 1):
        for r in range(n):
            at_most_one(cnf, [_sudoku_var(r, c, d, n) for c in range(n)])
        for c in range(n):
            at_most_one(cnf, [_sudoku_var(r, c, d, n) for r in range(n)])
        # each digit at most once per box
        for br in range(0, n, box):
            for bc in range(0, n, box):
                cells = [_sudoku_var(br + i, bc + j, d, n)
                         for i in range(box) for j in range(box)]
                at_most_one(cnf, cells)
    # givens
    for r in range(n):
        for c in range(n):
            v = givens[r][c]
            if v != 0:
                cnf.add_clause([_sudoku_var(r, c, v, n)])
    return cnf, {"n": n, "givens": givens}


def decode_sudoku(model: Dict[int, bool], meta: Dict) -> List[List[int]]:
    n = meta["n"]
    grid = [[0] * n for _ in range(n)]
    for r in range(n):
        for c in range(n):
            for d in range(1, n + 1):
                if model.get(_sudoku_var(r, c, d, n), False):
                    grid[r][c] = d
                    break
    return grid


def validate_sudoku(grid: List[List[int]], givens: List[List[int]],
                    n: int = 9) -> Tuple[bool, str]:
    box = int(round(math.sqrt(n)))
    full = set(range(1, n + 1))
    for r in range(n):
        if set(grid[r]) != full:
            return False, f"row {r} is not a permutation: {grid[r]}"
    for c in range(n):
        col = {grid[r][c] for r in range(n)}
        if col != full:
            return False, f"column {c} is not a permutation"
    for br in range(0, n, box):
        for bc in range(0, n, box):
            cells = {grid[br + i][bc + j] for i in range(box) for j in range(box)}
            if cells != full:
                return False, f"box ({br},{bc}) is not a permutation"
    for r in range(n):
        for c in range(n):
            if givens[r][c] != 0 and grid[r][c] != givens[r][c]:
                return False, f"given at ({r},{c}) was overwritten"
    return True, "valid sudoku solution"


# =========================================================================
# N-Queens
# =========================================================================
def _queen_var(r: int, c: int, n: int) -> int:
    return r * n + c + 1


def encode_nqueens(n: int) -> Tuple[CNF, Dict]:
    cnf = CNF()
    cnf.num_vars = n * n
    cnf.comments.append(f"{n}-queens")
    # exactly one queen per row
    for r in range(n):
        exactly_one(cnf, [_queen_var(r, c, n) for c in range(n)])
    # at most one per column
    for c in range(n):
        at_most_one(cnf, [_queen_var(r, c, n) for r in range(n)])
    # at most one per diagonal (both directions)
    diag1: Dict[int, List[int]] = {}
    diag2: Dict[int, List[int]] = {}
    for r in range(n):
        for c in range(n):
            diag1.setdefault(r - c, []).append(_queen_var(r, c, n))
            diag2.setdefault(r + c, []).append(_queen_var(r, c, n))
    for lits in list(diag1.values()) + list(diag2.values()):
        if len(lits) > 1:
            at_most_one(cnf, lits)
    return cnf, {"n": n}


def decode_nqueens(model: Dict[int, bool], meta: Dict) -> List[int]:
    n = meta["n"]
    pos = [-1] * n
    for r in range(n):
        for c in range(n):
            if model.get(_queen_var(r, c, n), False):
                pos[r] = c
                break
    return pos


def validate_nqueens(pos: List[int], n: int) -> Tuple[bool, str]:
    if len(pos) != n or any(c < 0 for c in pos):
        return False, "not every row has a queen"
    if len(set(pos)) != n:
        return False, "two queens share a column"
    for r1, r2 in combinations(range(n), 2):
        if abs(pos[r1] - pos[r2]) == abs(r1 - r2):
            return False, f"queens at rows {r1},{r2} share a diagonal"
    return True, f"valid {n}-queens placement"


# =========================================================================
# Graph k-coloring
# =========================================================================
def _color_var(v: int, c: int, k: int) -> int:
    # v in 0..V-1 ; c in 0..k-1
    return v * k + c + 1


def encode_coloring(num_vertices: int, edges: List[Tuple[int, int]],
                    k: int) -> Tuple[CNF, Dict]:
    cnf = CNF()
    cnf.num_vars = num_vertices * k
    cnf.comments.append(f"{k}-coloring of V={num_vertices} E={len(edges)}")
    for v in range(num_vertices):
        exactly_one(cnf, [_color_var(v, c, k) for c in range(k)])
    for (u, v) in edges:
        for c in range(k):
            cnf.add_clause([-_color_var(u, c, k), -_color_var(v, c, k)])
    return cnf, {"V": num_vertices, "edges": edges, "k": k}


def decode_coloring(model: Dict[int, bool], meta: Dict) -> List[int]:
    V, k = meta["V"], meta["k"]
    colors = [-1] * V
    for v in range(V):
        for c in range(k):
            if model.get(_color_var(v, c, k), False):
                colors[v] = c
                break
    return colors


def validate_coloring(colors: List[int], meta: Dict) -> Tuple[bool, str]:
    V, edges, k = meta["V"], meta["edges"], meta["k"]
    if any(c < 0 or c >= k for c in colors):
        return False, "a vertex has no valid color"
    for (u, v) in edges:
        if colors[u] == colors[v]:
            return False, f"edge ({u},{v}) endpoints share color {colors[u]}"
    return True, f"valid {k}-coloring"


# =========================================================================
# Pigeonhole PHP(p, h): p pigeons into h holes — UNSAT iff p > h
# =========================================================================
def _php_var(i: int, j: int, holes: int) -> int:
    return i * holes + j + 1


def encode_pigeonhole(pigeons: int, holes: int) -> Tuple[CNF, Dict]:
    cnf = CNF()
    cnf.num_vars = pigeons * holes
    cnf.comments.append(f"pigeonhole {pigeons} pigeons, {holes} holes")
    # every pigeon occupies at least one hole
    for i in range(pigeons):
        at_least_one(cnf, [_php_var(i, j, holes) for j in range(holes)])
    # no two pigeons share a hole
    for j in range(holes):
        for i1, i2 in combinations(range(pigeons), 2):
            cnf.add_clause([-_php_var(i1, j, holes), -_php_var(i2, j, holes)])
    return cnf, {"pigeons": pigeons, "holes": holes}
