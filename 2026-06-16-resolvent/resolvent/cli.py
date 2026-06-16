"""Command-line interface for Resolvent."""
from __future__ import annotations

import argparse
import sys
import time
from typing import List

from .cnf import CNF, parse_dimacs, DimacsError
from .solver import Solver
from .oracle import brute_force
from .generate import random_ksat, random_at_ratio
from . import encoders
from . import proof as proofmod
from . import viz as vizmod


def _read(path: str) -> str:
    if path == "-":
        return sys.stdin.read()
    with open(path, "r") as f:
        return f.read()


def _load_cnf(path: str) -> CNF:
    try:
        return parse_dimacs(_read(path))
    except DimacsError as e:
        print(str(e), file=sys.stderr)
        sys.exit(2)


def _print_stats(s: Solver, elapsed: float) -> None:
    st = s.stats
    print(
        f"c stats: {st.decisions} decisions, {st.conflicts} conflicts, "
        f"{st.propagations} propagations, {st.learned} learned, "
        f"{st.restarts} restarts, {st.deleted_clauses} deleted "
        f"({st.db_reductions} reductions), maxlevel {st.max_decision_level}, "
        f"{elapsed*1000:.1f} ms",
        file=sys.stderr,
    )


# -- subcommands ---------------------------------------------------------
def cmd_solve(args) -> int:
    cnf = _load_cnf(args.file)
    s = Solver(cnf, use_restarts=not args.no_restarts, use_vsids=not args.no_vsids,
               reduce_db=not args.no_reduce, log_proof=bool(args.proof), seed=args.seed)
    t0 = time.perf_counter()
    sat = s.solve()
    elapsed = time.perf_counter() - t0
    if sat:
        print("s SATISFIABLE")
        model = s.model()
        if not cnf.is_satisfied_by(model):
            print("e INTERNAL ERROR: model does not satisfy formula", file=sys.stderr)
            return 3
        line = " ".join(str(x) for x in model)
        print("v " + line + " 0")
    else:
        print("s UNSATISFIABLE")
        if args.proof:
            with open(args.proof, "w") as f:
                f.write(proofmod.serialize_proof(s.proof))
            print(f"c DRUP proof ({len(s.proof)} steps) written to {args.proof}",
                  file=sys.stderr)
    _print_stats(s, elapsed)
    return 10 if sat else 20


def cmd_gen(args) -> int:
    cnf = random_ksat(args.vars, args.clauses, k=args.k, seed=args.seed)
    out = cnf.to_dimacs(comment=f"random {args.k}-SAT  vars={args.vars} "
                                f"clauses={args.clauses} seed={args.seed}")
    if args.out:
        with open(args.out, "w") as f:
            f.write(out)
        print(f"c wrote {args.out}", file=sys.stderr)
    else:
        sys.stdout.write(out)
    return 0


def cmd_check(args) -> int:
    cnf = _load_cnf(args.file)
    model = []
    for t in _read(args.model).split():
        try:
            v = int(t)
        except ValueError:
            continue  # skip 'v', 's', 'SATISFIABLE', comments, etc.
        if v != 0:
            model.append(v)
    ok = cnf.is_satisfied_by(model)
    print("VALID — model satisfies all clauses" if ok else "INVALID — model fails")
    return 0 if ok else 1


def cmd_fuzz(args) -> int:
    rng_seed = args.seed
    mism = 0
    bad_model = 0
    sat_count = 0
    for i in range(args.n):
        seed = rng_seed + i
        nv = (seed % (args.max_vars - 2)) + 3
        ratio = 3.5 + (seed % 200) / 100.0  # 3.5 .. 5.5, spanning the transition
        cnf = random_at_ratio(nv, ratio, k=3, seed=seed * 7919 + 13)
        exp_sat, _ = brute_force(cnf)
        s = Solver(cnf, seed=seed)
        got_sat = s.solve()
        if got_sat != exp_sat:
            mism += 1
            print(f"MISMATCH seed={seed} vars={nv}: oracle={exp_sat} solver={got_sat}",
                  file=sys.stderr)
            if mism <= 3:
                print(cnf.to_dimacs(), file=sys.stderr)
        elif got_sat:
            sat_count += 1
            if not cnf.is_satisfied_by(s.model()):
                bad_model += 1
                print(f"BAD MODEL seed={seed}", file=sys.stderr)
        if (i + 1) % max(1, args.n // 10) == 0:
            print(f"c {i+1}/{args.n} ok (mismatches={mism}, bad_models={bad_model})",
                  file=sys.stderr)
    print(f"fuzz: {args.n} instances, {sat_count} SAT, "
          f"{mism} verdict mismatches, {bad_model} bad models")
    return 0 if (mism == 0 and bad_model == 0) else 1


def cmd_bench(args) -> int:
    print(f"c phase transition sweep: {args.vars} vars, {args.trials} trials/ratio")
    print(f"{'ratio':>6}  {'P(SAT)':>7}  {'avg conflicts':>14}")
    r = args.lo
    while r <= args.hi + 1e-9:
        sat = 0
        confl = 0
        for t in range(args.trials):
            cnf = random_at_ratio(args.vars, r, k=3, seed=args.seed + t * 101 + int(r * 1000))
            s = Solver(cnf, seed=t)
            if s.solve():
                sat += 1
            confl += s.stats.conflicts
        print(f"{r:6.2f}  {sat/args.trials:7.2f}  {confl/args.trials:14.1f}")
        r += args.step
    return 0


def _build_encoding(args) -> encoders.Encoding:
    kind = args.problem
    if kind == "queens":
        return encoders.encode_queens(args.n)
    if kind == "pigeonhole":
        return encoders.encode_pigeonhole(args.holes, args.pigeons)
    if kind == "sudoku":
        text = _read(args.sudoku) if args.sudoku else _DEFAULT_SUDOKU
        return encoders.encode_sudoku(text)
    if kind == "color":
        n, edges = encoders.parse_graph(_read(args.graph))
        return encoders.encode_coloring(n, edges, args.colors)
    raise ValueError(kind)


def cmd_encode(args) -> int:
    enc = _build_encoding(args)
    out = enc.cnf.to_dimacs(comment=f"encoding: {enc.name}")
    if args.out:
        with open(args.out, "w") as f:
            f.write(out)
        print(f"c wrote {args.out} ({enc.cnf.nvars} vars, {enc.cnf.nclauses} clauses)",
              file=sys.stderr)
    else:
        sys.stdout.write(out)
    return 0


def cmd_solve_puzzle(args) -> int:
    enc = _build_encoding(args)
    s = Solver(enc.cnf, log_proof=bool(args.proof))
    t0 = time.perf_counter()
    sat = s.solve()
    elapsed = time.perf_counter() - t0
    print(f"c {enc.name}: {enc.cnf.nvars} vars, {enc.cnf.nclauses} clauses",
          file=sys.stderr)
    if sat:
        print(f"s SATISFIABLE")
        print(enc.decode(s.model()))
    else:
        print("s UNSATISFIABLE (no solution exists)")
        if args.proof:
            with open(args.proof, "w") as f:
                f.write(proofmod.serialize_proof(s.proof))
            print(f"c DRUP proof written to {args.proof}", file=sys.stderr)
    _print_stats(s, elapsed)
    return 10 if sat else 20


def cmd_viz(args) -> int:
    cnf = _load_cnf(args.file)
    s = Solver(cnf, record_conflict_graph=True, seed=args.seed)
    s.solve()
    if s.conflict_graph is None:
        print("e no conflict occurred — nothing to visualize "
              "(formula solved without backtracking)", file=sys.stderr)
        return 1
    html = vizmod.render_html(s.conflict_graph)
    with open(args.out, "w") as f:
        f.write(html)
    print(f"c implication graph written to {args.out}", file=sys.stderr)
    return 0


def cmd_proofcheck(args) -> int:
    cnf = _load_cnf(args.file)
    proof = proofmod.parse_proof(_read(args.proof))
    ok = proofmod.check_proof(cnf, proof)
    if ok:
        print(f"VERIFIED — DRUP proof ({len(proof)} steps) derives the empty clause; "
              "formula is UNSAT")
        return 0
    print("REJECTED — proof does not establish UNSAT")
    return 1


def cmd_demo(args) -> int:
    from .demo import run_demo
    return run_demo()


_DEFAULT_SUDOKU = (
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


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        prog="resolvent", description="A from-scratch CDCL SAT solver.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("solve", help="solve a DIMACS CNF file")
    sp.add_argument("file")
    sp.add_argument("--proof", metavar="FILE", help="write a DRUP proof if UNSAT")
    sp.add_argument("--no-restarts", action="store_true")
    sp.add_argument("--no-vsids", action="store_true")
    sp.add_argument("--no-reduce", action="store_true")
    sp.add_argument("--seed", type=int, default=0)
    sp.set_defaults(func=cmd_solve)

    sp = sub.add_parser("gen", help="generate random k-SAT")
    sp.add_argument("--vars", type=int, default=50)
    sp.add_argument("--clauses", type=int, default=213)
    sp.add_argument("--k", type=int, default=3)
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--out", help="output file (default stdout)")
    sp.set_defaults(func=cmd_gen)

    sp = sub.add_parser("check", help="verify a model satisfies a formula")
    sp.add_argument("file")
    sp.add_argument("model", help="file with a model (signed literals)")
    sp.set_defaults(func=cmd_check)

    sp = sub.add_parser("fuzz", help="differential test vs brute-force oracle")
    sp.add_argument("-n", type=int, default=500)
    sp.add_argument("--max-vars", type=int, default=14)
    sp.add_argument("--seed", type=int, default=1)
    sp.set_defaults(func=cmd_fuzz)

    sp = sub.add_parser("bench", help="phase-transition sweep")
    sp.add_argument("--vars", type=int, default=80)
    sp.add_argument("--lo", type=float, default=3.0)
    sp.add_argument("--hi", type=float, default=6.0)
    sp.add_argument("--step", type=float, default=0.5)
    sp.add_argument("--trials", type=int, default=20)
    sp.add_argument("--seed", type=int, default=0)
    sp.set_defaults(func=cmd_bench)

    def add_problem(sp):
        sp.add_argument("problem", choices=["queens", "sudoku", "color", "pigeonhole"])
        sp.add_argument("--n", type=int, default=8, help="N (queens)")
        sp.add_argument("--holes", type=int, default=5, help="holes (pigeonhole)")
        sp.add_argument("--pigeons", type=int, default=None, help="pigeons (default holes+1)")
        sp.add_argument("--sudoku", help="sudoku givens file (81 cells)")
        sp.add_argument("--graph", help="graph file for coloring")
        sp.add_argument("--colors", type=int, default=3, help="colors (coloring)")

    sp = sub.add_parser("encode", help="emit CNF for a named problem")
    add_problem(sp)
    sp.add_argument("--out", help="output file (default stdout)")
    sp.set_defaults(func=cmd_encode)

    sp = sub.add_parser("solve-puzzle", help="encode -> solve -> decode a problem")
    add_problem(sp)
    sp.add_argument("--proof", metavar="FILE", help="write a DRUP proof if UNSAT")
    sp.set_defaults(func=cmd_solve_puzzle)

    sp = sub.add_parser("viz", help="solve and emit an implication-graph HTML page")
    sp.add_argument("file")
    sp.add_argument("--out", default="implication-graph.html")
    sp.add_argument("--seed", type=int, default=0)
    sp.set_defaults(func=cmd_viz)

    sp = sub.add_parser("proofcheck", help="independently verify a DRUP UNSAT proof")
    sp.add_argument("file")
    sp.add_argument("proof")
    sp.set_defaults(func=cmd_proofcheck)

    sp = sub.add_parser("demo", help="run the full end-to-end demo")
    sp.set_defaults(func=cmd_demo)

    return p


def main(argv: List[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
