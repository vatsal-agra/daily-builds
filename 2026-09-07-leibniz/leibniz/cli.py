"""The `leibniz` command-line interface."""

from __future__ import annotations

import argparse
import sys

from . import (
    CannotIntegrate, LinearSystemError, NotPolynomial, ParseError, SolveError,
    diff, evalf, expand, factor, free_symbols, integrate, parse, parse_equation,
    simplify, simplify_rational, solve, solve_linear_system, to_latex, to_str,
)
from .render import Steps


class CliError(Exception):
    pass


def _guess_var(e, explicit: str | None) -> str:
    if explicit:
        return explicit
    syms = sorted(free_symbols(e))
    if len(syms) == 1:
        return syms[0]
    if not syms:
        raise CliError("expression has no variable; pass --var explicitly")
    raise CliError(f"expression has multiple variables {syms}; pass --var explicitly")


def cmd_simplify(args):
    e = simplify(parse(args.expr))
    print(to_str(e))


def cmd_expand(args):
    e = expand(parse(args.expr))
    print(to_str(e))


def cmd_factor(args):
    e = factor(parse(args.expr))
    print(to_str(e))


def cmd_ratsimp(args):
    e = simplify_rational(parse(args.expr))
    print(to_str(e))


def cmd_diff(args):
    e = parse(args.expr)
    var = _guess_var(e, args.var)
    steps = Steps() if args.steps else None
    result = diff(e, var, steps=steps)
    if steps:
        for s in steps.entries:
            print(f"  {s['label']}: {s['expr']}")
    print(to_str(result))
    if args.viz:
        _write_viz(args.viz, "differentiate", args.expr, var, steps or _one_step(f"d/d{var}", result))


def cmd_integrate(args):
    e = parse(args.expr)
    var = _guess_var(e, args.var)
    steps = Steps() if args.steps else None
    try:
        result = integrate(e, var, steps=steps)
    except CannotIntegrate as ex:
        raise CliError(f"cannot integrate: {ex}") from ex
    print(f"{to_str(result)} + C")
    if args.viz:
        _write_viz(args.viz, "integrate", args.expr, var, steps or _one_step(f"integral d{var}", result))


def cmd_solve(args):
    lhs, rhs = parse_equation(args.equation)
    var = _guess_var(simplify(lhs - rhs), args.var)
    try:
        result = solve(lhs, rhs, var)
    except SolveError as ex:
        raise CliError(str(ex)) from ex

    if result.infinite:
        print(f"true for every value of {var}")
        return
    if result.no_solution:
        print("no solution")
        return
    for r in result.roots:
        print(f"{var} = {to_str(r)}")
    for r in result.numeric_roots:
        tag = "real" if r.imag == 0 else "complex"
        print(f"{var} ~= {r.real:.6g}" + (f" + {r.imag:.6g}i" if r.imag else "") + f"  ({tag}, numeric)")

    if args.viz:
        steps = Steps()
        steps.add("equation", simplify(lhs - rhs), note="= 0")
        for r in result.roots:
            steps.add(f"{var} =", r)
        _write_viz(args.viz, "solve", args.equation, var, steps)


def cmd_solve_system(args):
    names = args.vars.split(",")
    eqs = [parse_equation(e) for e in args.equations]
    try:
        result = solve_linear_system(eqs, names)
    except LinearSystemError as ex:
        raise CliError(str(ex)) from ex
    if result.inconsistent:
        print("no solution (inconsistent system)")
    elif result.infinite:
        print("infinitely many solutions (underdetermined system)")
    else:
        for name in names:
            print(f"{name} = {to_str(result.solution[name])}")


def cmd_eval(args):
    e = parse(args.expr)
    mapping = {}
    if args.at:
        for pair in args.at.split(","):
            k, v = pair.split("=")
            mapping[k.strip()] = float(v.strip())
    try:
        value = evalf(e, mapping)
    except Exception as ex:  # noqa: BLE001 - surfaced as a clean CLI error
        raise CliError(str(ex)) from ex
    print(value)


def cmd_repl(args):
    print("Leibniz CAS -- a from-scratch computer algebra system. Type 'help' or 'quit'.")
    while True:
        try:
            line = input("leibniz> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line:
            continue
        if line in ("quit", "exit"):
            break
        if line == "help":
            print(_REPL_HELP)
            continue
        try:
            _repl_eval(line)
        except (ParseError, NotPolynomial, SolveError, CannotIntegrate, LinearSystemError, CliError) as ex:
            print(f"error: {ex}")


_REPL_HELP = """\
Commands:
  <expr>              simplify and print an expression, e.g. 2*x + 3*x
  diff <expr>, <var>       symbolic derivative
  integrate <expr>, <var>  symbolic antiderivative
  solve <eqn>, <var>       solve an equation ("=" optional, defaults rhs=0)
  expand <expr>            fully distribute
  factor <expr>            factor a polynomial
  ratsimp <expr>           combine/cancel a rational function
  quit                     leave the REPL
"""


def _repl_eval(line: str):
    for prefix, handler in (
        ("diff ", lambda body: _repl_diff(body)),
        ("integrate ", lambda body: _repl_integrate(body)),
        ("solve ", lambda body: _repl_solve(body)),
        ("expand ", lambda body: print(to_str(expand(parse(body))))),
        ("factor ", lambda body: print(to_str(factor(parse(body))))),
        ("ratsimp ", lambda body: print(to_str(simplify_rational(parse(body))))),
    ):
        if line.startswith(prefix):
            handler(line[len(prefix):])
            return
    print(to_str(simplify(parse(line))))


def _split_expr_var(body: str):
    if "," in body:
        expr_s, var = body.rsplit(",", 1)
        return expr_s.strip(), var.strip()
    return body.strip(), None


def _repl_diff(body):
    expr_s, var = _split_expr_var(body)
    e = parse(expr_s)
    print(to_str(diff(e, _guess_var(e, var))))


def _repl_integrate(body):
    expr_s, var = _split_expr_var(body)
    e = parse(expr_s)
    print(f"{to_str(integrate(e, _guess_var(e, var)))} + C")


def _repl_solve(body):
    eqn_s, var = _split_expr_var(body)
    lhs, rhs = parse_equation(eqn_s)
    v = _guess_var(simplify(lhs - rhs), var)
    result = solve(lhs, rhs, v)
    if result.infinite:
        print(f"true for every value of {v}")
    elif result.no_solution:
        print("no solution")
    else:
        for r in result.roots:
            print(f"{v} = {to_str(r)}")
        for r in result.numeric_roots:
            print(f"{v} ~= {r} (numeric)")


def _one_step(label, expr) -> Steps:
    s = Steps()
    s.add(label, expr)
    return s


def _write_viz(path, op, expr_text, var, steps):
    from viz.generate_viz import build_html

    html = build_html(op=op, expr_text=expr_text, var=var, steps=steps.to_json())
    with open(path, "w") as f:
        f.write(html)
    print(f"wrote visualizer to {path}", file=sys.stderr)


def build_parser():
    p = argparse.ArgumentParser(prog="leibniz", description="A computer algebra system built from scratch.")
    sub = p.add_subparsers(dest="command", required=True)

    ps = sub.add_parser("simplify", help="canonicalize an expression")
    ps.add_argument("expr")
    ps.set_defaults(func=cmd_simplify)

    pe = sub.add_parser("expand", help="fully distribute an expression")
    pe.add_argument("expr")
    pe.set_defaults(func=cmd_expand)

    pf = sub.add_parser("factor", help="factor a univariate polynomial")
    pf.add_argument("expr")
    pf.set_defaults(func=cmd_factor)

    prs = sub.add_parser("ratsimp", help="combine/cancel a rational function (e.g. (x^2-1)/(x-1) -> x+1)")
    prs.add_argument("expr")
    prs.set_defaults(func=cmd_ratsimp)

    pd = sub.add_parser("diff", help="symbolic derivative")
    pd.add_argument("expr")
    pd.add_argument("--var")
    pd.add_argument("--steps", action="store_true", help="print intermediate steps")
    pd.add_argument("--viz", help="write an HTML step visualizer to this path")
    pd.set_defaults(func=cmd_diff)

    pi = sub.add_parser("integrate", help="symbolic antiderivative")
    pi.add_argument("expr")
    pi.add_argument("--var")
    pi.add_argument("--steps", action="store_true")
    pi.add_argument("--viz", help="write an HTML step visualizer to this path")
    pi.set_defaults(func=cmd_integrate)

    po = sub.add_parser("solve", help="solve an equation exactly")
    po.add_argument("equation")
    po.add_argument("--var")
    po.add_argument("--viz", help="write an HTML step visualizer to this path")
    po.set_defaults(func=cmd_solve)

    pls = sub.add_parser("solve-system", help="solve a linear system exactly")
    pls.add_argument("equations", nargs="+")
    pls.add_argument("--vars", required=True, help="comma-separated variable names")
    pls.set_defaults(func=cmd_solve_system)

    pv = sub.add_parser("eval", help="numerically evaluate an expression")
    pv.add_argument("expr")
    pv.add_argument("--at", help="comma-separated var=value bindings, e.g. x=2,y=3")
    pv.set_defaults(func=cmd_eval)

    pr = sub.add_parser("repl", help="interactive REPL")
    pr.set_defaults(func=cmd_repl)

    return p


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)
    try:
        args.func(args)
    except (ParseError, NotPolynomial, SolveError, CannotIntegrate, LinearSystemError, CliError, ZeroDivisionError) as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
