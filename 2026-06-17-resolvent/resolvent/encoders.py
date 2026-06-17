"""Compile classic combinatorial problems to CNF, and decode SAT models back
into human-readable solutions. This turns the generic SAT solver into a Sudoku
solver, a graph k-colorer, an N-Queens placer, and a pigeonhole refuter.
"""
from __future__ import annotations

from typing import List, Tuple, Dict, Optional
from .cnf import CNF
from .solver import Solver


# --------------------------------------------------------------------------
# Small CNF helpers
# --------------------------------------------------------------------------
def at_least_one(f: CNF, lits: List[int]) -> None:
    f.add_clause(list(lits))


def at_most_one(f: CNF, lits: List[int]) -> None:
    """Pairwise (naive) at-most-one encoding."""
    for i in range(len(lits)):
        for j in range(i + 1, len(lits)):
            f.add_clause([-lits[i], -lits[j]])


def exactly_one(f: CNF, lits: List[int]) -> None:
    at_least_one(f, lits)
    at_most_one(f, lits)


# --------------------------------------------------------------------------
# Sudoku (generalised N×N where N is a perfect square; default 9)
# --------------------------------------------------------------------------
DEFAULT_SUDOKU = (
    "53..7...."
    "6..195..."
    ".98....6."
    "8...6...3"
    "4..8.3..1"
    "7...2...6"
    ".6....28."
    "...419..5"
    "....8..79"
)


def _sudoku_var(n: int, r: int, c: int, d: int) -> int:
    return r * n * n + c * n + d  # d in 1..n, 1-based overall


def encode_sudoku(grid: str, n: int = 9) -> Tuple[CNF, Dict]:
    box = int(round(n ** 0.5))
    if box * box != n:
        raise ValueError(f"sudoku size {n} is not a perfect square")
    cells = [c for c in grid if c in "0123456789."]
    if len(cells) != n * n:
        raise ValueError(f"expected {n*n} cells, got {len(cells)}")
    f = CNF(n * n * n)
    V = lambda r, c, d: _sudoku_var(n, r, c, d)

    # Each cell holds exactly one digit.
    for r in range(n):
        for c in range(n):
            exactly_one(f, [V(r, c, d) for d in range(1, n + 1)])
    # Each digit appears exactly once per row, column, and box.
    for d in range(1, n + 1):
        for r in range(n):
            exactly_one(f, [V(r, c, d) for c in range(n)])
        for c in range(n):
            exactly_one(f, [V(r, c, d) for r in range(n)])
        for br in range(0, n, box):
            for bc in range(0, n, box):
                cell = [V(br + i, bc + j, d) for i in range(box) for j in range(box)]
                exactly_one(f, cell)
    # Givens.
    for idx, ch in enumerate(cells):
        if ch not in "0.":
            r, c = divmod(idx, n)
            f.add_clause([V(r, c, int(ch))])
    return f, {"n": n, "box": box, "grid": cells}


def decode_sudoku(model: Dict[int, bool], meta: Dict) -> List[List[int]]:
    n = meta["n"]
    out = [[0] * n for _ in range(n)]
    for r in range(n):
        for c in range(n):
            for d in range(1, n + 1):
                if model[_sudoku_var(n, r, c, d)]:
                    out[r][c] = d
                    break
    return out


def format_sudoku(grid: List[List[int]]) -> str:
    n = len(grid)
    box = int(round(n ** 0.5))
    lines = []
    for r in range(n):
        if r % box == 0 and r != 0:
            lines.append("+".join(["-" * (box * 2 + 1)] * box))
        row = []
        for c in range(n):
            if c % box == 0 and c != 0:
                row.append("|")
            row.append(str(grid[r][c]) if grid[r][c] else ".")
        lines.append(" " + " ".join(row))
    return "\n".join(lines)


def is_valid_sudoku(grid: List[List[int]]) -> bool:
    n = len(grid)
    box = int(round(n ** 0.5))
    full = set(range(1, n + 1))
    for r in range(n):
        if set(grid[r]) != full:
            return False
    for c in range(n):
        if set(grid[r][c] for r in range(n)) != full:
            return False
    for br in range(0, n, box):
        for bc in range(0, n, box):
            vals = [grid[br + i][bc + j] for i in range(box) for j in range(box)]
            if set(vals) != full:
                return False
    return True


# --------------------------------------------------------------------------
# Graph k-coloring
# --------------------------------------------------------------------------
NAMED_GRAPHS = {
    # name: (num_vertices, edges, suggested chromatic number for the demo)
    "petersen": (10, [
        (0, 1), (1, 2), (2, 3), (3, 4), (4, 0),       # outer 5-cycle
        (5, 7), (7, 9), (9, 6), (6, 8), (8, 5),       # inner pentagram
        (0, 5), (1, 6), (2, 7), (3, 8), (4, 9),       # spokes
    ], 3),
    "k4": (4, [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)], 4),
    "c5": (5, [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0)], 3),
    "wheel6": (6, [(0, 1), (0, 2), (0, 3), (0, 4), (0, 5),
                   (1, 2), (2, 3), (3, 4), (4, 5), (5, 1)], 4),
}


def _color_var(v: int, color: int, k: int) -> int:
    return v * k + color + 1  # color in 0..k-1


def encode_coloring(num_vertices: int, edges: List[Tuple[int, int]], k: int):
    if k < 1:
        raise ValueError("graph coloring needs at least 1 color")
    f = CNF(num_vertices * k)
    for v in range(num_vertices):
        exactly_one(f, [_color_var(v, c, k) for c in range(k)])
    for (a, b) in edges:
        for c in range(k):
            f.add_clause([-_color_var(a, c, k), -_color_var(b, c, k)])
    return f, {"n": num_vertices, "k": k, "edges": edges}


def decode_coloring(model: Dict[int, bool], meta: Dict) -> List[int]:
    n, k = meta["n"], meta["k"]
    colors = [-1] * n
    for v in range(n):
        for c in range(k):
            if model[_color_var(v, c, k)]:
                colors[v] = c
                break
    return colors


def is_valid_coloring(colors: List[int], meta: Dict) -> bool:
    if any(c < 0 for c in colors):
        return False
    return all(colors[a] != colors[b] for (a, b) in meta["edges"])


# --------------------------------------------------------------------------
# N-Queens
# --------------------------------------------------------------------------
def _queen_var(n: int, r: int, c: int) -> int:
    return r * n + c + 1


def encode_queens(n: int):
    if n < 1:
        raise ValueError("N-Queens needs N >= 1")
    f = CNF(n * n)
    Q = lambda r, c: _queen_var(n, r, c)
    for r in range(n):
        exactly_one(f, [Q(r, c) for c in range(n)])   # one queen per row
    for c in range(n):
        at_most_one(f, [Q(r, c) for r in range(n)])    # <=1 per column
    # Diagonals.
    for d in range(-(n - 1), n):
        diag = [Q(r, r - d) for r in range(n) if 0 <= r - d < n]
        at_most_one(f, diag)
    for d in range(2 * n - 1):
        anti = [Q(r, d - r) for r in range(n) if 0 <= d - r < n]
        at_most_one(f, anti)
    return f, {"n": n}


def decode_queens(model: Dict[int, bool], meta: Dict) -> List[int]:
    n = meta["n"]
    pos = [-1] * n
    for r in range(n):
        for c in range(n):
            if model[_queen_var(n, r, c)]:
                pos[r] = c
                break
    return pos


def format_queens(pos: List[int]) -> str:
    n = len(pos)
    rows = []
    for r in range(n):
        rows.append(" ".join("Q" if pos[r] == c else "." for c in range(n)))
    return "\n".join(rows)


def is_valid_queens(pos: List[int]) -> bool:
    n = len(pos)
    if any(c < 0 for c in pos):
        return False
    if len(set(pos)) != n:
        return False
    for r1 in range(n):
        for r2 in range(r1 + 1, n):
            if abs(pos[r1] - pos[r2]) == abs(r1 - r2):
                return False
    return True


# --------------------------------------------------------------------------
# Pigeonhole principle PHP(n+1 -> n): UNSAT
# --------------------------------------------------------------------------
def encode_php(holes: int):
    if holes < 1:
        raise ValueError("pigeonhole needs at least 1 hole")
    pigeons = holes + 1
    f = CNF()
    V = lambda p, h: p * holes + h + 1
    for p in range(pigeons):
        f.add_clause([V(p, h) for h in range(holes)])      # each pigeon placed
    for h in range(holes):
        for p1 in range(pigeons):
            for p2 in range(p1 + 1, pigeons):
                f.add_clause([-V(p1, h), -V(p2, h)])        # one per hole
    return f, {"holes": holes, "pigeons": pigeons}


# --------------------------------------------------------------------------
# Dispatch used by the CLI
# --------------------------------------------------------------------------
def build(problem: str, params: List[str]) -> Tuple[CNF, Dict]:
    if problem == "sudoku":
        grid = params[0] if params else DEFAULT_SUDOKU
        return encode_sudoku(grid)
    if problem == "coloring":
        name = params[0] if params else "petersen"
        if name not in NAMED_GRAPHS:
            raise ValueError(f"unknown graph {name!r}; choose from "
                             f"{', '.join(NAMED_GRAPHS)}")
        n, edges, default_k = NAMED_GRAPHS[name]
        k = int(params[1]) if len(params) > 1 else default_k
        return encode_coloring(n, edges, k)
    if problem == "queens":
        n = int(params[0]) if params else 8
        return encode_queens(n)
    if problem == "php":
        holes = int(params[0]) if params else 6
        return encode_php(holes)
    raise ValueError(f"unknown problem {problem!r}")


def solve_and_print(problem: str, params: List[str], file: Optional[str]) -> int:
    if file:
        with open(file) as fh:
            content = fh.read().strip()
        if problem == "sudoku":
            params = [content] + params
        else:
            params = content.split() + params
    f, meta = build(problem, params)
    print(f"c {problem}: {f.nvars} variables, {f.nclauses} clauses")
    s = Solver(f)
    sat = s.solve()
    if not sat:
        print("s UNSATISFIABLE")
        if problem == "php":
            print(f"c pigeonhole PHP({meta['pigeons']} pigeons -> {meta['holes']} "
                  "holes) has no solution — correctly proven UNSAT.")
        else:
            print("c no solution exists for these constraints.")
        return 20
    model = s.model()
    if not f.is_satisfied_by(model):
        print("c INTERNAL ERROR: model invalid", flush=True)
        return 3
    print("s SATISFIABLE")
    if problem == "sudoku":
        grid = decode_sudoku(model, meta)
        print(format_sudoku(grid))
        print(f"c valid completed Sudoku: {is_valid_sudoku(grid)}")
    elif problem == "coloring":
        colors = decode_coloring(model, meta)
        print("c coloring:", " ".join(f"v{v}={c}" for v, c in enumerate(colors)))
        print(f"c proper {meta['k']}-coloring: {is_valid_coloring(colors, meta)}")
    elif problem == "queens":
        pos = decode_queens(model, meta)
        print(format_queens(pos))
        print(f"c valid {meta['n']}-queens placement: {is_valid_queens(pos)}")
    elif problem == "php":
        print("c (unexpectedly satisfiable)")
    return 10
