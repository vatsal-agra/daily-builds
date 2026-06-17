"""Encode real combinatorial problems into CNF, and decode SAT models back into
human-readable solutions. Covers N-Queens, graph coloring, Sudoku, and the
pigeonhole principle (a family of guaranteed-UNSAT stress tests)."""
from __future__ import annotations

from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .cnf import CNF


class Encoding:
    """A CNF together with the metadata needed to decode a model back."""

    def __init__(self, cnf: CNF, decoder: Callable[[set], str], name: str):
        self.cnf = cnf
        self._decoder = decoder
        self.name = name

    def decode(self, model: Sequence[int]) -> str:
        true_vars = {lit for lit in model if lit > 0}
        return self._decoder(true_vars)


# -- propositional building blocks ---------------------------------------
def at_least_one(lits: Sequence[int]) -> List[List[int]]:
    return [list(lits)]


def at_most_one(lits: Sequence[int]) -> List[List[int]]:
    """Pairwise at-most-one: no two literals simultaneously true."""
    clauses = []
    for i in range(len(lits)):
        for j in range(i + 1, len(lits)):
            clauses.append([-lits[i], -lits[j]])
    return clauses


def exactly_one(lits: Sequence[int]) -> List[List[int]]:
    return at_least_one(lits) + at_most_one(lits)


# -- N-Queens ------------------------------------------------------------
def encode_queens(n: int) -> Encoding:
    if n < 1:
        raise ValueError("N-Queens needs N >= 1")
    cnf = CNF(n * n)

    def var(r: int, c: int) -> int:
        return r * n + c + 1

    for r in range(n):  # exactly one queen per row
        cnf.extend(exactly_one([var(r, c) for c in range(n)]))
    for c in range(n):  # at most one per column
        cnf.extend(at_most_one([var(r, c) for r in range(n)]))
    # diagonals (both directions), at most one each
    for d in range(-(n - 1), n):
        diag = [var(r, r - d) for r in range(n) if 0 <= r - d < n]
        cnf.extend(at_most_one(diag))
    for s in range(2 * n - 1):
        anti = [var(r, s - r) for r in range(n) if 0 <= s - r < n]
        cnf.extend(at_most_one(anti))

    def decode(true_vars: set) -> str:
        rows = []
        for r in range(n):
            cells = ["Q" if var(r, c) in true_vars else "." for c in range(n)]
            rows.append(" ".join(cells))
        return "\n".join(rows)

    return Encoding(cnf, decode, f"queens-{n}")


# -- graph coloring ------------------------------------------------------
def encode_coloring(n_vertices: int, edges: Sequence[Tuple[int, int]], k: int) -> Encoding:
    if n_vertices < 1 or k < 1:
        raise ValueError("need n_vertices >= 1 and k >= 1")
    cnf = CNF(n_vertices * k)

    def var(v: int, color: int) -> int:
        return v * k + color + 1  # v in 0..n-1, color in 0..k-1

    for v in range(n_vertices):
        cnf.extend(exactly_one([var(v, col) for col in range(k)]))
    for (u, w) in edges:
        if not (0 <= u < n_vertices and 0 <= w < n_vertices):
            raise ValueError(f"edge ({u},{w}) out of range")
        for col in range(k):
            cnf.add_clause([-var(u, col), -var(w, col)])

    def decode(true_vars: set) -> str:
        out = []
        for v in range(n_vertices):
            color = next((col for col in range(k) if var(v, col) in true_vars), None)
            out.append(f"vertex {v}: color {color}")
        return "\n".join(out)

    return Encoding(cnf, decode, f"color-{n_vertices}v-{k}c")


# -- Sudoku --------------------------------------------------------------
def encode_sudoku(givens: str) -> Encoding:
    """``givens`` is 81 cells row-major; '.', '0' or ' ' mean blank, '1'-'9' fixed."""
    grid = _parse_sudoku(givens)
    cnf = CNF(9 * 9 * 9)

    def var(r: int, c: int, d: int) -> int:  # r,c in 0..8, d in 1..9
        return r * 81 + c * 9 + (d - 1) + 1

    for r in range(9):
        for c in range(9):
            cnf.extend(exactly_one([var(r, c, d) for d in range(1, 10)]))
    for d in range(1, 10):
        for r in range(9):  # each digit exactly once per row
            cnf.extend(exactly_one([var(r, c, d) for c in range(9)]))
        for c in range(9):  # per column
            cnf.extend(exactly_one([var(r, c, d) for r in range(9)]))
        for br in range(3):  # per 3x3 box
            for bc in range(3):
                cells = [var(br * 3 + i, bc * 3 + j, d) for i in range(3) for j in range(3)]
                cnf.extend(exactly_one(cells))
    for r in range(9):
        for c in range(9):
            if grid[r][c]:
                cnf.add_clause([var(r, c, grid[r][c])])

    def decode(true_vars: set) -> str:
        out = []
        for r in range(9):
            if r in (3, 6):
                out.append("------+-------+------")
            row = []
            for c in range(9):
                if c in (3, 6):
                    row.append("|")
                d = next((d for d in range(1, 10) if var(r, c, d) in true_vars), 0)
                row.append(str(d) if d else ".")
            out.append(" ".join(row))
        return "\n".join(out)

    return Encoding(cnf, decode, "sudoku")


def _parse_sudoku(text: str) -> List[List[int]]:
    cleaned = [ch for ch in text if ch in "0123456789." or ch == " "]
    flat = []
    for ch in cleaned:
        if ch in ". ":
            flat.append(0)
        else:
            flat.append(int(ch))
    if len(flat) != 81:
        raise ValueError(f"sudoku needs exactly 81 cells, got {len(flat)}")
    return [flat[i * 9:(i + 1) * 9] for i in range(9)]


# -- pigeonhole (guaranteed UNSAT for pigeons = holes + 1) ---------------
def encode_pigeonhole(holes: int, pigeons: Optional[int] = None) -> Encoding:
    if holes < 1:
        raise ValueError("need holes >= 1")
    if pigeons is None:
        pigeons = holes + 1
    cnf = CNF(pigeons * holes)

    def var(p: int, h: int) -> int:  # p in 0..pigeons-1, h in 0..holes-1
        return p * holes + h + 1

    for p in range(pigeons):  # every pigeon in some hole
        cnf.add_clause([var(p, h) for h in range(holes)])
    for h in range(holes):  # no two pigeons share a hole
        cnf.extend(at_most_one([var(p, h) for p in range(pigeons)]))

    def decode(true_vars: set) -> str:
        out = []
        for p in range(pigeons):
            h = next((h for h in range(holes) if var(p, h) in true_vars), None)
            out.append(f"pigeon {p} -> hole {h}")
        return "\n".join(out)

    return Encoding(cnf, decode, f"php-{pigeons}p-{holes}h")


def parse_graph(text: str) -> Tuple[int, List[Tuple[int, int]]]:
    """Parse a tiny graph format: first non-comment line ``<n_vertices>``, then
    one ``u v`` edge per line (0-indexed)."""
    n = None
    edges = []
    for raw in text.splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line:
            continue
        parts = line.split()
        if n is None:
            n = int(parts[0])
            if len(parts) > 1:  # allow "n m" header; ignore m
                continue
            continue
        edges.append((int(parts[0]), int(parts[1])))
    if n is None:
        raise ValueError("graph file: missing vertex count on first line")
    return n, edges
