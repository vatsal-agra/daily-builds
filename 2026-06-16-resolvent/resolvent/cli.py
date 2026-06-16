"""Resolvent command-line interface."""
from __future__ import annotations

import argparse
import random
import sys
import time
from typing import List, Optional

from .cnf import CNF
from .solver import Solver, solve_cnf
from .proof import check_proof, count_models_dpll, brute_force_sat
from .puzzles import sudoku, nqueens, coloring, pigeonhole


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path) as f:
        return f.read()


def _print_stats(s: Solver, dt: float) -> None:
    st = s.stats
    print(f"c  time={dt*1000:.1f}ms  decisions={st.decisions}  conflicts={st.conflicts}"
          f"  propagations={st.propagations}  learned={st.learned}"
          f"  restarts={st.restarts}  maxlevel={st.max_decision_level}", file=sys.stderr)


# ---------------------------------------------------------------------- #
def cmd_solve(args) -> int:
    cnf = CNF.from_dimacs(_read(args.file))
    s = Solver(cnf, record_proof=args.proof is not None or args.check_proof)
    t = time.time()
    res = s.solve(max_conflicts=args.max_conflicts)
    dt = time.time() - t
    _print_stats(s, dt)
    if res is None:
        print("s INDETERMINATE")
        return 2
    if res is True:
        model = s.model()
        assert cnf.is_satisfied_by(model), "INTERNAL ERROR: model does not satisfy formula"
        print("s SATISFIABLE")
        lits = [str(v if model[v] else -v) for v in range(1, cnf.nvars + 1)]
        # DIMACS-style v lines
        line = "v"
        for tok in lits:
            if len(line) + len(tok) + 1 > 78:
                print(line)
                line = "v"
            line += " " + tok
        print(line + " 0")
        return 10
    # UNSAT
    print("s UNSATISFIABLE")
    if args.proof:
        with open(args.proof, "w") as f:
            for kind, clause in s.proof:
                f.write(("d " if kind == "d" else "") + " ".join(map(str, clause)) + " 0\n")
        print(f"c proof written to {args.proof}", file=sys.stderr)
    if args.check_proof:
        ok, msg = check_proof(cnf, s.proof)
        print(f"c proof-check: {msg}", file=sys.stderr)
        if not ok:
            return 1
    return 20


def cmd_sudoku(args) -> int:
    grid = sudoku.parse_grid(_read(args.file))
    puz = sudoku.Sudoku(grid)
    print(f"c sudoku {puz.size}x{puz.size}: {puz.model.cnf.nvars} vars, "
          f"{len(puz.model.cnf.clauses)} clauses", file=sys.stderr)
    t = time.time()
    sol = puz.solve()
    dt = time.time() - t
    print(f"c solved in {dt*1000:.1f}ms", file=sys.stderr)
    if sol is None:
        print("UNSATISFIABLE — no valid completion")
        return 20
    if not sudoku.is_valid_solution(sol):
        print("INTERNAL ERROR: invalid solution produced", file=sys.stderr)
        return 1
    print(sudoku.render(sol))
    return 10


def cmd_queens(args) -> int:
    puz = nqueens.NQueens(args.n)
    t = time.time()
    cols = puz.solve()
    dt = time.time() - t
    print(f"c {args.n}-queens in {dt*1000:.1f}ms", file=sys.stderr)
    if cols is None:
        print("UNSATISFIABLE")
        return 20
    if not nqueens.is_valid(cols):
        print("INTERNAL ERROR: invalid queens placement", file=sys.stderr)
        return 1
    print(nqueens.render(cols))
    return 10


def cmd_color(args) -> int:
    n, edges = coloring.parse_graph(_read(args.file))
    puz = coloring.Coloring(n, edges, args.k)
    t = time.time()
    col = puz.solve()
    dt = time.time() - t
    print(f"c {n} vertices, {len(edges)} edges, k={args.k} in {dt*1000:.1f}ms",
          file=sys.stderr)
    if col is None:
        print(f"UNSATISFIABLE — graph is not {args.k}-colorable")
        return 20
    if not coloring.is_valid(col, edges, args.k):
        print("INTERNAL ERROR: invalid coloring", file=sys.stderr)
        return 1
    print("SATISFIABLE")
    for v in range(n):
        print(f"  vertex {v}: color {col[v]}")
    return 10


def cmd_php(args) -> int:
    puz = pigeonhole.Pigeonhole(args.pigeons, args.holes)
    record = args.check_proof
    s = Solver(puz.model.cnf, record_proof=record)
    t = time.time()
    res = s.solve()
    dt = time.time() - t
    _print_stats(s, dt)
    if res is True:
        placement = puz.decode(s.model())
        print(f"SATISFIABLE — PHP({args.pigeons},{args.holes}) is solvable")
        print("  " + ", ".join(f"pigeon {i}->hole {h}" for i, h in enumerate(placement)))
        return 10
    print(f"UNSATISFIABLE — PHP({args.pigeons},{args.holes}) has no solution")
    if record:
        ok, msg = check_proof(puz.model.cnf, s.proof)
        print(f"c proof-check: {msg}", file=sys.stderr)
        return 0 if ok else 1
    return 20


def cmd_gen(args) -> int:
    rng = random.Random(args.seed)
    n = args.vars
    m = args.clauses if args.clauses is not None else int(round(args.ratio * n))
    cnf = CNF(n)
    for _ in range(m):
        clause: List[int] = []
        chosen = rng.sample(range(1, n + 1), min(args.k, n))
        for v in chosen:
            clause.append(v if rng.random() < 0.5 else -v)
        cnf.add_clause(clause)
    out = cnf.to_dimacs(comment=f"random {args.k}-SAT  n={n} m={m} seed={args.seed}")
    if args.out:
        with open(args.out, "w") as f:
            f.write(out)
        print(f"c wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(out)
    return 0


def cmd_verify(args) -> int:
    cnf = CNF.from_dimacs(_read(args.file))
    if args.model:
        model = {}
        for tok in _read(args.model).split():
            val = int(tok)
            if val == 0:
                continue
            model[abs(val)] = val > 0
        ok = cnf.is_satisfied_by(model)
        if ok:
            print("VALID — model satisfies all clauses")
            return 0
        bad = cnf.first_unsatisfied(model)
        print(f"INVALID — clause not satisfied: {bad}")
        return 1
    if args.proof:
        proof = []
        for line in _read(args.proof).splitlines():
            line = line.strip()
            if not line:
                continue
            kind = "a"
            if line.startswith("d "):
                kind = "d"
                line = line[2:]
            clause = [int(t) for t in line.split() if int(t) != 0]
            proof.append((kind, clause))
        ok, msg = check_proof(cnf, proof)
        print(("VALID — " if ok else "INVALID — ") + msg)
        return 0 if ok else 1
    if args.count:
        if cnf.nvars > 26:
            print("refusing exact count for >26 variables (would be too slow)",
                  file=sys.stderr)
            return 2
        print(f"models: {count_models_dpll(cnf)}")
        return 0
    # default: solve and self-check
    res, model, _ = solve_cnf(cnf)
    if res is True:
        print("SATISFIABLE", "(model verified)" if cnf.is_satisfied_by(model) else "(BAD MODEL)")
        return 10
    print("UNSATISFIABLE")
    return 20


def cmd_viz(args) -> int:
    from . import viz
    names = None
    if args.puzzle == "php":
        m, n = args.a, args.b
        puz = pigeonhole.Pigeonhole(m, n)
        cnf, names = puz.model.cnf, puz.model.names
        title = f"Pigeonhole PHP({m},{n})"
    elif args.puzzle == "queens":
        puz = nqueens.NQueens(args.a)
        cnf, names = puz.model.cnf, puz.model.names
        title = f"{args.a}-Queens"
    elif args.puzzle == "color":
        n, edges = coloring.parse_graph(_read(args.file))
        puz = coloring.Coloring(n, edges, args.k)
        cnf, names = puz.model.cnf, puz.model.names
        title = f"{args.k}-coloring"
    else:  # dimacs file
        cnf = CNF.from_dimacs(_read(args.file))
        title = args.file
    html = viz.render_report(cnf, title=title, names=names)
    with open(args.out, "w") as f:
        f.write(html)
    print(f"c wrote {args.out}", file=sys.stderr)
    return 0


def cmd_demo(args) -> int:
    print("== Resolvent demo ==")
    print("\n[1] Solving a 9x9 Sudoku")
    grid = "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79"
    sol = sudoku.Sudoku(sudoku.parse_grid(grid)).solve()
    print(sudoku.render(sol))
    print("valid:", sudoku.is_valid_solution(sol))

    print("\n[2] 12-Queens")
    cols = nqueens.NQueens(12).solve()
    print(nqueens.render(cols))

    print("\n[3] Pigeonhole PHP(6,5) is UNSAT, proven by an independent checker")
    puz = pigeonhole.Pigeonhole(6, 5)
    s = Solver(puz.model.cnf, record_proof=True)
    res = s.solve()
    ok, msg = check_proof(puz.model.cnf, s.proof)
    print("UNSAT:", res is False, "|", msg)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="resolvent",
                                description="A from-scratch CDCL SAT solver and toolkit.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("solve", help="solve a DIMACS CNF file")
    sp.add_argument("file")
    sp.add_argument("--proof", help="write a DRAT-style UNSAT proof here")
    sp.add_argument("--check-proof", action="store_true",
                    help="independently verify the UNSAT proof")
    sp.add_argument("--max-conflicts", type=int, default=None)
    sp.set_defaults(func=cmd_solve)

    sp = sub.add_parser("sudoku", help="solve a Sudoku grid")
    sp.add_argument("file", help="grid file ('-' for stdin)")
    sp.set_defaults(func=cmd_sudoku)

    sp = sub.add_parser("queens", help="solve N-Queens")
    sp.add_argument("n", type=int)
    sp.set_defaults(func=cmd_queens)

    sp = sub.add_parser("color", help="K-color a graph")
    sp.add_argument("file", help="edge-list file ('-' for stdin)")
    sp.add_argument("-k", type=int, required=True, help="number of colors")
    sp.set_defaults(func=cmd_color)

    sp = sub.add_parser("php", help="pigeonhole principle PHP(m,n)")
    sp.add_argument("pigeons", type=int)
    sp.add_argument("holes", type=int)
    sp.add_argument("--check-proof", action="store_true")
    sp.set_defaults(func=cmd_php)

    sp = sub.add_parser("gen", help="generate a random k-SAT instance")
    sp.add_argument("--vars", type=int, default=50)
    sp.add_argument("--clauses", type=int, default=None)
    sp.add_argument("--ratio", type=float, default=4.26,
                    help="clause/var ratio (default near 3-SAT phase transition)")
    sp.add_argument("-k", type=int, default=3)
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--out", default=None)
    sp.set_defaults(func=cmd_gen)

    sp = sub.add_parser("verify", help="verify a model, a proof, or count models")
    sp.add_argument("file")
    sp.add_argument("--model", help="model file to check against the CNF")
    sp.add_argument("--proof", help="UNSAT proof file to check")
    sp.add_argument("--count", action="store_true", help="exact #SAT model count")
    sp.set_defaults(func=cmd_verify)

    sp = sub.add_parser("viz", help="generate an interactive HTML solver report")
    sp.add_argument("puzzle", choices=["php", "queens", "color", "dimacs"])
    sp.add_argument("--file", help="input file for color/dimacs")
    sp.add_argument("-a", type=int, default=6, help="first size param")
    sp.add_argument("-b", type=int, default=5, help="second size param")
    sp.add_argument("-k", type=int, default=3)
    sp.add_argument("--out", default="resolvent_report.html")
    sp.set_defaults(func=cmd_viz)

    sp = sub.add_parser("demo", help="run a quick end-to-end demo")
    sp.set_defaults(func=cmd_demo)
    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args)
    except FileNotFoundError as e:
        print(f"error: file not found: {e.filename}", file=sys.stderr)
        return 2
    except (ValueError, KeyboardInterrupt) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
