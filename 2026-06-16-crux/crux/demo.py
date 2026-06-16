"""`crux demo` — a guided tour that exercises every feature end-to-end."""

from __future__ import annotations

import time

from .cnf import CNF
from .solver import Solver
from .brute import brute_is_sat, brute_count
from .counter import model_count
from .proof import check_proof
from . import encoders as enc


def _h(title):
    print("\n" + "=" * 64)
    print(title)
    print("=" * 64)


def run_demo() -> int:
    ok = True

    _h("1. Core CDCL — a satisfiable formula, verified model + stats")
    c = CNF()
    for cl in ([1, 2, 3], [-1, -2], [-2, -3], [-1, 3], [2]):
        c.add_clause(cl)
    r = Solver(c).solve()
    print("model:", r.assignment(), "| verified:", c.is_satisfied_by(r.model))
    print("stats:", r.stats.as_dict())
    ok &= r.sat and c.is_satisfied_by(r.model)

    _h("2. Real Sudoku solved and decoded")
    grid = [[int(ch) for ch in row] for row in
            ("530070000 600195000 098000060 800060003 400803001 "
             "700020006 060000280 000419005 000080079").split()]
    cnf, meta = enc.sudoku_encode(grid)
    t = time.time()
    r = Solver(cnf).solve()
    print(enc.sudoku_format(enc.sudoku_decode(r.model, meta)))
    print("solved in %.3fs · %d vars %d clauses" % (
        time.time() - t, cnf.nvars, cnf.nclauses))
    ok &= r.sat and cnf.is_satisfied_by(r.model)

    _h("3. N-Queens (n=10) and graph 3-colouring of C5")
    cnf, meta = enc.nqueens_encode(10)
    r = Solver(cnf).solve()
    print("10-queens columns:", enc.nqueens_decode(r.model, meta))
    ok &= r.sat
    edges = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0)]
    cnf, meta = enc.graph_coloring_encode(5, edges, 3)
    r = Solver(cnf).solve()
    print("C5 3-colouring:", enc.graph_coloring_decode(r.model, meta))
    cnf2, _ = enc.graph_coloring_encode(5, edges, 2)
    print("C5 with 2 colours is UNSAT:", not Solver(cnf2).solve().sat)
    ok &= r.sat and not Solver(cnf2).solve().sat

    _h("4. Differential oracle — Crux vs brute force on 1000 random formulas")
    import random
    rng = random.Random(2024)
    mism = 0
    for _ in range(1000):
        nv = rng.randint(1, 8)
        cc = CNF()
        for _ in range(rng.randint(0, nv * 4)):
            k = rng.randint(1, min(3, nv))
            lits, used = [], set()
            while len(lits) < k:
                v = rng.randint(1, nv)
                if v in used:
                    continue
                used.add(v)
                lits.append(v if rng.random() < 0.5 else -v)
            cc.add_clause(lits)
        cc.nvars = nv
        cr = Solver(cc.copy()).solve()
        if cr.sat != brute_is_sat(cc):
            mism += 1
        elif cr.sat and not cc.is_satisfied_by(cr.model):
            mism += 1
    print("1000 trials, mismatches:", mism)
    ok &= (mism == 0)

    _h("5. Exact model counting (#SAT), cross-checked vs brute force")
    cc = CNF()
    for cl in ([1, 2], [-2, 3], [-1, 3]):
        cc.add_clause(cl)
    cc.nvars = 3
    mc, bc = model_count(cc), brute_count(cc)
    print("formula (x1∨x2)(¬x2∨x3)(¬x1∨x3):  #SAT =", mc, " brute =", bc)
    ok &= (mc == bc)

    _h("6. UNSAT certificate — independent DRUP/RUP proof check")
    for (m, n) in [(3, 2), (4, 3), (5, 4)]:
        cnf = enc.pigeonhole_encode(m, n)[0]
        r = Solver(cnf.copy(), record_proof=True).solve()
        good, info = check_proof(cnf, r.proof)
        print("pigeonhole %d→%d UNSAT, proof of %d clauses VALID: %s"
              % (m, n, info["checked"], good))
        ok &= (not r.sat) and good

    _h("7. Conflict-analysis visualizer")
    from .viz import build_visualizer
    html = build_visualizer(enc.pigeonhole_encode(5, 4)[0])
    path = "web/crux-viz.html"
    try:
        with open(path, "w", encoding="utf-8") as fh:
            fh.write(html)
        print("wrote interactive visualizer ->", path, "(%d bytes)" % len(html))
    except OSError as e:
        print("could not write visualizer:", e)

    print("\n" + ("ALL DEMO CHECKS PASSED ✔" if ok else "*** DEMO HAD FAILURES ***"))
    return 0 if ok else 1
