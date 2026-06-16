"""A self-contained end-to-end demo touching every feature. Used by `resolvent
demo` and by the test suite as a smoke run."""
from __future__ import annotations

import os
import tempfile

from .cnf import CNF, parse_dimacs
from .solver import Solver
from .oracle import brute_force
from .generate import random_at_ratio
from . import encoders
from . import proof as proofmod
from . import viz as vizmod


def _hr(title: str) -> None:
    print("\n" + "=" * 64)
    print(f"  {title}")
    print("=" * 64)


def run_demo() -> int:
    _hr("1. DIMACS round-trip")
    cnf = CNF(3, [[1, 2, -3], [-1, 2], [3]])
    text = cnf.to_dimacs(comment="hand-built formula")
    cnf2 = parse_dimacs(text)
    print(text.strip())
    assert cnf2.nclauses == cnf.nclauses and cnf2.nvars == cnf.nvars
    print("round-trip OK")

    _hr("2. CDCL solve (SAT) with model verification")
    s = Solver(cnf)
    assert s.solve()
    model = s.model()
    assert cnf.is_satisfied_by(model)
    print("SATISFIABLE  model:", " ".join(str(x) for x in model))

    _hr("3. Differential fuzz vs brute-force oracle (300 random instances)")
    mism = 0
    for i in range(300):
        nv = (i % 9) + 4
        c = random_at_ratio(nv, 3.5 + (i % 200) / 100.0, seed=i * 131 + 7)
        exp, _ = brute_force(c)
        got = Solver(c, seed=i).solve()
        if exp != got:
            mism += 1
    print(f"300 instances, {mism} mismatches")
    assert mism == 0

    _hr("4. Heuristics actually fire (random 80-var at the phase transition)")
    c = random_at_ratio(80, 4.26, seed=42)
    s = Solver(c, seed=42)
    s.solve()
    print(f"decisions={s.stats.decisions} conflicts={s.stats.conflicts} "
          f"learned={s.stats.learned} restarts={s.stats.restarts}")
    assert s.stats.conflicts > 0 and s.stats.learned > 0

    _hr("5a. N-Queens (N=8) encode -> solve -> decode")
    enc = encoders.encode_queens(8)
    s = Solver(enc.cnf)
    assert s.solve()
    board = enc.decode(s.model())
    print(board)
    assert _valid_queens(board, 8)

    _hr("5b. Sudoku (a hard 17-clue style grid)")
    enc = encoders.encode_sudoku(_SUDOKU)
    s = Solver(enc.cnf)
    assert s.solve()
    grid = enc.decode(s.model())
    print(grid)

    _hr("5c. Pigeonhole PHP(5,4) is UNSAT (provably)")
    enc = encoders.encode_pigeonhole(4)
    s = Solver(enc.cnf, log_proof=True)
    assert not s.solve()
    print(f"UNSAT; DRUP proof has {len(s.proof)} steps")

    _hr("6. Implication-graph visualizer")
    c = random_at_ratio(40, 4.5, seed=5)
    s = Solver(c, record_conflict_graph=True, seed=5)
    s.solve()
    assert s.conflict_graph is not None
    html = vizmod.render_html(s.conflict_graph)
    path = os.path.join(tempfile.gettempdir(), "resolvent-demo-impl.html")
    with open(path, "w") as f:
        f.write(html)
    print(f"wrote {len(html)} bytes of self-contained HTML to {path}")

    _hr("7. DRUP UNSAT proof, independently checked")
    enc = encoders.encode_pigeonhole(4)
    s = Solver(enc.cnf, log_proof=True)
    assert not s.solve()
    ok = proofmod.check_proof(enc.cnf, s.proof)
    print(f"proof verified by independent RUP checker: {ok}")
    assert ok

    _hr("DONE — all features exercised successfully")
    return 0


def _valid_queens(board: str, n: int) -> bool:
    rows = [r.split() for r in board.splitlines()]
    qs = [(i, j) for i, row in enumerate(rows) for j, ch in enumerate(row) if ch == "Q"]
    if len(qs) != n:
        return False
    for a in range(len(qs)):
        for b in range(a + 1, len(qs)):
            (r1, c1), (r2, c2) = qs[a], qs[b]
            if r1 == r2 or c1 == c2 or abs(r1 - r2) == abs(c1 - c2):
                return False
    return True


_SUDOKU = (
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
