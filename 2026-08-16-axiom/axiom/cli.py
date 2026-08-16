"""`axiom` command-line tool."""

import argparse
import sys

from .errors import AxiomError
from .expr import symbols
from .parser import parse


def _var(name, *exprs):
    if name:
        return parse(name)
    fs = set()
    for e in exprs:
        fs |= e.free_symbols()
    if len(fs) == 1:
        return next(iter(fs))
    if len(fs) == 0:
        return symbols("x")[0]
    raise AxiomError(
        f"expression has multiple symbols {sorted(s.name for s in fs)} — pass --var explicitly")


def cmd_simplify(args):
    from .simplify import simplify
    e = parse(args.expr)
    trace = [] if args.steps else None
    result = simplify(e, trace=trace)
    if trace:
        for step in trace:
            print(" ", step)
    print(result)


def cmd_diff(args):
    from .calculus import differentiate
    e = parse(args.expr)
    var = _var(args.var, e)
    trace = [] if args.steps else None
    result = differentiate(e, var, trace=trace)
    if trace:
        for step in trace:
            print(" ", step)
    print(result)


def cmd_integrate(args):
    from .calculus import integrate
    e = parse(args.expr)
    var = _var(args.var, e)
    result = integrate(e, var)
    print(f"{result} + C")


def cmd_solve(args):
    from .solve import solve
    var = parse(args.var) if args.var else None
    if "=" in args.equation:
        lhs_s, rhs_s = args.equation.split("=", 1)
        lhs, rhs = parse(lhs_s), parse(rhs_s)
        if var is None:
            var = _var(None, lhs, rhs)
        roots = solve((lhs, rhs), var)
    else:
        e = parse(args.equation)
        if var is None:
            var = _var(None, e)
        roots = solve(e, var)
    for r in roots:
        print(r)


def cmd_expand(args):
    from .polynomial import expand
    print(expand(parse(args.expr)))


def cmd_factor(args):
    from .polynomial import factor
    var = parse(args.var) if args.var else None
    print(factor(parse(args.expr), var))


def cmd_latex(args):
    print(parse(args.expr).latex())


def cmd_eval(args):
    e = parse(args.expr)
    bindings = {}
    for kv in args.bind or []:
        k, v = kv.split("=", 1)
        bindings[k] = float(v)
    result = e.evalf(bindings)
    if abs(result.imag) < 1e-12:
        print(result.real)
    else:
        print(result)


def cmd_repl(args):
    from .calculus import differentiate, integrate
    from .simplify import simplify
    from .solve import solve
    print("Axiom REPL — type a math expression, or one of:")
    print("  diff <expr> [wrt var]   |  integrate <expr> [wrt var]")
    print("  solve <eq> [for var]    |  factor <expr>  |  expand <expr>")
    print("  quit")
    while True:
        try:
            line = input("axiom> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("quit", "exit"):
            break
        try:
            if line.startswith("diff "):
                rest = line[5:]
                expr_s, _, var_s = rest.partition(" wrt ")
                e = parse(expr_s)
                var = parse(var_s) if var_s else _var(None, e)
                print(differentiate(e, var))
            elif line.startswith("integrate "):
                rest = line[10:]
                expr_s, _, var_s = rest.partition(" wrt ")
                e = parse(expr_s)
                var = parse(var_s) if var_s else _var(None, e)
                print(f"{integrate(e, var)} + C")
            elif line.startswith("solve "):
                rest = line[6:]
                eq_s, _, var_s = rest.partition(" for ")
                var = parse(var_s) if var_s else None
                if "=" in eq_s:
                    lhs_s, rhs_s = eq_s.split("=", 1)
                    lhs, rhs = parse(lhs_s), parse(rhs_s)
                    var = var or _var(None, lhs, rhs)
                    for r in solve((lhs, rhs), var):
                        print(r)
                else:
                    e = parse(eq_s)
                    var = var or _var(None, e)
                    for r in solve(e, var):
                        print(r)
            elif line.startswith("factor "):
                from .polynomial import factor
                print(factor(parse(line[7:])))
            elif line.startswith("expand "):
                from .polynomial import expand
                print(expand(parse(line[7:])))
            else:
                print(simplify(parse(line)))
        except AxiomError as ex:
            print(f"error: {ex}")


def cmd_viz(args):
    from .report import generate_report
    e = parse(args.expr)
    var = _var(args.var, e)
    path = generate_report(e, var, args.out)
    print(f"wrote {path}")


def cmd_demo(args):
    from .demo import run_demo
    run_demo()


def cmd_serve(args):
    from .report import run_playground_server
    run_playground_server(args.port)


def build_parser():
    p = argparse.ArgumentParser(prog="axiom", description="A from-scratch computer algebra system.")
    sub = p.add_subparsers(dest="command", required=True)

    ps = sub.add_parser("simplify", help="simplify an expression")
    ps.add_argument("expr")
    ps.add_argument("--steps", action="store_true", help="show a step-by-step trace")
    ps.set_defaults(func=cmd_simplify)

    pd = sub.add_parser("diff", help="symbolically differentiate")
    pd.add_argument("expr")
    pd.add_argument("--var", default=None)
    pd.add_argument("--steps", action="store_true", help="show a step-by-step trace")
    pd.set_defaults(func=cmd_diff)

    pi = sub.add_parser("integrate", help="symbolically integrate")
    pi.add_argument("expr")
    pi.add_argument("--var", default=None)
    pi.set_defaults(func=cmd_integrate)

    pso = sub.add_parser("solve", help="solve an equation")
    pso.add_argument("equation", help='e.g. "x^2 - 4" or "x^2 = 4"')
    pso.add_argument("--var", default=None)
    pso.set_defaults(func=cmd_solve)

    pe = sub.add_parser("expand", help="fully distribute an expression")
    pe.add_argument("expr")
    pe.set_defaults(func=cmd_expand)

    pf = sub.add_parser("factor", help="factor a polynomial")
    pf.add_argument("expr")
    pf.add_argument("--var", default=None)
    pf.set_defaults(func=cmd_factor)

    pl = sub.add_parser("latex", help="render an expression as LaTeX")
    pl.add_argument("expr")
    pl.set_defaults(func=cmd_latex)

    pev = sub.add_parser("eval", help="numerically evaluate an expression")
    pev.add_argument("expr")
    pev.add_argument("--bind", action="append", help='e.g. --bind x=3.0 --bind y=1.0')
    pev.set_defaults(func=cmd_eval)

    pr = sub.add_parser("repl", help="interactive REPL")
    pr.set_defaults(func=cmd_repl)

    pv = sub.add_parser("viz", help="generate the interactive HTML report")
    pv.add_argument("expr")
    pv.add_argument("--var", default=None)
    pv.add_argument("--out", default="axiom_report.html")
    pv.set_defaults(func=cmd_viz)

    pdm = sub.add_parser("demo", help="run the full feature walkthrough")
    pdm.set_defaults(func=cmd_demo)

    psv = sub.add_parser("serve", help="run the live interactive playground (real backend)")
    psv.add_argument("--port", type=int, default=8765)
    psv.set_defaults(func=cmd_serve)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except AxiomError as ex:
        print(f"error: {ex}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
