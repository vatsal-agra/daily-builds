"""A guided tour exercising every feature, used by `python3 -m resolvent demo`
and by the verification script. Returns 0 on success, non-zero if any built-in
sanity check fails."""
from __future__ import annotations

import time

from .cnf import CNF
from .solver import Solver
from . import encoders
from .proof import check_unsat_proof
from .bruteforce import truth_table_sat


def _hdr(title: str):
    print("\n" + "=" * 64)
    print(f"  {title}")
    print("=" * 64)


def run() -> int:
    failures = 0

    _hdr("1. Solve a small SAT instance (model self-verified)")
    f = CNF.parse_dimacs("p cnf 4 5\n1 -2 3 0\n-1 2 0\n-3 4 0\n2 3 -4 0\n-1 -2 -3 0\n")
    s = Solver(f)
    sat = s.solve()
    ok = sat and f.is_satisfied_by(s.model())
    print(f"  verdict: {'SAT' if sat else 'UNSAT'}; model valid: {ok}")
    failures += 0 if ok else 1

    _hdr("2. Solve a small UNSAT instance and check its proof independently")
    g = CNF()
    for cl in [[1, 2], [1, -2], [-1, 2], [-1, -2]]:
        g.add_clause(cl)
    s = Solver(g, record_proof=True)
    sat = s.solve()
    proof = s.get_proof()
    pok, msg = check_unsat_proof(g, proof)
    print(f"  verdict: {'SAT' if sat else 'UNSAT'}; proof check: {pok} ({msg})")
    failures += 0 if (not sat and pok) else 1

    _hdr("3. Sudoku — generic SAT solver as a Sudoku engine")
    sf, meta = encoders.encode_sudoku(encoders.DEFAULT_SUDOKU)
    s = Solver(sf)
    s.solve()
    grid = encoders.decode_sudoku(s.model(), meta)
    valid = encoders.is_valid_sudoku(grid)
    print(encoders.format_sudoku(grid))
    print(f"  valid completed Sudoku: {valid}  "
          f"({sf.nvars} vars, {sf.nclauses} clauses, {s.stats.conflicts} conflicts)")
    failures += 0 if valid else 1

    _hdr("4. N-Queens (N=12)")
    qf, qm = encoders.encode_queens(12)
    s = Solver(qf)
    s.solve()
    pos = encoders.decode_queens(s.model(), qm)
    qok = encoders.is_valid_queens(pos)
    print(encoders.format_queens(pos))
    print(f"  valid 12-queens placement: {qok}")
    failures += 0 if qok else 1

    _hdr("5. Graph coloring — Petersen graph needs 3 colors, not 2")
    cf3, cm3 = encoders.encode_coloring(*encoders.NAMED_GRAPHS["petersen"][:2], 3)
    s3 = Solver(cf3)
    sat3 = s3.solve()
    colors = encoders.decode_coloring(s3.model(), cm3) if sat3 else []
    cf2, _ = encoders.encode_coloring(*encoders.NAMED_GRAPHS["petersen"][:2], 2)
    sat2 = Solver(cf2).solve()
    print(f"  3-coloring: {'found' if sat3 else 'none'} "
          f"(proper: {encoders.is_valid_coloring(colors, cm3) if sat3 else 'n/a'})")
    print(f"  2-coloring: {'found' if sat2 else 'none (correctly UNSAT)'}")
    failures += 0 if (sat3 and not sat2) else 1

    _hdr("6. Pigeonhole PHP(n+1 -> n) — UNSAT with a checked proof")
    for n in (4, 5):
        pf, pm = encoders.encode_php(n)
        s = Solver(pf, record_proof=True)
        sat = s.solve()
        pok, _ = check_unsat_proof(pf, s.get_proof())
        print(f"  PHP({n+1}->{n}): {'SAT' if sat else 'UNSAT'}, "
              f"conflicts={s.stats.conflicts}, proof verified={pok}")
        failures += 0 if (not sat and pok) else 1

    _hdr("7. Differential fuzz vs an exhaustive oracle (400 random formulas)")
    import random
    rng = random.Random(2024)
    mism = 0
    for _ in range(400):
        nv = rng.randint(1, 9)
        nc = rng.randint(1, int(nv * 4.5) + 1)
        rf = CNF(nv)
        for _ in range(nc):
            k = rng.randint(1, min(3, nv))
            rf.add_clause([(v if rng.random() < 0.5 else -v)
                           for v in (rng.randint(1, nv) for _ in range(k))])
        sv = Solver(rf).solve()
        if sv != truth_table_sat(rf):
            mism += 1
    print(f"  mismatches with oracle: {mism} / 400")
    failures += 0 if mism == 0 else 1

    _hdr("Summary")
    if failures == 0:
        print("  ALL FEATURES OK ✔")
    else:
        print(f"  {failures} CHECK(S) FAILED")
    return 1 if failures else 0


if __name__ == "__main__":
    raise SystemExit(run())
