"""Command line interface: python -m delve <command> ..."""
import argparse
import json
import sys
from . import terms as tm
from .interp import Interp
from .lang import DelveError, parse
from .symex import Explorer
from .report import text_report, html_report, fmt_inputs


def load(path):
    try:
        with open(path) as f: src = f.read()
    except OSError as e:
        raise DelveError("cannot read %s: %s" % (path, e.strerror))
    return parse(src)


def add_common(p):
    p.add_argument("--width", type=int, default=8, help="integer width in bits (default 8, max 32)")


def check_width(w):
    if not 2 <= w <= 32:
        raise DelveError("--width must be between 2 and 32")


def cmd_run(a):
    check_width(a.width)
    prog = load(a.file)
    inputs = {}
    for kv in a.input or []:
        if "=" not in kv: raise DelveError("--input expects name=value, got %r" % kv)
        k, v = kv.split("=", 1)
        try: inputs[k] = int(v, 0) & tm.mask(a.width)
        except ValueError: raise DelveError("bad integer %r for input %s" % (v, k))
    r = Interp(prog, a.width).run(inputs)
    unknown = sorted(set(inputs) - set(r.input_names))
    if unknown:
        print("warning: unknown input name(s) %s; this run reads: %s" % (
            ", ".join(unknown), ", ".join(r.input_names) or "(none)"), file=sys.stderr)
    for o in r.outputs: print(o)
    if r.infeasible: print("(execution violated an assume() or input range)"); return 3
    if r.exhausted: print("(step budget exhausted — possible infinite loop)"); return 3
    if r.trap: print("TRAP: %s at line %d" % r.trap); return 1
    if r.value is not None: print("returned", tm.to_signed(r.value, a.width))
    return 0


def cmd_analyze(a):
    check_width(a.width)
    prog = load(a.file)
    ex = Explorer(prog, a.width, loop_bound=a.loop_bound, max_paths=a.max_paths, timeout=a.timeout,
                  check_overflow=not a.no_overflow, minimize=not a.no_minimize, max_depth=a.call_depth,
                  solver_budget=a.solver_budget)
    ex.explore()
    ok = ex.verify()
    print(text_report(ex, a.file, show_paths=not a.quiet))
    if a.tests:
        tests = []
        for p in ex.paths:
            t = {"path": p.id, "inputs": {n: tm.to_signed(p.inputs[n], a.width) for n in p.in_names}}
            if p.status == "error": t["expect"] = {"trap": p.trap[0], "line": p.trap[1]}
            else: t["expect"] = {"return": p.expected_ret, "prints": p.expected_out}
            tests.append(t)
        with open(a.tests, "w") as f: json.dump({"program": a.file, "width": a.width, "tests": tests}, f, indent=2)
        print("\nwrote %d tests to %s" % (len(tests), a.tests))
    if a.html:
        with open(a.html, "w") as f: f.write(html_report(ex, a.file))
        print("wrote HTML report to %s" % a.html)
    if not ok:
        print("\nINTERNAL ERROR: a generated test did not replay concretely", file=sys.stderr)
        return 2
    return 1 if ex.bugs else 0


def cmd_replay(a):
    """Run a tests JSON (from analyze --tests) against a program on the concrete interpreter."""
    with open(a.tests) as f: spec = json.load(f)
    prog = load(a.file)
    w = spec["width"]
    it = Interp(prog, w)
    bad = 0
    for t in spec["tests"]:
        r = it.run({k: v & tm.mask(w) for k, v in t["inputs"].items()})
        e = t["expect"]
        if "trap" in e: good = r.trap == (e["trap"], e["line"])
        else: good = (r.trap is None and (r.value is None or tm.to_signed(r.value, w) == e["return"]) and r.outputs == e["prints"])
        print("%s test %d" % ("PASS" if good else "FAIL", t["path"]))
        bad += not good
    print("%d/%d passed" % (len(spec["tests"]) - bad, len(spec["tests"])))
    return 1 if bad else 0


def run_big_stack(fn, arg):
    """Run in a thread with a large stack so deeply nested programs do not crash the interpreter."""
    import threading
    out = {}
    threading.stack_size(512 * 1024 * 1024)
    sys.setrecursionlimit(200000)

    def target():
        try: out["v"] = fn(arg)
        except BaseException as e: out["e"] = e
    t = threading.Thread(target=target)
    t.start(); t.join()
    if "e" in out: raise out["e"]
    return out["v"]


def main(argv=None):
    ap = argparse.ArgumentParser(prog="delve", description="Symbolic execution with a from-scratch bit-vector SMT solver")
    sub = ap.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="execute a program concretely"); r.add_argument("file")
    r.add_argument("-i", "--input", action="append", metavar="NAME=VALUE"); add_common(r); r.set_defaults(fn=cmd_run)
    an = sub.add_parser("analyze", help="symbolically execute: find bugs, generate tests")
    an.add_argument("file"); add_common(an)
    an.add_argument("--loop-bound", type=int, default=8); an.add_argument("--call-depth", type=int, default=24)
    an.add_argument("--max-paths", type=int, default=2000); an.add_argument("--timeout", type=float, default=60.0)
    an.add_argument("--solver-budget", type=int, default=100000, help="SAT conflicts allowed per query")
    an.add_argument("--no-overflow", action="store_true", help="do not treat signed overflow as a bug")
    an.add_argument("--no-minimize", action="store_true", help="skip input minimization (faster)")
    an.add_argument("--tests", metavar="FILE.json"); an.add_argument("--html", metavar="FILE.html")
    an.add_argument("-q", "--quiet", action="store_true", help="omit the per-path table"); an.set_defaults(fn=cmd_analyze)
    rp = sub.add_parser("replay", help="replay a generated tests file concretely")
    rp.add_argument("file"); rp.add_argument("tests"); rp.set_defaults(fn=cmd_replay)
    from . import extras
    extras.register(sub, add_common)
    a = ap.parse_args(argv)
    try:
        return run_big_stack(a.fn, a)
    except DelveError as e:
        print("error: %s" % e, file=sys.stderr)
        return 64
    except RecursionError:
        print("error: program too deeply nested", file=sys.stderr)
        return 64


if __name__ == "__main__":
    sys.exit(main())
