"""Command-line interface for Resolvent.

Subcommands:
  solve   <file.cnf>        decide a DIMACS CNF, print SAT/UNSAT + model + stats
  fuzz    [--n N --seed S]  differential test vs an exhaustive oracle
  encode  <problem> ...     compile Sudoku/coloring/queens/php to DIMACS
  decode  <problem> <file>  solve an encoded problem and pretty-print the answer
  verify  <file.cnf>        prove UNSAT and independently check the proof (RUP)
  viz     <file.cnf> [out]  render the conflict implication graph to HTML
  demo                      run a guided tour of every feature
"""
from __future__ import annotations

import argparse
import sys
import time

from .cnf import CNF, DimacsError, read_dimacs_file
from .solver import Solver


def _fmt_stats(s) -> str:
    st = s.stats
    return (f"  decisions     {st.decisions}\n"
            f"  propagations  {st.propagations}\n"
            f"  conflicts     {st.conflicts}\n"
            f"  learned       {st.learned}\n"
            f"  restarts      {st.restarts}\n"
            f"  db reductions {st.db_reductions} (removed {st.removed_clauses})\n"
            f"  max level     {st.max_decision_level}")


def cmd_solve(args) -> int:
    try:
        formula = read_dimacs_file(args.file)
    except (DimacsError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    if formula.nvars == 0 and formula.nclauses == 0:
        print("s SATISFIABLE")
        print("c (empty formula — trivially satisfiable)")
        return 10
    s = Solver(formula, rng_seed=args.seed)
    t0 = time.time()
    sat = s.solve()
    elapsed = time.time() - t0
    print(f"c solved in {elapsed*1000:.1f} ms over {formula.nvars} vars,"
          f" {formula.nclauses} clauses")
    if sat:
        model = s.model()
        if not formula.is_satisfied_by(model):
            print("c INTERNAL ERROR: produced model does not satisfy formula!",
                  file=sys.stderr)
            return 3
        print("c model verified against original clauses")
        print("s SATISFIABLE")
        if not args.no_model:
            lits = [str(v if model[v] else -v) for v in range(1, formula.nvars + 1)]
            # DIMACS-style 'v' lines.
            line = "v"
            for tok in lits:
                if len(line) + len(tok) + 1 > 76:
                    print(line)
                    line = "v"
                line += " " + tok
            print(line + " 0")
        print("c stats")
        print(_fmt_stats(s))
        return 10
    else:
        print("s UNSATISFIABLE")
        print("c stats")
        print(_fmt_stats(s))
        return 20


def cmd_fuzz(args) -> int:
    from .bruteforce import truth_table_sat
    import random
    rng = random.Random(args.seed)
    mismatches = 0
    bad_models = 0
    for t in range(args.n):
        nv = rng.randint(1, args.maxvars)
        nc = rng.randint(1, int(nv * 4.5) + 2)
        f = CNF(nv)
        for _ in range(nc):
            k = rng.randint(1, min(3, nv))
            clause = []
            for _ in range(k):
                v = rng.randint(1, nv)
                clause.append(v if rng.random() < 0.5 else -v)
            f.add_clause(clause)
        s = Solver(f)
        sat = s.solve()
        oracle = truth_table_sat(f)
        if sat != oracle:
            mismatches += 1
            print(f"MISMATCH (solver={sat}, oracle={oracle}): {f.clauses}")
        if sat and not f.is_satisfied_by(s.model()):
            bad_models += 1
            print(f"BAD MODEL: {f.clauses}")
    print(f"c fuzzed {args.n} random formulas (<= {args.maxvars} vars, seed {args.seed})")
    if mismatches == 0 and bad_models == 0:
        print(f"OK — solver agreed with the exhaustive oracle on every instance")
        return 0
    print(f"FAIL — {mismatches} verdict mismatches, {bad_models} invalid models")
    return 1


def cmd_encode(args) -> int:
    from . import encoders
    try:
        f, _meta = encoders.build(args.problem, args.params)
    except (ValueError, IndexError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    sys.stdout.write(f.to_dimacs())
    return 0


def cmd_decode(args) -> int:
    from . import encoders
    try:
        return encoders.solve_and_print(args.problem, args.params, args.file)
    except (ValueError, IndexError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    except OSError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


def cmd_verify(args) -> int:
    from .proof import check_unsat_proof
    try:
        formula = read_dimacs_file(args.file)
    except (DimacsError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    s = Solver(formula, record_proof=True)
    sat = s.solve()
    if sat:
        print("s SATISFIABLE")
        print("c formula is satisfiable; nothing to prove (model verified:"
              f" {formula.is_satisfied_by(s.model())})")
        return 10
    print("s UNSATISFIABLE")
    proof = s.get_proof()
    print(f"c solver emitted a {len(proof)}-step clausal proof; checking it"
          " with an independent RUP verifier...")
    ok, msg = check_unsat_proof(formula, proof)
    if ok:
        print(f"c PROOF VERIFIED — {msg}")
        return 20
    print(f"c PROOF REJECTED — {msg}", file=sys.stderr)
    return 1


def cmd_viz(args) -> int:
    from .viz import render_conflict_html
    try:
        formula = read_dimacs_file(args.file)
    except (DimacsError, OSError) as e:
        print(f"error: {e}", file=sys.stderr)
        return 2
    out = args.out or "conflict.html"
    msg = render_conflict_html(formula, out)
    print(msg)
    return 0


def cmd_demo(args) -> int:
    from . import demo as demo_mod
    return demo_mod.run()


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(prog="resolvent",
                                description="A from-scratch CDCL SAT solver.")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("solve", help="solve a DIMACS CNF file")
    sp.add_argument("file")
    sp.add_argument("--seed", type=int, default=0)
    sp.add_argument("--no-model", action="store_true", help="don't print the model")
    sp.set_defaults(func=cmd_solve)

    fp = sub.add_parser("fuzz", help="differential test against an exhaustive oracle")
    fp.add_argument("--n", type=int, default=1000)
    fp.add_argument("--seed", type=int, default=0)
    fp.add_argument("--maxvars", type=int, default=8)
    fp.set_defaults(func=cmd_fuzz)

    ep = sub.add_parser("encode", help="compile a problem to DIMACS CNF")
    ep.add_argument("problem", choices=["sudoku", "coloring", "queens", "php"])
    ep.add_argument("params", nargs="*", help="problem-specific arguments")
    ep.set_defaults(func=cmd_encode)

    dp = sub.add_parser("decode", help="solve an encoded problem and pretty-print it")
    dp.add_argument("problem", choices=["sudoku", "coloring", "queens", "php"])
    dp.add_argument("params", nargs="*")
    dp.add_argument("--file", default=None, help="(optional) puzzle input file")
    dp.set_defaults(func=cmd_decode)

    vp = sub.add_parser("verify", help="prove UNSAT and independently check the proof")
    vp.add_argument("file")
    vp.set_defaults(func=cmd_verify)

    zp = sub.add_parser("viz", help="render the conflict implication graph to HTML")
    zp.add_argument("file")
    zp.add_argument("out", nargs="?", default=None)
    zp.set_defaults(func=cmd_viz)

    mp = sub.add_parser("demo", help="run a guided tour of every feature")
    mp.set_defaults(func=cmd_demo)
    return p


def main(argv=None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
