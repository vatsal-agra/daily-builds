"""Command-line interface for Backjump."""

from __future__ import annotations

import argparse
import random
import sys
import time
from typing import List, Optional

from .cnf import CNF, parse_dimacs
from .solver import Solver, SAT, UNSAT
from .proof import check_model, check_proof
from .encoders import Sudoku, NQueens, GraphColoring, Pigeonhole
from .brute import brute_is_sat
from .modelcount import count_models, all_models
from .viz import build_bundle, generate_html


# --------------------------------------------------------------------------
def _solve_and_report(cnf: CNF, args, what: str = "instance"):
    s = Solver(cnf, emit_proof=True, restart_base=getattr(args, "restart", 100))
    t0 = time.time()
    result = s.solve()
    dt = time.time() - t0
    print(f"{what}: {result}   ({cnf.num_vars} vars, {cnf.num_clauses} clauses, {dt*1000:.1f} ms)")
    print(f"  stats: {s.stats}")
    if result == SAT:
        ok = check_model(cnf.clauses, s.model())
        print(f"  model verified: {ok}")
        if getattr(args, "model", False):
            print("  v " + " ".join(str(l) for l in s.model()))
    elif result == UNSAT:
        ok, msg = check_proof(cnf.clauses, s.proof)
        print(f"  proof verified: {ok} ({len(s.proof)} steps) — {msg}")
    return s, result


def cmd_solve(args):
    text = _read_text(args.file)
    cnf = parse_dimacs(text)
    s, result = _solve_and_report(cnf, args, args.file)
    if args.viz:
        _write_viz(cnf, args.viz, f"DIMACS: {args.file}")
    return 0 if result in (SAT, UNSAT) else 2


def cmd_sudoku(args):
    sk = Sudoku(args.size)
    if args.file:
        text = _read_text(args.file)
        grid = sk.parse_grid(text, args.size)
    else:
        grid = sk.parse_grid(_DEFAULT_SUDOKU, 9)
    print("Puzzle:")
    print(sk.render(grid))
    cnf = sk.encode(grid)
    s, result = _solve_and_report(cnf, args, "sudoku")
    if result == SAT:
        sol = sk.decode(s.model())
        print("Solution:")
        print(sk.render(sol))
        ok = _validate_sudoku(sk, grid, sol)
        print(f"  solution is a valid completion: {ok}")
    else:
        print("  (no solution — puzzle is unsatisfiable)")
    if args.viz:
        _write_viz(cnf, args.viz, "Sudoku")
    return 0


def cmd_queens(args):
    nq = NQueens(args.n)
    cnf = nq.encode()
    s, result = _solve_and_report(cnf, args, f"{args.n}-queens")
    if result == SAT:
        cols = nq.decode(s.model())
        print(nq.render(cols))
        ok = all(cols[i] != cols[j] and abs(cols[i] - cols[j]) != abs(i - j)
                 for i in range(args.n) for j in range(i + 1, args.n)) and all(c >= 0 for c in cols)
        print(f"  no two queens attack: {ok}")
    if args.viz:
        _write_viz(cnf, args.viz, f"{args.n}-Queens")
    return 0


def cmd_color(args):
    v, edges = _parse_graph(args)
    gc = GraphColoring(v, edges, args.k)
    cnf = gc.encode()
    s, result = _solve_and_report(cnf, args, f"{args.k}-colouring")
    if result == SAT:
        cols = gc.decode(s.model())
        print("  colours: " + ", ".join(f"v{i}={c}" for i, c in enumerate(cols)))
        ok = all(cols[a] != cols[b] for a, b in edges)
        print(f"  proper colouring: {ok}")
    if args.viz:
        _write_viz(cnf, args.viz, f"{args.k}-colouring")
    return 0


def cmd_pigeon(args):
    ph = Pigeonhole(args.pigeons, args.holes)
    cnf = ph.encode()
    s, result = _solve_and_report(cnf, args, f"PHP({args.pigeons},{args.holes})")
    if args.viz:
        _write_viz(cnf, args.viz, f"Pigeonhole {args.pigeons}->{args.holes}")
    return 0


def cmd_gen(args):
    random.seed(args.seed)
    cnf = random_ksat(args.vars, args.clauses, args.k, random.Random(args.seed))
    text = cnf.to_dimacs()
    if args.out:
        _write_text(args.out, text)
        print(f"wrote {args.out} ({cnf.num_vars} vars, {cnf.num_clauses} clauses)")
    else:
        sys.stdout.write(text)
    return 0


def cmd_count(args):
    if args.file:
        text = _read_text(args.file)
        cnf = parse_dimacs(text)
    else:
        random.seed(args.seed)
        cnf = random_ksat(args.vars, args.clauses, args.k, random.Random(args.seed))
    if cnf.num_vars > 24:
        print("refusing to enumerate: too many variables (>24)")
        return 2
    t0 = time.time()
    models = []
    for m in all_models(cnf, limit=args.limit):
        models.append(m)
    dt = time.time() - t0
    print(f"#SAT = {len(models)}  ({cnf.num_vars} vars, {cnf.num_clauses} clauses, {dt*1000:.1f} ms)")
    if args.check and cnf.num_vars <= 20:
        from .brute import count_models as brute_count
        bc = brute_count(cnf.num_vars, cnf.clauses)
        status = "MATCH" if (args.limit is None and bc == len(models)) else f"brute={bc}"
        print(f"  brute-force cross-check: {status}")
    if args.show:
        for m in models[:args.show]:
            print("  " + " ".join(str(l) for l in m))
    return 0


def cmd_fuzz(args):
    rng = random.Random(args.seed)
    mism = nsat = nunsat = 0
    t0 = time.time()
    for i in range(args.trials):
        nv = rng.randint(1, args.vars)
        nc = rng.randint(0, int(nv * args.ratio))
        cnf = random_ksat(nv, nc, min(args.k, nv), rng)
        s = Solver(cnf, emit_proof=True)
        result = s.solve()
        truth = brute_is_sat(nv, cnf.clauses)
        if (result == SAT) != truth:
            mism += 1
            print(f"  MISMATCH solver={result} brute={truth}: {cnf.clauses}")
            if mism >= 5:
                break
            continue
        if result == SAT:
            nsat += 1
            if not check_model(cnf.clauses, s.model()):
                print(f"  BAD MODEL: {cnf.clauses}")
                mism += 1
        else:
            nunsat += 1
            ok, msg = check_proof(cnf.clauses, s.proof)
            if not ok:
                print(f"  BAD PROOF: {cnf.clauses} — {msg}")
                mism += 1
    dt = time.time() - t0
    print(f"fuzz: {args.trials} trials, {nsat} SAT, {nunsat} UNSAT, "
          f"{mism} mismatches  ({dt:.2f}s)")
    print("  every SAT model and every UNSAT proof was independently verified."
          if mism == 0 else "  *** failures detected ***")
    return 1 if mism else 0


def cmd_phase(args):
    """3-SAT phase-transition demo: satisfiability vs clause/variable ratio."""
    rng = random.Random(args.seed)
    n = args.vars
    print(f"3-SAT phase transition, n={n} variables, {args.samples} samples per ratio:")
    print(f"  {'ratio':>6}  {'sat%':>6}  {'avg conflicts':>14}")
    for step in range(args.steps + 1):
        ratio = args.lo + (args.hi - args.lo) * step / args.steps
        m = int(round(ratio * n))
        sat = 0
        conf = 0
        for _ in range(args.samples):
            cnf = random_ksat(n, m, 3, rng)
            s = Solver(cnf)
            if s.solve() == SAT:
                sat += 1
            conf += s.stats.conflicts
        bar = "#" * int(round(sat / args.samples * 30))
        print(f"  {ratio:6.2f}  {100*sat/args.samples:5.0f}%  {conf/args.samples:14.1f}  {bar}")
    print("  (the satisfiability cliff sits near ratio ~4.26 for random 3-SAT)")
    return 0


def cmd_viz(args):
    if args.kind == "dimacs":
        text = _read_text(args.file)
        cnf = parse_dimacs(text)
        title = f"DIMACS {args.file}"
    elif args.kind == "color":
        v, edges = _parse_graph(args)
        cnf = GraphColoring(v, edges, args.k).encode()
        title = f"{args.k}-colouring ({v} vertices)"
    elif args.kind == "pigeon":
        cnf = Pigeonhole(args.pigeons, args.holes).encode()
        title = f"Pigeonhole {args.pigeons}->{args.holes}"
    elif args.kind == "queens":
        cnf = NQueens(args.n).encode()
        title = f"{args.n}-Queens"
    else:
        random.seed(args.seed)
        cnf = random_ksat(args.vars, args.clauses, args.k, random.Random(args.seed))
        title = f"random {args.k}-SAT ({args.vars} vars, {args.clauses} clauses)"
    _write_viz(cnf, args.out, title)
    return 0


# --------------------------------------------------------------------------
def _read_text(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path) as f:
        return f.read()


def _write_text(path: str, text: str) -> None:
    with open(path, "w") as f:
        f.write(text)


def _write_viz(cnf: CNF, path: str, title: str):
    bundle = build_bundle(cnf, title)
    _write_text(path, generate_html(bundle))
    print(f"  wrote visualizer → {path}  "
          f"({bundle['result']}, {len(bundle['events'])} steps)")


def random_ksat(n: int, m: int, k: int, rng: random.Random) -> CNF:
    k = max(1, min(k, n))
    cnf = CNF(n)
    for _ in range(m):
        clause = set()
        while len(clause) < k:
            v = rng.randint(1, n)
            clause.add(v if rng.random() < 0.5 else -v)
        cnf.add_clause(list(clause))
    return cnf


def _parse_graph(args):
    if getattr(args, "cycle", None):
        v = args.cycle
        edges = [(i, (i + 1) % v) for i in range(v)]
        return v, edges
    if getattr(args, "complete", None):
        v = args.complete
        edges = [(i, j) for i in range(v) for j in range(i + 1, v)]
        return v, edges
    if getattr(args, "edges", None):
        edges = []
        maxv = 0
        for pair in args.edges:
            a, b = pair.split("-")
            a, b = int(a), int(b)
            edges.append((a, b))
            maxv = max(maxv, a, b)
        v = getattr(args, "vertices", None) or (maxv + 1)
        return v, edges
    # default: Petersen-like graph
    edges = [(0, 1), (1, 2), (2, 3), (3, 4), (4, 0),
             (0, 5), (1, 6), (2, 7), (3, 8), (4, 9),
             (5, 7), (7, 9), (9, 6), (6, 8), (8, 5)]
    return 10, edges


def _validate_sudoku(sk: Sudoku, givens, sol) -> bool:
    n = sk.n
    full = list(range(1, n + 1))
    for r in range(n):
        if sorted(sol[r]) != full:
            return False
    for c in range(n):
        if sorted(sol[r][c] for r in range(n)) != full:
            return False
    b = sk.box
    for br in range(b):
        for bc in range(b):
            box = [sol[br * b + i][bc * b + j] for i in range(b) for j in range(b)]
            if sorted(box) != full:
                return False
    for r in range(n):
        for c in range(n):
            if givens[r][c] != 0 and givens[r][c] != sol[r][c]:
                return False
    return True


_DEFAULT_SUDOKU = "53..7....6..195....98....6.8...6...34..8.3..17...2...6.6....28....419..5....8..79"


def cmd_demo(args):
    """A guided tour exercising every feature."""
    print("=" * 64)
    print("BACKJUMP — guided demo")
    print("=" * 64)

    print("\n[1] Solve a hard Sudoku (encode -> CDCL -> decode -> validate)")
    sk = Sudoku(9)
    grid = sk.parse_grid(_DEFAULT_SUDOKU, 9)
    cnf = sk.encode(grid)
    s = Solver(cnf)
    s.solve()
    sol = sk.decode(s.model())
    print(sk.render(sol))
    print("  valid:", _validate_sudoku(sk, grid, sol), "|", s.stats)

    print("\n[2] N-Queens for n = 8, 20, 30")
    for n in (8, 20, 30):
        nq = NQueens(n)
        c = nq.encode()
        s = Solver(c)
        t0 = time.time()
        r = s.solve()
        cols = nq.decode(s.model())
        ok = all(cols[i] != cols[j] and abs(cols[i] - cols[j]) != abs(i - j)
                 for i in range(n) for j in range(i + 1, n))
        print(f"  {n}-queens: {r} valid={ok} in {(time.time()-t0)*1000:.0f}ms  {s.stats}")

    print("\n[3] Pigeonhole PHP(p, p-1) is UNSAT — with a verified proof")
    for p in (5, 6, 7):
        ph = Pigeonhole(p, p - 1)
        c = ph.encode()
        s = Solver(c, emit_proof=True)
        r = s.solve()
        ok, _ = check_proof(c.clauses, s.proof)
        print(f"  PHP({p},{p-1}): {r} proof_steps={len(s.proof)} verified={ok}  {s.stats}")

    print("\n[4] Graph colouring: C5 needs 3 colours (2 is UNSAT)")
    edges = [(i, (i + 1) % 5) for i in range(5)]
    for k in (2, 3):
        c = GraphColoring(5, edges, k).encode()
        s = Solver(c, emit_proof=True)
        r = s.solve()
        extra = ""
        if r == UNSAT:
            ok, _ = check_proof(c.clauses, s.proof)
            extra = f"proof_verified={ok}"
        print(f"  C5 with {k} colours: {r} {extra}")

    print("\n[5] Exact model counting (#SAT), cross-checked vs brute force")
    rng = random.Random(1)
    c = random_ksat(8, 16, 3, rng)
    from .brute import count_models as bc
    cdcl_count = count_models(c)
    print(f"  random 3-SAT (8 vars, 16 clauses): #SAT = {cdcl_count}, "
          f"brute = {bc(c.num_vars, c.clauses)}")

    print("\n[6] Differential fuzz: 400 random instances vs brute force")
    rng = random.Random(99)
    mism = 0
    for _ in range(400):
        nv = rng.randint(1, 9)
        cc = random_ksat(nv, rng.randint(0, nv * 4), 3, rng)
        s = Solver(cc, emit_proof=True)
        r = s.solve()
        if (r == SAT) != brute_is_sat(nv, cc.clauses):
            mism += 1
        elif r == SAT and not check_model(cc.clauses, s.model()):
            mism += 1
        elif r == UNSAT and not check_proof(cc.clauses, s.proof)[0]:
            mism += 1
    print(f"  400 trials, mismatches/bad-certificates = {mism}")

    print("\n[7] Generating an interactive visualizer for a small 3-colouring")
    gedges = [(0, 1), (1, 2), (2, 0), (0, 3), (1, 3), (2, 4), (3, 4), (1, 4)]
    vc = GraphColoring(5, gedges, 3).encode()
    _write_viz(vc, "demo_visualizer.html", "Graph 3-colouring (demo)")

    print("\nDemo complete.")
    return 0


# --------------------------------------------------------------------------
def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="backjump", description="A CDCL SAT solver.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("solve", help="solve a DIMACS CNF file")
    sp.add_argument("file", help="DIMACS file, or - for stdin")
    sp.add_argument("--model", action="store_true", help="print the model")
    sp.add_argument("--viz", metavar="OUT.html", help="also write a visualizer")
    sp.add_argument("--restart", type=int, default=100)
    sp.set_defaults(func=cmd_solve)

    sp = sub.add_parser("sudoku", help="solve a Sudoku puzzle")
    sp.add_argument("file", nargs="?", help="puzzle file (81 chars), or - for stdin")
    sp.add_argument("--size", type=int, default=9)
    sp.add_argument("--viz", metavar="OUT.html")
    sp.add_argument("--restart", type=int, default=100)
    sp.set_defaults(func=cmd_sudoku)

    sp = sub.add_parser("queens", help="solve the N-queens problem")
    sp.add_argument("n", type=int)
    sp.add_argument("--viz", metavar="OUT.html")
    sp.add_argument("--restart", type=int, default=100)
    sp.set_defaults(func=cmd_queens)

    sp = sub.add_parser("color", help="graph k-colouring")
    sp.add_argument("k", type=int, help="number of colours")
    sp.add_argument("--cycle", type=int, help="use a cycle graph C_n")
    sp.add_argument("--complete", type=int, help="use a complete graph K_n")
    sp.add_argument("--edges", nargs="+", help="edges like 0-1 1-2 ...")
    sp.add_argument("--vertices", type=int)
    sp.add_argument("--viz", metavar="OUT.html")
    sp.add_argument("--restart", type=int, default=100)
    sp.set_defaults(func=cmd_color)

    sp = sub.add_parser("pigeon", help="pigeonhole principle (UNSAT when p>h)")
    sp.add_argument("pigeons", type=int)
    sp.add_argument("holes", type=int)
    sp.add_argument("--viz", metavar="OUT.html")
    sp.add_argument("--restart", type=int, default=100)
    sp.set_defaults(func=cmd_pigeon)

    sp = sub.add_parser("gen", help="generate a random k-SAT DIMACS file")
    sp.add_argument("--vars", type=int, default=50)
    sp.add_argument("--clauses", type=int, default=210)
    sp.add_argument("--k", type=int, default=3)
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--out", help="output file (default stdout)")
    sp.set_defaults(func=cmd_gen)

    sp = sub.add_parser("count", help="exact #SAT / AllSAT via blocking clauses")
    sp.add_argument("file", nargs="?", help="DIMACS file, or - for stdin")
    sp.add_argument("--vars", type=int, default=10)
    sp.add_argument("--clauses", type=int, default=20)
    sp.add_argument("--k", type=int, default=3)
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--limit", type=int, default=None, help="stop after N models")
    sp.add_argument("--show", type=int, default=0, help="print first N models")
    sp.add_argument("--check", action="store_true", help="cross-check vs brute force")
    sp.set_defaults(func=cmd_count)

    sp = sub.add_parser("fuzz", help="differential test vs brute force")
    sp.add_argument("--trials", type=int, default=1000)
    sp.add_argument("--vars", type=int, default=10)
    sp.add_argument("--ratio", type=float, default=4.5)
    sp.add_argument("--k", type=int, default=3)
    sp.add_argument("--seed", type=int, default=0)
    sp.set_defaults(func=cmd_fuzz)

    sp = sub.add_parser("phase", help="3-SAT phase-transition demo")
    sp.add_argument("--vars", type=int, default=40)
    sp.add_argument("--lo", type=float, default=2.0)
    sp.add_argument("--hi", type=float, default=7.0)
    sp.add_argument("--steps", type=int, default=10)
    sp.add_argument("--samples", type=int, default=40)
    sp.add_argument("--seed", type=int, default=0)
    sp.set_defaults(func=cmd_phase)

    sp = sub.add_parser("viz", help="write an interactive HTML visualizer")
    sp.add_argument("kind", choices=["dimacs", "color", "pigeon", "queens", "random"])
    sp.add_argument("--out", default="backjump_viz.html")
    sp.add_argument("--file", help="DIMACS file for kind=dimacs")
    sp.add_argument("--k", type=int, default=3)
    sp.add_argument("--cycle", type=int)
    sp.add_argument("--complete", type=int)
    sp.add_argument("--edges", nargs="+")
    sp.add_argument("--vertices", type=int)
    sp.add_argument("--n", type=int, default=6)
    sp.add_argument("--pigeons", type=int, default=4)
    sp.add_argument("--holes", type=int, default=3)
    sp.add_argument("--vars", type=int, default=8)
    sp.add_argument("--clauses", type=int, default=20)
    sp.add_argument("--seed", type=int, default=0)
    sp.set_defaults(func=cmd_viz)

    sp = sub.add_parser("demo", help="run a guided tour of every feature")
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
    except (ValueError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0
    except KeyboardInterrupt:
        print("\ninterrupted", file=sys.stderr)
        return 130


if __name__ == "__main__":
    sys.exit(main())
