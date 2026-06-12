"""Command-line interface: python3 -m rxlab <command> …"""

import argparse
import sys

from . import compile as rx_compile
from . import parser as P
from .lexer import RegexError


def _ast_dump(node, indent=0):
    pad = "  " * indent
    if isinstance(node, P.Lit):
        return f"{pad}Lit {node.ch!r}"
    if isinstance(node, P.Dot):
        return f"{pad}Dot ."
    if isinstance(node, P.CharClass):
        neg = " negated" if node.negated else ""
        return f"{pad}Class {node.label}{neg}"
    if isinstance(node, P.Anchor):
        return f"{pad}Anchor {node.kind}"
    if isinstance(node, P.Concat):
        lines = [f"{pad}Concat"]
        lines += [_ast_dump(p, indent + 1) for p in node.parts]
        return "\n".join(lines)
    if isinstance(node, P.Alt):
        lines = [f"{pad}Alt"]
        lines += [_ast_dump(b, indent + 1) for b in node.branches]
        return "\n".join(lines)
    if isinstance(node, P.Repeat):
        hi = "∞" if node.hi is None else node.hi
        lazy = " lazy" if node.lazy else ""
        return (f"{pad}Repeat {{{node.lo},{hi}}}{lazy}\n"
                + _ast_dump(node.child, indent + 1))
    if isinstance(node, P.Group):
        which = f"capture #{node.index}" if node.index else "non-capturing"
        return f"{pad}Group {which}\n" + _ast_dump(node.child, indent + 1)
    return f"{pad}?{node!r}"


def cmd_parse(args):
    ast, ngroups = P.parse(args.pattern)
    print(_ast_dump(ast))
    print(f"({ngroups} capturing group{'s' if ngroups != 1 else ''})")


def _print_match(m, text):
    if m is None:
        print("no match")
        return 1
    s, e = m.span()
    print(f"match  span=({s}, {e})  {text[s:e]!r}")
    for g in range(1, m.re.ngroups + 1):
        gs, ge = m.span(g)
        if gs == -1:
            print(f"  group {g}: (unset)")
        else:
            print(f"  group {g}: span=({gs}, {ge})  {m.group(g)!r}")
    return 0


def cmd_match(args):
    pat = rx_compile(args.pattern)
    fn = getattr(pat, args.cmd)
    return _print_match(fn(args.text), args.text)


def cmd_findall(args):
    pat = rx_compile(args.pattern)
    out = pat.findall(args.text)
    print(f"{len(out)} match{'es' if len(out) != 1 else ''}")
    for item in out:
        print(f"  {item!r}")


def cmd_trace(args):
    pat = rx_compile(args.pattern)
    text = args.text

    def observer(pos, clist):
        cur = text[pos] if pos < len(text) else "⌀"
        tape = text[:pos] + "⟨" + cur + "⟩" + \
            (text[pos + 1:] if pos < len(text) else "")
        pcs = ", ".join(str(pc) for pc, _ in clist)
        print(f"  pos {pos:<3} {tape!r:<30} threads [{pcs}]")

    print(f"tracing {args.mode} of {args.pattern!r} on {text!r}:")
    m = pat._run(text, 0, args.mode, observer)
    return _print_match(m, text)


def cmd_dfa(args):
    pat = rx_compile(args.pattern)
    d = pat.dfa(minimize=True)
    print(f"pattern        {args.pattern!r}")
    print(f"NFA states     {d.n_nfa}")
    print(f"subset DFA     {d.n_subset}")
    print(f"minimized DFA  {d.n_states}")
    print(f"alphabet       {d.n_classes} character class(es)")
    if args.table:
        from .nfa import format_ranges
        print("\nstate table (missing entries reject):")
        for q in range(len(d.trans)):
            acc = " (accept)" if d.accept[q] else ""
            print(f"  q{q}{acc}")
            for c, t in sorted(d.trans[q].items()):
                print(f"    --[{format_ranges((d.class_ranges[c],))}]--> q{t}")
    if args.text is not None:
        ok = d.fullmatch(args.text)
        print(f"\nfullmatch({args.text!r}) = {ok}")


def cmd_viz(args):
    from .viz import write_html
    sample = args.text
    if sample is None:
        # pre-fill the page with a generated matching string when possible
        try:
            from .gen import generate
            samples, _ = generate(args.pattern, n=1, seed=0)
            sample = samples[0] if samples else ""
        except RegexError:
            sample = ""
    path = write_html(args.pattern, args.out, sample=sample)
    print(f"wrote {path}")
    print("open it in a browser; no network or dependencies needed")


def cmd_explain(args):
    from .explain import explain
    print(explain(args.pattern))


def cmd_gen(args):
    from .gen import generate
    samples, rejected = generate(args.pattern, n=args.n, seed=args.seed)
    for s in samples:
        print(repr(s) if args.repr else s)
    if rejected:
        print(f"({rejected} candidate(s) rejected by verification)",
              file=sys.stderr)


def cmd_fuzz(args):
    from .fuzz import run_fuzz
    print(f"fuzzing {args.n} random patterns vs Python re "
          f"(seed={args.seed}) …")
    checked, diffs = run_fuzz(n=args.n, seed=args.seed, verbose=True)
    if diffs:
        print(f"\n{len(diffs)} DIVERGENCE(S) over {checked} patterns:")
        for d in diffs:
            print("  " + d)
        return 1
    print(f"OK: {checked} patterns × (search, match, fullmatch, findall, "
          "finditer, DFA≡NFA) — no divergences")
    return 0


def main(argv=None):
    ap = argparse.ArgumentParser(
        prog="rxlab",
        description="RegexLab: a from-scratch regex engine "
                    "(NFA, Pike VM, DFA) with an interactive visualizer.",
        epilog="If a pattern starts with '-', separate it with '--', e.g.: "
               "rxlab search -- '-\\d+' 'x-42'")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("parse", help="dump the pattern AST")
    p.add_argument("pattern")
    p.set_defaults(fn=cmd_parse)

    for name, hlp in [("match", "anchored match at position 0"),
                      ("fullmatch", "match the entire string"),
                      ("search", "find the leftmost match")]:
        p = sub.add_parser(name, help=hlp)
        p.add_argument("pattern")
        p.add_argument("text")
        p.set_defaults(fn=cmd_match)

    p = sub.add_parser("findall", help="all non-overlapping matches")
    p.add_argument("pattern")
    p.add_argument("text")
    p.set_defaults(fn=cmd_findall)

    p = sub.add_parser("trace", help="step-by-step VM trace in the terminal")
    p.add_argument("pattern")
    p.add_argument("text")
    p.add_argument("--mode", choices=["match", "search", "fullmatch"],
                   default="search")
    p.set_defaults(fn=cmd_trace)

    p = sub.add_parser("dfa", help="compile to a minimized DFA")
    p.add_argument("pattern")
    p.add_argument("--table", action="store_true",
                   help="print the transition table")
    p.add_argument("--text", help="also run fullmatch on this text")
    p.set_defaults(fn=cmd_dfa)

    p = sub.add_parser("viz", help="emit the interactive HTML visualizer")
    p.add_argument("pattern")
    p.add_argument("-o", "--out", default="regexlab.html")
    p.add_argument("--text", help="pre-filled test string "
                                  "(default: a generated match)")
    p.set_defaults(fn=cmd_viz)

    p = sub.add_parser("explain", help="plain-English pattern breakdown")
    p.add_argument("pattern")
    p.set_defaults(fn=cmd_explain)

    p = sub.add_parser("gen", help="generate random strings that match")
    p.add_argument("pattern")
    p.add_argument("-n", type=int, default=10, help="how many (default 10)")
    p.add_argument("--seed", type=int, help="RNG seed for reproducibility")
    p.add_argument("--repr", action="store_true",
                   help="print samples as Python literals")
    p.set_defaults(fn=cmd_gen)

    p = sub.add_parser("fuzz",
                       help="differential fuzz this engine vs Python's re")
    p.add_argument("-n", type=int, default=2000,
                   help="number of patterns (default 2000)")
    p.add_argument("--seed", type=int, help="RNG seed")
    p.set_defaults(fn=cmd_fuzz)

    args = ap.parse_args(argv)
    try:
        return args.fn(args) or 0
    except RegexError as e:
        print(f"error: {e}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
