"""Command-line interface for Crux.

Subcommands:
    solve     solve a DIMACS file (or stdin); print SAT/UNSAT + model + stats
    check     verify a model (DIMACS + assignment) satisfies a formula
    gen       generate a random DIMACS instance
    encode    encode a built-in problem (sudoku/queens/coloring/pigeonhole) to DIMACS
    decode    solve an encoded problem and print the human-readable solution
    fuzz      differential test the engine against the brute-force oracle
    count     exact model count (#SAT) for small instances
    proof     solve, and if UNSAT emit + independently check a resolution proof
    viz       generate the interactive HTML conflict-analysis visualizer
    demo      run a guided tour of every feature
"""

from __future__ import annotations

import argparse
import random
import sys
from typing import List, Optional

from .cnf import CNF, parse_dimacs, parse_dimacs_file
from .solver import Solver
from . import encoders as enc


def _read_cnf(path: Optional[str]) -> CNF:
    if path in (None, "-"):
        return parse_dimacs(sys.stdin.read())
    return parse_dimacs_file(path)


def _print_stats(stats, prefix="c "):
    for k, v in stats.as_dict().items():
        print(f"{prefix}{k}: {v}")


# --------------------------------------------------------------------- solve
def cmd_solve(args) -> int:
    cnf = _read_cnf(args.file)
    sol = Solver(cnf, restart_base=args.restart, record_proof=False)
    r = sol.solve(max_conflicts=args.max_conflicts)
    _print_stats(r.stats)
    if r.sat is None:
        print("s UNKNOWN")
        print(f"c conflict budget ({args.max_conflicts}) exhausted")
        return 0
    if r.sat:
        print("s SATISFIABLE")
        lits = r.assignment()
        # DIMACS-style v-lines
        line = "v " + " ".join(str(x) for x in lits) + " 0"
        print(line)
        assert cnf.is_satisfied_by(r.model), "internal error: bad model!"
        print("c model verified: True")
    else:
        print("s UNSATISFIABLE")
    return 10 if r.sat else 20


# --------------------------------------------------------------------- check
def cmd_check(args) -> int:
    cnf = parse_dimacs_file(args.file)
    text = sys.stdin.read() if args.model in (None, "-") else open(args.model).read()
    lits = []
    for tok in text.replace("v", " ").split():
        try:
            x = int(tok)
        except ValueError:
            continue
        if x != 0:
            lits.append(x)
    ok = cnf.is_satisfied_by(lits)
    if ok:
        print("c model SATISFIES the formula")
        return 0
    bad = cnf.unsatisfied_clauses(lits)
    print(f"c model FAILS: {len(bad)} unsatisfied clause(s)")
    for c in bad[:10]:
        print("c   " + " ".join(map(str, c)))
    return 1


# ----------------------------------------------------------------------- gen
def cmd_gen(args) -> int:
    random.seed(args.seed)
    cnf = CNF()
    for _ in range(args.clauses):
        clause = []
        used = set()
        while len(clause) < args.width:
            v = random.randint(1, args.vars)
            if v in used:
                continue
            used.add(v)
            clause.append(v if random.random() < 0.5 else -v)
        cnf.add_clause(clause)
    cnf.nvars = max(cnf.nvars, args.vars)
    sys.stdout.write(cnf.to_dimacs())
    return 0


# -------------------------------------------------------------------- encode
def _build_problem(args):
    if args.problem == "sudoku":
        grid = _load_sudoku(args.input)
        return enc.sudoku_encode(grid), "sudoku"
    if args.problem == "queens":
        return enc.nqueens_encode(args.n), "queens"
    if args.problem == "coloring":
        n_nodes, edges = _load_graph(args.input)
        return enc.graph_coloring_encode(n_nodes, edges, args.k), "coloring"
    if args.problem == "pigeonhole":
        return enc.pigeonhole_encode(args.m, args.n), "pigeonhole"
    raise SystemExit(f"unknown problem {args.problem}")


def cmd_encode(args) -> int:
    (cnf, meta), _ = _build_problem(args)
    sys.stdout.write(cnf.to_dimacs())
    return 0


def cmd_decode(args) -> int:
    (cnf, meta), kind = _build_problem(args)
    r = Solver(cnf).solve()
    _print_stats(r.stats)
    if not r.sat:
        print("s UNSATISFIABLE")
        return 20
    print("s SATISFIABLE")
    if kind == "sudoku":
        sol = enc.sudoku_decode(r.model, meta)
        print(enc.sudoku_format(sol))
    elif kind == "queens":
        cols = enc.nqueens_decode(r.model, meta)
        print(enc.nqueens_format(cols))
        print("c columns:", cols)
    elif kind == "coloring":
        cols = enc.graph_coloring_decode(r.model, meta)
        print("c colouring:", cols)
    elif kind == "pigeonhole":
        holes = enc.pigeonhole_decode(r.model, meta)
        for i, h in enumerate(holes):
            print(f"c pigeon {i} -> hole {h}")
    assert cnf.is_satisfied_by(r.model)
    return 10


def _load_sudoku(path: Optional[str]) -> List[List[int]]:
    text = sys.stdin.read() if path in (None, "-") else open(path).read()
    rows = []
    for line in text.split():
        line = line.strip()
        if not line:
            continue
        rows.append([0 if ch in ".0" else int(ch) for ch in line])
    if not rows:
        raise SystemExit("no sudoku grid found on input")
    return rows


def _load_graph(path: Optional[str]):
    """Graph format: first line 'n_nodes', then 'a b' edges (0-indexed)."""
    text = sys.stdin.read() if path in (None, "-") else open(path).read()
    nums = text.split()
    it = iter(nums)
    n_nodes = int(next(it))
    edges = []
    rest = list(it)
    for i in range(0, len(rest) - 1, 2):
        edges.append((int(rest[i]), int(rest[i + 1])))
    return n_nodes, edges


# ---------------------------------------------------------------------- fuzz
def cmd_fuzz(args) -> int:
    from .brute import brute_is_sat
    random.seed(args.seed)
    mism = 0
    for t in range(args.trials):
        nv = random.randint(1, args.vars)
        nc = random.randint(1, nv * 4)
        cnf = CNF()
        for _ in range(nc):
            k = random.randint(1, min(3, nv))
            lits, used = [], set()
            while len(lits) < k:
                v = random.randint(1, nv)
                if v in used:
                    continue
                used.add(v)
                lits.append(v if random.random() < 0.5 else -v)
            cnf.add_clause(lits)
        cnf.nvars = nv
        r = Solver(cnf, restart_base=1 + (t % 100)).solve()
        b = brute_is_sat(cnf)
        if r.sat != b:
            mism += 1
            print(f"MISMATCH trial={t} crux={r.sat} brute={b}")
            print("  clauses:", [list(c) for c in cnf.clauses])
        elif r.sat and not cnf.is_satisfied_by(r.model):
            mism += 1
            print(f"BAD MODEL trial={t}")
    print(f"c fuzz: {args.trials} trials, {mism} mismatches")
    return 1 if mism else 0


# --------------------------------------------------------------------- count
def cmd_count(args) -> int:
    cnf = _read_cnf(args.file)
    from .counter import model_count
    n = model_count(cnf)
    print(f"c model count (#SAT): {n}")
    if args.verify:
        from .brute import brute_count
        bn = brute_count(cnf)
        print(f"c brute count: {bn}  match={'YES' if bn == n else 'NO'}")
        return 0 if bn == n else 1
    return 0


# --------------------------------------------------------------------- proof
def cmd_proof(args) -> int:
    cnf = _read_cnf(args.file)
    sol = Solver(cnf, record_proof=True)
    r = sol.solve()
    if r.sat:
        print("s SATISFIABLE (no UNSAT proof to check)")
        assert cnf.is_satisfied_by(r.model)
        return 10
    print("s UNSATISFIABLE")
    from .proof import check_proof
    ok, info = check_proof(cnf, r.proof)
    print(f"c proof steps: {info['steps']}, checked: {info['checked']}")
    print(f"c proof VALID: {ok}")
    return 0 if ok else 1


# ----------------------------------------------------------------------- viz
def cmd_viz(args) -> int:
    from .viz import build_visualizer
    if args.problem:
        ns = argparse.Namespace(problem=args.problem, input=args.input,
                                n=args.n, k=args.k, m=args.m)
        (cnf, _), _ = _build_problem(ns)
    elif args.file:
        cnf = _read_cnf(args.file)
    else:
        # a small instructive default that actually conflicts and learns
        cnf = enc.pigeonhole_encode(args.m or 4, args.n or 3)[0]
    html = build_visualizer(cnf, title=args.title)
    with open(args.out, "w", encoding="utf-8") as fh:
        fh.write(html)
    print(f"c wrote visualizer to {args.out} ({len(html)} bytes)")
    return 0


# ---------------------------------------------------------------------- demo
def cmd_demo(args) -> int:
    from .demo import run_demo
    return run_demo()


# --------------------------------------------------------------------- parser
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="crux", description="A CDCL SAT solver.")
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("solve", help="solve a DIMACS CNF")
    s.add_argument("file", nargs="?", help="DIMACS file (default stdin)")
    s.add_argument("--restart", type=int, default=100)
    s.add_argument("--max-conflicts", type=int, default=None,
                   dest="max_conflicts", help="budget; print UNKNOWN if exceeded")
    s.set_defaults(func=cmd_solve)

    c = sub.add_parser("check", help="verify a model against a DIMACS formula")
    c.add_argument("file")
    c.add_argument("model", nargs="?", help="assignment file (default stdin)")
    c.set_defaults(func=cmd_check)

    g = sub.add_parser("gen", help="generate a random DIMACS instance")
    g.add_argument("--vars", type=int, default=20)
    g.add_argument("--clauses", type=int, default=80)
    g.add_argument("--width", type=int, default=3)
    g.add_argument("--seed", type=int, default=0)
    g.set_defaults(func=cmd_gen)

    for name, fn in (("encode", cmd_encode), ("decode", cmd_decode)):
        e = sub.add_parser(name, help=f"{name} a built-in problem")
        e.add_argument("problem",
                       choices=["sudoku", "queens", "coloring", "pigeonhole"])
        e.add_argument("input", nargs="?", help="problem input file (default stdin)")
        e.add_argument("-n", type=int, default=8, help="board size / holes")
        e.add_argument("-k", type=int, default=3, help="number of colours")
        e.add_argument("-m", type=int, default=4, help="number of pigeons")
        e.set_defaults(func=fn)

    f = sub.add_parser("fuzz", help="differential test vs brute force")
    f.add_argument("--trials", type=int, default=2000)
    f.add_argument("--vars", type=int, default=7)
    f.add_argument("--seed", type=int, default=0)
    f.set_defaults(func=cmd_fuzz)

    ct = sub.add_parser("count", help="exact #SAT model count")
    ct.add_argument("file", nargs="?")
    ct.add_argument("--verify", action="store_true", help="cross-check vs brute")
    ct.set_defaults(func=cmd_count)

    pr = sub.add_parser("proof", help="solve + independently check UNSAT proof")
    pr.add_argument("file", nargs="?")
    pr.set_defaults(func=cmd_proof)

    vz = sub.add_parser("viz", help="generate the HTML conflict visualizer")
    vz.add_argument("--file", help="DIMACS input")
    vz.add_argument("--problem",
                    choices=["sudoku", "queens", "coloring", "pigeonhole"])
    vz.add_argument("--input")
    vz.add_argument("-n", type=int, default=3)
    vz.add_argument("-k", type=int, default=3)
    vz.add_argument("-m", type=int, default=4)
    vz.add_argument("--out", default="web/crux-viz.html")
    vz.add_argument("--title", default="Crux — CDCL conflict analysis")
    vz.set_defaults(func=cmd_viz)

    d = sub.add_parser("demo", help="guided tour of every feature")
    d.set_defaults(func=cmd_demo)

    return p


def main(argv: Optional[List[str]] = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)
