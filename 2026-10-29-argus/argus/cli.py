"""Command-line interface:  python -m argus <command> ..."""
import argparse
import glob
import json
import os
import random
import re
import sys
import time

from .lang import ArgusError, parse_ltl_text
from .live import check_ltl
from .ltl import fmt_core, nnf, to_buchi
from .model import StepError, build, state_str, successors, is_end
from .safety import check_safety
from .trace import STUTTER, Trace, ValidationError, Violation, render, to_json, trace_from_json, validate


def load(path, defines):
    try:
        with open(path) as f:
            src = f.read()
    except OSError as ex:
        raise ArgusError(f"cannot read {path}: {ex.strerror}")
    d = {}
    for item in defines or []:
        if "=" not in item:
            raise ArgusError(f"-D expects NAME=VALUE, got '{item}'")
        k, v = item.split("=", 1)
        try:
            d[k] = int(v)
        except ValueError:
            raise ArgusError(f"-D {k}: '{v}' is not an integer")
    try:
        return build(src, d, path)
    except ArgusError as ex:
        if ex.src is None:
            ex.src = src
        raise


def n(x):
    return f"{x:,}"


def run_validation(m, v, args, out):
    if args.no_validate:
        return True
    try:
        facts = validate(m, v, getattr(v, "fairness", args.fair), getattr(v, "granularity", args.fair_by))
    except ValidationError as ex:
        out(f"  ✗ INTERNAL ERROR: counterexample failed independent replay: {ex}")
        return False
    out("  independent replay ✓ " + facts[0])
    for f in facts[1:]:
        out("                    ✓ " + f)
    return True


def cmd_check(args):
    m = load(args.model, args.D)
    say = print
    if args.json:
        say = lambda *a, **k: None
    report = {"model": args.model, "properties": []}
    say(f"model {os.path.basename(args.model)}: {m.nproc} process(es), {len(m.edges)} statements, "
        f"{len(m.init)}-slot state vector, {len(m.invariants)} invariant(s), {len(m.ltls)} ltl propert{'y' if len(m.ltls) == 1 else 'ies'}")
    status = 0
    wanted = set(args.prop or [])
    names = {x.name for x in m.invariants} | {x.name for x in m.ltls}
    for w in wanted:
        if w not in names and w not in ("safety",):
            raise ArgusError(f"no property named '{w}' (have: {', '.join(sorted(names)) or 'none'})")

    run_safety = not args.no_safety and (not wanted or "safety" in wanted or any(i.name in wanted for i in m.invariants))
    if run_safety:
        sel = m.invariants
        if wanted and "safety" not in wanted:
            m_inv = [i for i in m.invariants if i.name in wanted]
            m.invariants = m_inv
        res = check_safety(m, args.max_states, args.all, args.por)
        m.invariants = sel
        label = "safety (assertions, deadlock, runtime errors" + (", " + ", ".join(i.name for i in sel) if sel else "") + ")"
        stats = f"{n(res.states)} states, {n(res.transitions)} transitions, depth {res.depth}, {res.seconds:.2f}s"
        if args.por:
            stats += f", POR reduced {n(res.por_reduced)} states"
        entry = {"property": "safety", "ok": res.ok, "states": res.states, "transitions": res.transitions,
                 "depth": res.depth, "seconds": round(res.seconds, 3), "limited": res.limited, "violations": []}
        if res.violations:
            status = max(status, 1)
            say(f"✗ {label}: VIOLATED — {stats}")
            for v in res.violations:
                say("")
                say(render(m, v, args.model))
                if not run_validation(m, v, args, say):
                    status = 2
                entry["violations"].append(to_json(m, v))
                say("")
        elif res.limited:
            status = max(status, 3)
            say(f"? {label}: INCONCLUSIVE — state limit {n(args.max_states)} reached ({stats})")
        else:
            say(f"✓ {label}: holds — {stats}")
        report["properties"].append(entry)

    if not args.no_ltl:
        for spec in m.ltls:
            if wanted and spec.name not in wanted:
                continue
            res = check_ltl(m, spec, args.fair, args.fair_by, args.max_states)
            fair = f"{args.fair} fairness" + (f" per {'process' if args.fair_by == 'proc' else 'statement'}" if args.fair != "none" else "")
            stats = (f"product {n(res.product_states)} states / {n(res.product_edges)} edges, Büchi(¬φ) "
                     f"{res.buchi_states} states {res.acc_sets} acc-set(s), {fair}, {res.seconds:.2f}s")
            entry = {"property": spec.name, "ok": res.ok, "product_states": res.product_states,
                     "seconds": round(res.seconds, 3), "fairness": args.fair, "violations": []}
            if res.error is not None:
                status = max(status, 1)
                say(f"✗ ltl {spec.name}: cannot be checked — a safety error is reachable (run without --prop to see it)")
                say("")
                say(render(m, res.error, args.model))
                entry["violations"].append(to_json(m, res.error))
            elif res.violation is not None:
                status = max(status, 1)
                say(f"✗ ltl {spec.name}: VIOLATED — {stats}")
                say("")
                say(render(m, res.violation, args.model))
                if not run_validation(m, res.violation, args, say):
                    status = 2
                entry["violations"].append(to_json(m, res.violation))
                say("")
            elif res.limited:
                status = max(status, 3)
                say(f"? ltl {spec.name}: INCONCLUSIVE — state limit reached ({stats})")
            else:
                say(f"✓ ltl {spec.name}: holds — {stats}")
            report["properties"].append(entry)
    if args.json:
        print(json.dumps(report, indent=2))
    if args.save_trace and any(p["violations"] for p in report["properties"]):
        first = next(v for p in report["properties"] for v in p["violations"])
        with open(args.save_trace, "w") as f:
            json.dump(first, f, indent=1)
        say(f"saved first counterexample to {args.save_trace}")
    return status


def cmd_info(args):
    m = load(args.model, args.D)
    print(f"{args.model}")
    print(f"  constants : " + (", ".join(f"{k}={v}" for k, v in m.consts.items()) or "-"))
    print(f"  variables : " + (", ".join(f"{k}{'[' + str(v.size) + ']' if v.size else ''}" for k, v in m.vars.items()) or "-"))
    print(f"  channels  : " + (", ".join(f"{k}[{c.cap}] of {c.arity}" for k, c in m.chans.items()) or "-"))
    for p in m.procs:
        local = sum(e.local for node in p.out for e in node)
        total = sum(len(node) for node in p.out)
        labs = ", ".join(p.labels) or "-"
        print(f"  process {p.name:<8} {len(p.out)} locations, {total} statements ({local} process-local), labels: {labs}")
    print(f"  invariants: " + (", ".join(f"{i.name}: {i.text}" for i in m.invariants) or "-"))
    print(f"  ltl       : " + (", ".join(i.name for i in m.ltls) or "-"))
    print(f"  initial   : {state_str(m, m.init)}")
    return 0


def cmd_sim(args):
    m = load(args.model, args.D)
    rng = random.Random(args.seed)
    s = m.init
    steps = []
    print(f"simulation seed={args.seed}")
    print(f"  0  init  {state_str(m, s)}")
    prev = s
    for i in range(1, args.steps + 1):
        try:
            succ = successors(m, s)
        except StepError as ex:
            print(f"  {i}  {m.procs[ex.pid].name} {ex.edge.text} (line {ex.edge.line})  ✗ {ex.msg}")
            return 1
        if not succ:
            print(("  -- terminated: all processes at end states" if is_end(m, s)
                   else "  -- DEADLOCK: no process can move"))
            return 0 if is_end(m, s) else 1
        if args.interactive:
            for j, (pid, e, t) in enumerate(succ):
                print(f"     [{j}] {m.procs[pid].name:<6} {e.text}  (line {e.line})")
            try:
                raw = input("choose> ").strip()
            except EOFError:
                return 0
            if raw in ("q", "quit"):
                return 0
            pick = succ[int(raw)] if raw.isdigit() and int(raw) < len(succ) else rng.choice(succ)
        else:
            pick = rng.choice(succ)
        pid, e, t = pick
        steps.append(pick)
        from .model import diff_str
        ch = [c for c in diff_str(m, s, t) if not c.split(":")[0].endswith(".pc")]
        print(f"  {i:<2} {m.procs[pid].name:<6} {e.text}  (line {e.line})" + (f"   ↳ {'; '.join(ch)}" if ch else ""))
        s = t
    print(f"  final {state_str(m, s)}")
    if args.save:
        v = Violation("simulation", "sim", "", Trace(m.init, steps))
        d = {"kind": "simulation", "name": "sim", "message": "", "init": list(m.init) and to_json(m, Violation("invariant", "x", "", Trace(m.init, steps)))["init"],
             "steps": to_json(m, Violation("invariant", "x", "", Trace(m.init, steps)))["steps"], "loop_to": None}
        with open(args.save, "w") as f:
            json.dump(d, f, indent=1)
    return 0


def cmd_replay(args):
    m = load(args.model, args.D)
    with open(args.trace) as f:
        d = json.load(f)
    v = trace_from_json(m, d)
    try:
        if v.kind == "simulation":
            v.kind = "none"
        facts = validate(m, v, args.fair, args.fair_by)
    except ValidationError as ex:
        print(f"✗ trace is NOT valid: {ex}")
        return 1
    print(render(m, v, args.model) if v.kind != "none" else "")
    for fct in facts:
        print("✓", fct)
    return 0


def cmd_buchi(args):
    f = parse_ltl_text(args.formula)
    names, index = [], {}
    from .lang import fmt

    def conv(g):
        if g[0] == "atom":
            t = fmt(g[1])
            if t not in index:
                index[t] = len(names)
                names.append(t)
            return ("ap", index[t])
        if g[0] in ("true", "false"):
            return g
        return (g[0],) + tuple(conv(x) for x in g[1:])

    surf = conv(f)
    core = nnf(surf, not args.negate)
    from .ltl import gpvw
    aut = gpvw(core)
    print(aut.to_dot(names) if args.dot else aut.to_text(names))
    return 0


def cmd_graph(args):
    m = load(args.model, args.D)
    ids, order, edges = {m.init: 0}, [m.init], []
    i = 0
    while i < len(order) and len(order) < args.max:
        s = order[i]
        try:
            succ = successors(m, s)
        except StepError:
            succ = []
        for pid, e, t in succ:
            if t not in ids:
                if len(order) >= args.max:
                    continue
                ids[t] = len(order)
                order.append(t)
            edges.append((ids[s], ids[t], m.procs[pid].name, e.text))
        i += 1
    print("digraph states {\n  rankdir=TB; node [shape=box fontname=Helvetica fontsize=9];")
    for s, k in ids.items():
        succ_ok = True
        label = state_str(m, s).replace('"', "'").replace("|", "\\n")
        style = ' style=filled fillcolor="#ffd6d6"' if (not edges or all(e[0] != k for e in edges)) and not is_end(m, s) and k < len(order) else ""
        print(f'  s{k} [label="{label}"{style}];')
    for a, b, p, t in edges:
        print(f'  s{a} -> s{b} [label="{p}: {t}" fontsize=8];')
    print("}")
    return 0


EXPECT_RE = re.compile(r"//\s*expect:\s*(.*)")


def cmd_verify(args):
    files = []
    for p in args.paths:
        files.extend(sorted(glob.glob(os.path.join(p, "*.arg"))) if os.path.isdir(p) else [p])
    bad = 0
    total = 0
    t0 = time.time()
    for path in files:
        src = open(path).read()
        exps = [EXPECT_RE.match(l.strip()).group(1).split() for l in src.splitlines() if EXPECT_RE.match(l.strip())]
        if not exps:
            continue
        for toks in exps:
            what, verdict, opts = toks[0], toks[1], dict(t.split("=", 1) for t in toks[2:] if "=" in t)
            fair = opts.get("fair", "weak")
            by = opts.get("by", "proc")
            defs = dict(kv.split(":") for kv in opts["D"].split(",")) if "D" in opts else {}
            m = build(src, {k: int(v) for k, v in defs.items()}, path)
            total += 1
            kind = None
            if what == "safety":
                r = check_safety(m, args.max_states, False, opts.get("por") == "1")
                ok = r.ok
                kind = r.violations[0].kind if r.violations else ("limit" if r.limited else None)
            else:
                spec = next((s for s in m.ltls if s.name == what), None)
                if spec is None:
                    print(f"✗ {path}: no ltl property {what}")
                    bad += 1
                    continue
                r = check_ltl(m, spec, fair, by, args.max_states)
                ok = r.ok
                v = r.violation or r.error
                kind = v.kind if v else ("limit" if r.limited else None)
                if v is not None:
                    try:
                        validate(m, v, fair, by)
                    except ValidationError as ex:
                        print(f"✗ {path} {what}: counterexample failed replay: {ex}")
                        bad += 1
                        continue
            if what == "safety" and r.violations:
                for v in r.violations:
                    try:
                        validate(m, v)
                    except ValidationError as ex:
                        print(f"✗ {path} {what}: counterexample failed replay: {ex}")
                        bad += 1
            want_ok = verdict == "pass"
            extra = opts.get("kind")
            good = (ok == want_ok) and (want_ok or extra is None or extra == kind)
            mark = "✓" if good else "✗"
            bad += not good
            detail = f"{'holds' if ok else 'violated (' + str(kind) + ')'}"
            print(f"{mark} {os.path.basename(path):<28} {what:<14} expect {verdict:<4} → {detail}")
    print(f"\n{total - bad}/{total} expectations met in {time.time() - t0:.1f}s")
    return 1 if bad else 0


def main(argv=None):
    ap = argparse.ArgumentParser(prog="argus", description="Explicit-state model checker for concurrent systems")
    sub = ap.add_subparsers(dest="cmd", required=True)

    def common(p, model=True):
        if model:
            p.add_argument("model")
        p.add_argument("-D", action="append", metavar="NAME=VALUE", help="override a const")
        p.add_argument("--fair", choices=["none", "weak", "strong"], default="weak",
                       help="fairness assumption for liveness (default weak)")
        p.add_argument("--fair-by", choices=["proc", "edge"], default="proc",
                       help="fairness classes: whole processes or individual statements")

    p = sub.add_parser("check", help="verify invariants, assertions, deadlock-freedom and LTL properties")
    common(p)
    p.add_argument("--prop", action="append", help="only check this property (or 'safety'); repeatable")
    p.add_argument("--no-safety", action="store_true")
    p.add_argument("--no-ltl", action="store_true")
    p.add_argument("--por", action="store_true", help="partial-order reduction (safety only)")
    p.add_argument("--all", action="store_true", help="report every distinct safety violation, not just the first")
    p.add_argument("--max-states", type=int, default=1_500_000)
    p.add_argument("--json", action="store_true")
    p.add_argument("--no-validate", action="store_true", help="skip the independent counterexample replay")
    p.add_argument("--save-trace", metavar="FILE")
    p.set_defaults(fn=cmd_check)

    p = sub.add_parser("info", help="summarise a model")
    common(p)
    p.set_defaults(fn=cmd_info)

    p = sub.add_parser("sim", help="random or interactive simulation")
    common(p)
    p.add_argument("--steps", type=int, default=30)
    p.add_argument("--seed", type=int, default=1)
    p.add_argument("--interactive", action="store_true")
    p.add_argument("--save", metavar="FILE")
    p.set_defaults(fn=cmd_sim)

    p = sub.add_parser("replay", help="independently validate a saved trace")
    common(p)
    p.add_argument("trace")
    p.set_defaults(fn=cmd_replay)

    p = sub.add_parser("buchi", help="show the Büchi automaton for an LTL formula")
    p.add_argument("formula")
    p.add_argument("--negate", action="store_true", help="automaton for the negation (what the checker uses)")
    p.add_argument("--dot", action="store_true")
    p.set_defaults(fn=cmd_buchi)

    p = sub.add_parser("graph", help="Graphviz export of the reachable state graph")
    common(p)
    p.add_argument("--max", type=int, default=200)
    p.set_defaults(fn=cmd_graph)

    p = sub.add_parser("verify", help="run the `// expect:` annotations in model files")
    p.add_argument("paths", nargs="+")
    p.add_argument("--max-states", type=int, default=1_500_000)
    p.set_defaults(fn=cmd_verify)

    args = ap.parse_args(argv)
    try:
        return args.fn(args)
    except ArgusError as ex:
        print(f"error: {ex}", file=sys.stderr)
        return 2
    except BrokenPipeError:
        return 0


if __name__ == "__main__":
    sys.exit(main())
