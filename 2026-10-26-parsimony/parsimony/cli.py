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
        if t.conflicts and args.witness:
            _show_witness(lang, 10)
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
    if args.recover:
        if args.method not in METHODS:
            print("error: --recover needs an LR method", file=sys.stderr); return 2
        from .lr import LRParser
        try:
            res = LRParser(lang.table(args.method)).parse_recovering(lang.tokenize(text))
        except LexError as e:
            print(f"error: {e}", file=sys.stderr); return 1
        for e in res.errors:
            print(f"error: {e}", file=sys.stderr)
        if res.tree is None:
            print("error: could not recover", file=sys.stderr); return 1
        print(_render(res.tree, args))
        return 1 if res.errors else 0
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


def cmd_compare(lang: Language, args) -> int:
    """Run every strategy on the same input and check that they agree."""
    text = _read_input(args)
    results = {}
    for m in ALL_METHODS:
        try:
            if m in METHODS and lang.table(m).conflicts:
                results[m] = ("skip", f"{len(lang.table(m).conflicts)} conflict(s)")
                continue
            results[m] = ("ok", lang.parse(text, m))
        except (LexError, ParseError) as e:
            results[m] = ("reject", str(e))
        except GrammarError as e:
            results[m] = ("skip", "not LL(1)")
    ok = {m: v for m, (k, v) in results.items() if k == "ok"}
    for m, (k, v) in results.items():
        if k == "ok":
            print(f"  {m:<7} accept  {v.compact().sexp()[:70]}")
        else:
            print(f"  {m:<7} {k:<7} {str(v)[:70]}")
    trees = list(ok.values())
    agree = all(t == trees[0] for t in trees)
    verdicts = {k for k, _ in results.values() if k in ("ok", "reject")}
    if len(verdicts) > 1:
        print("DISAGREEMENT on accept/reject"); return 3
    print("all deterministic strategies agree" + (" on the parse tree" if trees and agree else
          " (trees differ — expected when the grammar is ambiguous or has precedence)" if trees else ""))
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


def _show_witness(lang: Language, max_len: int) -> bool:
    from .witness import find_ambiguity
    w = find_ambiguity(lang.grammar, max_len=max_len, an=lang.analysis)
    if w is None:
        print(f"no ambiguous sentence of up to {max_len} tokens found (this is not a proof of unambiguity)")
        return False
    n = "infinitely many" if w.parses == float("inf") else str(int(w.parses))
    print(f"ambiguous sentence: {w.text()}    ({n} parses)")
    for i, t in enumerate(w.trees, 1):
        print(f"  parse {i}: {t.compact().sexp()}")
    return True


def cmd_witness(lang: Language, args) -> int:
    return 0 if not _show_witness(lang, args.max_len) else 1


def cmd_ll1(lang: Language, args) -> int:
    from .ll1 import build_ll1
    twin = lang.ll1_language()
    t = build_ll1(twin.grammar, twin.analysis)
    print(t.dump())
    return 1 if t.conflicts else 0


def cmd_transform(lang: Language, args) -> int:
    from .transform import make_ll1_friendly
    from .ll1 import build_ll1
    from .analysis import Analysis
    g2, log = make_ll1_friendly(lang.grammar)
    for l in log:
        print("# " + l)
    print(g2.pretty(full=True))
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
    p.add_argument("--witness", action="store_true", help="also search for a concrete ambiguous sentence")
    p = add("states", cmd_states, "dump the LR automaton or action/goto grid", method="lalr")
    p.set_defaults(lr_only=True)
    p.add_argument("--grid", action="store_true")
    p = add("parse", cmd_parse, "parse input", io=True, method="lalr")
    p.add_argument("--format", choices=["tree", "sexp", "json"], default="tree")
    p.add_argument("--compact", action="store_true", help="collapse unit-production chains")
    p.add_argument("--trace", action="store_true", help="show the shift/reduce steps")
    p.add_argument("--recover", action="store_true", help="resynchronise at `error` rules and report every syntax error")
    add("compare", cmd_compare, "parse with every strategy and cross-check the results", io=True)
    p = add("ambig", cmd_ambig, "count and enumerate every parse (Earley)", io=True)
    p.add_argument("--limit", type=int, default=5); p.add_argument("--compact", action="store_true")
    p = add("gen", cmd_gen, "emit a standalone parser module", method="lalr")
    p.add_argument("-o", "--output")
    p = add("witness", cmd_witness, "search for a sentence with two parse trees (proves ambiguity)")
    p.add_argument("--max-len", type=int, default=10)
    add("ll1", cmd_ll1, "show the LL(1) table and its conflicts")
    add("transform", cmd_transform, "eliminate left recursion + left-factor toward LL(1)")

    args = ap.parse_args(argv)
    if getattr(args, "lr_only", False) and args.method not in METHODS:
        ap.error(f"--method must be one of {', '.join(METHODS)} for this command")
    if args.cmd == "gen" and args.method not in METHODS:
        ap.error(f"--method must be one of {', '.join(METHODS)} for gen")
    try:
        lang = Language.from_file(args.grammar)
        return args.fn(lang, args)
    except GrammarError as e:
        print(f"grammar error: {e}", file=sys.stderr); return 2
    except BrokenPipeError:
        sys.stderr.close()                      # e.g. `parsimony states ... | head`; not an error
        return 0
    except (OSError, UnicodeError, ValueError) as e:
        print(f"error: {e}", file=sys.stderr); return 2
