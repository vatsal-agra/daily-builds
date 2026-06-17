"""Conflux command-line interface."""
from __future__ import annotations

import argparse
import sys
import time

from .cnf import CNF, read_dimacs_file
from .solver import Solver, SAT, UNSAT, UNKNOWN
from .proof import verify_unsat
from . import encoders as E
from . import rand3sat
from .trace import ExplainTracer
from .viz import write_html


def _solve_cnf(cnf: CNF, proof: bool = False, max_conflicts=None):
    s = Solver(num_vars=cnf.num_vars, record_proof=proof)
    for cl in cnf.clauses:
        if not s.add_clause(cl):
            break
    t = time.time()
    res = s.solve(max_conflicts=max_conflicts)
    dt = time.time() - t
    return res, s, dt


def _print_stats(s, dt):
    st = s.stats
    print(f"c time {dt*1000:.1f} ms | decisions {st.decisions} | "
          f"propagations {st.propagations} | conflicts {st.conflicts} | "
          f"learned {st.learned} | restarts {st.restarts} | "
          f"max-level {st.max_decision_level}", file=sys.stderr)


# ---- subcommands ---------------------------------------------------------
def cmd_solve(args):
    cnf = read_dimacs_file(args.file)
    res, s, dt = _solve_cnf(cnf, proof=(args.proof or args.check))
    _print_stats(s, dt)
    if res == SAT:
        print("s SATISFIABLE")
        model = s.model()
        if args.check:
            ok = cnf.is_satisfied_by(model)
            print(f"c model independently verified: {ok}", file=sys.stderr)
            if not ok:
                return 1
        lits = [v if model[v] else -v for v in range(1, cnf.num_vars + 1)]
        # print v-lines
        line = "v"
        for l in lits:
            line += f" {l}"
        print(line + " 0")
    elif res == UNSAT:
        print("s UNSATISFIABLE")
        if args.check or args.proof:
            ok, msg = verify_unsat(cnf.num_vars, cnf.clauses, s.proof)
            print(f"c proof: {msg}", file=sys.stderr)
            if not ok:
                return 1
    else:
        print("s UNKNOWN")
    return 0


def cmd_sudoku(args):
    text = args.puzzle
    if args.file:
        with open(args.file) as f:
            text = f.read()
    n = args.size
    grid_in = E.parse_sudoku(text, n)
    cnf, meta = E.encode_sudoku(grid_in, n)
    res, s, dt = _solve_cnf(cnf)
    _print_stats(s, dt)
    if res != SAT:
        print("s UNSATISFIABLE — this sudoku has no solution")
        return 1
    grid = E.decode_sudoku(s.model(), meta)
    ok, msg = E.validate_sudoku(grid, grid_in, n)
    print(_fmt_sudoku(grid, n))
    print(f"c {msg}", file=sys.stderr)
    return 0 if ok else 1


def _fmt_sudoku(grid, n):
    import math
    box = int(round(math.sqrt(n)))
    width = len(str(n))
    rows = []
    for r in range(n):
        if r % box == 0 and r != 0:
            rows.append("")
        cells = []
        for c in range(n):
            sep = "  " if (c % box == 0 and c != 0) else " "
            cells.append((sep if c else "") + str(grid[r][c]).rjust(width))
        rows.append("".join(cells))
    return "\n".join(rows)


def cmd_queens(args):
    n = args.n
    cnf, meta = E.encode_nqueens(n)
    res, s, dt = _solve_cnf(cnf, proof=True)
    _print_stats(s, dt)
    if res != SAT:
        ok, msg = verify_unsat(cnf.num_vars, cnf.clauses, s.proof)
        print(f"s UNSATISFIABLE — no {n}-queens placement (proof verified: {ok})")
        return 0
    pos = E.decode_nqueens(s.model(), meta)
    ok, msg = E.validate_nqueens(pos, n)
    for r in range(n):
        print("".join(" Q" if pos[r] == c else " ." for c in range(n)))
    print(f"c columns per row: {pos}", file=sys.stderr)
    print(f"c {msg}", file=sys.stderr)
    return 0 if ok else 1


def _parse_edges(s):
    edges = []
    for part in s.split(","):
        part = part.strip()
        if not part:
            continue
        a, b = part.replace("-", " ").split()
        edges.append((int(a), int(b)))
    return edges


BUILTIN_GRAPHS = {
    "petersen": (10, [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0), (0, 5), (1, 6),
                      (2, 7), (3, 8), (4, 9), (5, 7), (7, 9), (9, 6), (6, 8), (8, 5)]),
    "k4": (4, [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]),
    "wheel6": (7, [(0, 1), (1, 2), (2, 3), (3, 4), (4, 5), (5, 1),
                   (6, 1), (6, 2), (6, 3), (6, 4), (6, 5)]),
}


def cmd_color(args):
    if args.graph in BUILTIN_GRAPHS:
        V, edges = BUILTIN_GRAPHS[args.graph]
    else:
        V = args.vertices
        if V <= 0:
            raise ValueError(
                f"unknown graph {args.graph!r}; use a builtin "
                f"({', '.join(BUILTIN_GRAPHS)}) or pass --vertices N "
                f"[--edges \"0-1,1-2\"]")
        edges = _parse_edges(args.edges or "")
    cnf, meta = E.encode_coloring(V, edges, args.colors)
    res, s, dt = _solve_cnf(cnf, proof=True)
    _print_stats(s, dt)
    if res != SAT:
        ok, _ = verify_unsat(cnf.num_vars, cnf.clauses, s.proof)
        print(f"s UNSATISFIABLE — graph is not {args.colors}-colorable "
              f"(proof verified: {ok})")
        return 0
    colors = E.decode_coloring(s.model(), meta)
    ok, msg = E.validate_coloring(colors, meta)
    for v in range(V):
        print(f"  vertex {v}: color {colors[v]}")
    print(f"c {msg}", file=sys.stderr)
    return 0 if ok else 1


def cmd_php(args):
    cnf, meta = E.encode_pigeonhole(args.pigeons, args.holes)
    res, s, dt = _solve_cnf(cnf, proof=True)
    _print_stats(s, dt)
    if res == UNSAT:
        ok, msg = verify_unsat(cnf.num_vars, cnf.clauses, s.proof)
        print(f"s UNSATISFIABLE — {args.pigeons} pigeons can't fit in "
              f"{args.holes} holes")
        print(f"c {msg}", file=sys.stderr)
        return 0 if ok else 1
    print("s SATISFIABLE")
    return 0


def cmd_gen(args):
    import random
    rng = random.Random(args.seed)
    m = round(args.ratio * args.vars)
    cnf = rand3sat.random_ksat(args.vars, m, args.k, rng)
    sys.stdout.write(cnf.to_dimacs())
    return 0


def cmd_phase(args):
    res = rand3sat.phase_transition(
        num_vars=args.vars, k=args.k, alpha_min=args.min, alpha_max=args.max,
        steps=args.steps, samples=args.samples, seed=args.seed)
    if args.json:
        import json
        print(json.dumps(res, indent=2))
    else:
        print(rand3sat.render_sweep_ascii(res))
    return 0


def cmd_explain(args):
    cnf = read_dimacs_file(args.file)
    s = Solver(num_vars=cnf.num_vars)
    tr = ExplainTracer(target_conflict=args.conflict)
    s.tracer = tr
    for cl in cnf.clauses:
        if not s.add_clause(cl):
            break
    s.solve(max_conflicts=args.max_conflicts)
    print(tr.render())
    return 0


def cmd_viz(args):
    path = write_html(args.out)
    print(f"wrote visualizer to {path}")
    return 0


def cmd_demo(args):
    print("== Conflux demo ==\n")
    print("[1] Sudoku (the classic):")
    g = E.parse_sudoku(
        "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79")
    cnf, meta = E.encode_sudoku(g)
    res, s, dt = _solve_cnf(cnf)
    grid = E.decode_sudoku(s.model(), meta)
    print(_fmt_sudoku(grid, 9))
    print(f"  -> {E.validate_sudoku(grid, g)[1]} in {dt*1000:.0f} ms\n")

    print("[2] Pigeonhole PHP(6,5) — provably UNSAT:")
    cnf, meta = E.encode_pigeonhole(6, 5)
    res, s, dt = _solve_cnf(cnf, proof=True)
    ok, msg = verify_unsat(cnf.num_vars, cnf.clauses, s.proof)
    print(f"  -> {res}, {msg}, {s.stats.conflicts} conflicts\n")

    print("[3] Phase transition (random 3-SAT, n=40):")
    r = rand3sat.phase_transition(num_vars=40, steps=16, samples=20, seed=1)
    print(rand3sat.render_sweep_ascii(r))
    return 0


def build_parser():
    p = argparse.ArgumentParser(
        prog="conflux", description="Conflux — a from-scratch CDCL SAT solver.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("solve", help="solve a DIMACS CNF file")
    sp.add_argument("file")
    sp.add_argument("--proof", action="store_true", help="record a DRAT proof")
    sp.add_argument("--check", action="store_true",
                    help="verify the model (SAT) or the proof (UNSAT)")
    sp.set_defaults(func=cmd_solve)

    sp = sub.add_parser("sudoku", help="solve a sudoku")
    sp.add_argument("puzzle", nargs="?", default="", help="81 cells, . = blank")
    sp.add_argument("--file", help="read puzzle from a file")
    sp.add_argument("--size", type=int, default=9)
    sp.set_defaults(func=cmd_sudoku)

    sp = sub.add_parser("queens", help="solve the N-queens problem")
    sp.add_argument("n", type=int)
    sp.set_defaults(func=cmd_queens)

    sp = sub.add_parser("color", help="graph k-coloring")
    sp.add_argument("graph", help="builtin name (petersen/k4/wheel6) or 'custom'")
    sp.add_argument("colors", type=int)
    sp.add_argument("--vertices", type=int, default=0)
    sp.add_argument("--edges", help='e.g. "0-1,1-2,2-0"')
    sp.set_defaults(func=cmd_color)

    sp = sub.add_parser("php", help="pigeonhole PHP(pigeons, holes)")
    sp.add_argument("pigeons", type=int)
    sp.add_argument("holes", type=int)
    sp.set_defaults(func=cmd_php)

    sp = sub.add_parser("gen", help="generate a random k-SAT DIMACS file")
    sp.add_argument("--vars", type=int, default=50)
    sp.add_argument("--ratio", type=float, default=4.26)
    sp.add_argument("--k", type=int, default=3)
    sp.add_argument("--seed", type=int, default=0)
    sp.set_defaults(func=cmd_gen)

    sp = sub.add_parser("phase", help="random 3-SAT phase-transition sweep")
    sp.add_argument("--vars", type=int, default=60)
    sp.add_argument("--k", type=int, default=3)
    sp.add_argument("--min", type=float, default=2.0)
    sp.add_argument("--max", type=float, default=7.0)
    sp.add_argument("--steps", type=int, default=26)
    sp.add_argument("--samples", type=int, default=40)
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--json", action="store_true")
    sp.set_defaults(func=cmd_phase)

    sp = sub.add_parser("explain", help="ASCII implication-graph of a conflict")
    sp.add_argument("file")
    sp.add_argument("--conflict", type=int, default=1, help="which conflict (1-based)")
    sp.add_argument("--max-conflicts", type=int, default=100000)
    sp.set_defaults(func=cmd_explain)

    sp = sub.add_parser("viz", help="write the single-file HTML visualizer")
    sp.add_argument("out", nargs="?", default="conflux.html")
    sp.set_defaults(func=cmd_viz)

    sp = sub.add_parser("demo", help="run a short feature tour")
    sp.set_defaults(func=cmd_demo)
    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        return args.func(args) or 0
    except (ValueError, FileNotFoundError, IsADirectoryError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
