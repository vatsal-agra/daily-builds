"""Command line interface: ``python -m parsimony <command> GRAMMAR [options]``."""
from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from .api import ALL_METHODS, Language
from .grammar import GrammarError
from .lexer import LexError
from .lr import METHODS, ParseError


def _read_input(args) -> str:
    if getattr(args, "expr", None) is not None:
        return args.expr
    if getattr(args, "file", None):
        with open(args.file, encoding="utf-8") as f:
            return f.read()
    return sys.stdin.read()


def _render(tree, args) -> str:
    if args.compact:
        tree = tree.compact()
    return {"tree": tree.pretty, "sexp": tree.sexp, "json": tree.json}[args.format]()


def cmd_check(lang: Language, args) -> int:
    print(lang.analysis.report())
    from .classify import classify, format_classification
    print()
    print(format_classification(classify(lang)))
    return 0


def cmd_conflicts(lang: Language, args) -> int:
    methods = [args.method] if args.method else ["slr", "lalr", "lr1"]
    bad = 0
    for m in methods:
        t = lang.table(m)
        print(t.conflict_report())
        bad += len(t.conflicts)
        if t.resolved and args.verbose:
            print(f"  resolved by precedence ({len(t.resolved)}):")
            for r in t.resolved:
                print("    " + r)
    return 1 if bad else 0


def cmd_states(lang: Language, args) -> int:
    t = lang.table(args.method)
    print(t.action_grid() if args.grid else t.dump_states())
    return 0


def cmd_parse(lang: Language, args) -> int:
    text = _read_input(args)
    trace: Optional[list] = [] if args.trace else None
    if args.method not in ALL_METHODS:
        print(f"error: unknown method {args.method}", file=sys.stderr); return 2
    try:
        tree = lang.parse(text, args.method, trace)
    except (LexError, ParseError) as e:
        if trace:
            _print_trace(trace)
        print(f"error: {e}", file=sys.stderr)
        return 1
    if trace:
        _print_trace(trace)
        print()
    print(_render(tree, args))
    return 0


def _print_trace(rows):
    print(f"{'step':>4}  {'lookahead':<10} {'action':<34} stack")
    for r in rows:
        print(f"{r.step:>4}  {r.lookahead:<10} {r.action:<34} {r.stack}")


def cmd_ambig(lang: Language, args) -> int:
    text = _read_input(args)
    try:
        res = lang.earley(text)
    except (LexError, ParseError) as e:
        print(f"error: {e}", file=sys.stderr); return 1
    n = res.count()
    print(f"parses: {'infinitely many' if n == float('inf') else n}")
    if n == 1:
        print("the input is unambiguous"); print(res.trees(1)[0].pretty()); return 0
    for line in res.ambiguities():
        print("  ambiguity:", line)
    for i, t in enumerate(res.trees(args.limit), 1):
        print(f"\n— parse {i} —\n{t.compact().sexp() if args.compact else t.sexp()}")
    return 0


def cmd_gen(lang: Language, args) -> int:
    from .codegen import generate
    code = generate(lang, args.method)
    if args.output:
        with open(args.output, "w", encoding="utf-8") as f:
            f.write(code)
        print(f"wrote {args.output} ({len(code.splitlines())} lines)")
    else:
        sys.stdout.write(code)
    return 0


def cmd_ll1(lang: Language, args) -> int:
    from .ll1 import build_ll1
    t = build_ll1(lang.grammar, lang.analysis)
    print(t.dump())
    return 1 if t.conflicts else 0


def cmd_transform(lang: Language, args) -> int:
    from .transform import make_ll1_friendly
    from .ll1 import build_ll1
    from .analysis import Analysis
    g2, log = make_ll1_friendly(lang.grammar)
    for l in log:
        print("# " + l)
    print(g2.pretty())
    t = build_ll1(g2, Analysis(g2))
    print(f"\n# LL(1) conflicts after transform: {len(t.conflicts)}")
    return 0


def main(argv: Optional[List[str]] = None) -> int:
    ap = argparse.ArgumentParser(prog="parsimony", description="Parser-generator laboratory")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def add(name, fn, help, io=False, method=None):
        p = sub.add_parser(name, help=help)
        p.add_argument("grammar", help="grammar file")
        if method:
            p.add_argument("-m", "--method", default=method, help=f"one of {', '.join(ALL_METHODS)}")
        if io:
            p.add_argument("-e", "--expr", help="input text")
            p.add_argument("-f", "--file", help="input file (default: stdin)")
        p.set_defaults(fn=fn)
        return p

    add("check", cmd_check, "analyse the grammar and classify it (LL(1)/SLR/LALR/LR(1))")
    p = add("conflicts", cmd_conflicts, "list parser conflicts with example inputs")
    p.add_argument("-m", "--method", choices=METHODS); p.add_argument("-v", "--verbose", action="store_true")
    p = add("states", cmd_states, "dump the LR automaton or action/goto grid", method="lalr")
    p.set_defaults(lr_only=True)
    p.add_argument("--grid", action="store_true")
    p = add("parse", cmd_parse, "parse input", io=True, method="lalr")
    p.add_argument("--format", choices=["tree", "sexp", "json"], default="tree")
    p.add_argument("--compact", action="store_true", help="collapse unit-production chains")
    p.add_argument("--trace", action="store_true", help="show the shift/reduce steps")
    p = add("ambig", cmd_ambig, "count and enumerate every parse (Earley)", io=True)
    p.add_argument("--limit", type=int, default=5); p.add_argument("--compact", action="store_true")
    p = add("gen", cmd_gen, "emit a standalone parser module", method="lalr")
    p.add_argument("-o", "--output")
    add("ll1", cmd_ll1, "show the LL(1) table and its conflicts")
    add("transform", cmd_transform, "eliminate left recursion + left-factor toward LL(1)")

    args = ap.parse_args(argv)
    if getattr(args, "lr_only", False) and args.method not in METHODS:
        ap.error(f"--method must be one of {', '.join(METHODS)} for this command")
    if args.cmd == "gen" and args.method not in METHODS:
        ap.error(f"--method must be one of {', '.join(METHODS)} for gen")
    try:
        style = "right" if args.cmd in ("ll1", "transform") or getattr(args, "method", None) == "ll1" else "left"
        lang = Language.from_file(args.grammar, ebnf_style=style)
        return args.fn(lang, args)
    except GrammarError as e:
        print(f"grammar error: {e}", file=sys.stderr); return 2
    except (OSError, UnicodeError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr); return 2
