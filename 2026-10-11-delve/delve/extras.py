"""Stretch commands built on the core: program equivalence checking and a raw
bit-vector formula solver."""
import re
from . import terms as tm
from .bitblast import Smt, Unknown
from .interp import Interp
from .lang import DelveError, KEYWORDS, Parser, parse, check_literals
from .symex import Explorer, State
from .report import fmt_inputs


# ------------------------------------------------------------------ equiv
def _outcome(p, w):
    """Observable behaviour of a path: (kind, return-term-or-None, output terms)."""
    if p.status == "error":
        return ("trap:" + p.trap[0], None, [])
    return ("ok", p.ret, list(p.outputs))


def _diff_cond(pa, pb, w):
    """Boolean term true exactly when the two paths' observable behaviour differs
    (given both path conditions hold)."""
    ka, ra, oa = _outcome(pa, w)
    kb, rb, ob = _outcome(pb, w)
    if ka != kb: return tm.TRUE
    if ka != "ok": return tm.FALSE
    if (ra is None) != (rb is None): return tm.TRUE
    if len(oa) != len(ob): return tm.TRUE
    d = tm.FALSE
    if ra is not None: d = tm.lor(d, tm.lnot(tm.eq(ra, rb)))
    for x, y in zip(oa, ob): d = tm.lor(d, tm.lnot(tm.eq(x, y)))
    return d


class EquivResult:
    def __init__(self):
        self.equivalent = True
        self.complete = True
        self.cex = None            # dict with inputs, a_result, b_result
        self.pairs = self.checked = 0
        self.notes = []


def describe(res, w):
    if res.trap: return "TRAP: %s (line %d)" % res.trap
    if res.infeasible: return "(assume violated)"
    if res.exhausted: return "(did not terminate)"
    v = "returned %d" % tm.to_signed(res.value, w) if res.value is not None else "finished"
    return v + (", printed %s" % res.outputs if res.outputs else "")


def check_equiv(pa, pb, width=8, loop_bound=8, solver_budget=100000, check_overflow=True, **kw):
    smt = Smt(solver_budget)
    ea = Explorer(pa, width, loop_bound=loop_bound, smt=smt, check_overflow=check_overflow, **kw).explore()
    eb = Explorer(pb, width, loop_bound=loop_bound, smt=smt, check_overflow=check_overflow, **kw).explore()
    res = EquivResult()
    res.ea, res.eb = ea, eb
    if not (ea.paths and eb.paths):
        res.notes.append("one program has no feasible execution")
    res.complete = not (ea.truncated or eb.truncated or ea.hit_limit or eb.hit_limit or ea.unknown or eb.unknown)
    if not res.complete:
        res.notes.append("exploration incomplete (loop/call bound, limits or solver budget): equivalence is only established for the explored paths")
    ia, ib = set(), set()
    for p in ea.paths: ia.update(p.in_names)
    for p in eb.paths: ib.update(p.in_names)
    if ia != ib:
        res.notes.append("input names differ (A: %s, B: %s); inputs are matched by name, unmatched ones are free in one program only"
                         % (sorted(ia), sorted(ib)))
    for p in ea.paths:
        for q in eb.paths:
            res.pairs += 1
            d = _diff_cond(p, q, width)
            if d is tm.FALSE: continue
            conds = p.pc + q.pc + [d]
            try:
                ok, _ = smt.check(conds, want_model=False)
            except Unknown:
                res.complete = False
                res.notes.append("solver budget exceeded on a path pair")
                continue
            res.checked += 1
            if not ok: continue
            names = sorted(set(p.in_names) | set(q.in_names))
            m = smt.minimize(conds, names) or {}
            inputs = {n: m.get(n, 0) for n in names}
            ra = Interp(pa, width).run(inputs)
            rb = Interp(pb, width).run(inputs)
            res.equivalent = False
            res.cex = {"inputs": inputs, "names": names, "a": ra, "b": rb,
                       "confirmed": _really_differ(ra, rb)}
            return res
    return res


def _really_differ(ra, rb):
    ka = ra.trap[0] if ra.trap else None
    kb = rb.trap[0] if rb.trap else None
    return (ka, ra.value, ra.outputs) != (kb, rb.value, rb.outputs)


def cmd_equiv(a):
    from .cli import load, check_width
    check_width(a.width)
    pa, pb = load(a.a), load(a.b)
    r = check_equiv(pa, pb, a.width, loop_bound=a.loop_bound, solver_budget=a.solver_budget,
                    check_overflow=not a.no_overflow)
    w = a.width
    print("Delve equivalence check   A=%s   B=%s   (width=%d, loop bound=%d)" % (a.a, a.b, w, a.loop_bound))
    print("paths: A has %d, B has %d; %d path pairs, %d needed a solver query" % (len(r.ea.paths), len(r.eb.paths), r.pairs, r.checked))
    for n in r.notes: print("note:", n)
    if r.equivalent:
        if r.complete:
            print("EQUIVALENT: the programs behave identically (result, prints, traps) for every input.")
        else:
            print("EQUIVALENT within the explored paths (not a full proof).")
        return 0
    c = r.cex
    print("NOT EQUIVALENT. Distinguishing input: %s" % fmt_inputs(c["inputs"], c["names"], w))
    print("  A: " + describe(c["a"], w))
    print("  B: " + describe(c["b"], w))
    print("  (replay on the concrete interpreter %s)" % ("confirms the difference" if c["confirmed"] else "DISAGREES — internal error"))
    return 1


# ------------------------------------------------------------------ solve
def solve_formula(text, width=8, prove=False, count=1, budget=100000):
    """Returns ('sat'|'unsat'|'valid'|'invalid'|'unknown', [models], names)."""
    if len(text) > 10000: raise DelveError("formula too long")
    names = []
    for m in re.finditer(r"[A-Za-z_]\w*", text):
        n = m.group(0)
        if n not in KEYWORDS and n not in names and not re.match(r"0[xXbB]", text[m.start():m.start() + 2]) and not (
                m.start() > 0 and (text[m.start() - 1].isdigit())):
            names.append(n)
    p = Parser(text)
    p.scopes = [{n: n for n in names}]
    e = p.expr()
    if p.peek()[0] != "eof": raise DelveError("unexpected %r after formula" % (p.peek()[1],))
    if p.pending: raise DelveError("function calls are not supported in formulas")
    from .lang import Program
    prog = Program({}, [("return", e, 1)], text)
    check_literals(prog, width)
    ex = Explorer(prog, width, check_overflow=False, solver_budget=budget)
    s = State.initial()
    s.env = {n: tm.var(n, width) for n in names}
    s.in_names = list(names)
    try:
        f = tm.bv2bool(ex.eval(s, e, tm.TRUE, 1))
    except Unknown:
        return "unknown", [], names
    smt = ex.smt
    target = tm.lnot(f) if prove else f
    models, blocks = [], []
    try:
        for _ in range(max(1, count)):
            conds = s.pc + [target] + blocks
            m = smt.minimize(conds, names)
            if m is None: break
            m = {n: m.get(n, 0) for n in names}
            models.append(m)
            blocks.append(tm.lnot(tm.land_all([tm.eq(tm.var(n, width), tm.const(m[n], width)) for n in names])))
            if not names: break
    except Unknown:
        return "unknown", models, names
    if prove: return ("invalid" if models else "valid"), models, names
    return ("sat" if models else "unsat"), models, names


def cmd_solve(a):
    from .cli import check_width
    check_width(a.width)
    verdict, models, names = solve_formula(a.formula, a.width, a.prove, a.count)
    w = a.width
    if verdict == "unknown":
        print("unknown (solver budget exceeded)"); return 3
    if verdict in ("unsat", "valid"):
        print("UNSAT: no assignment satisfies it" if verdict == "unsat" else "VALID: holds for every assignment of %s" % (", ".join(names) or "(no variables)"))
        return 0 if verdict == "valid" else 1
    print("SAT" if verdict == "sat" else "INVALID — counterexample%s:" % ("s" if len(models) > 1 else ""))
    for m in models:
        print("  " + (fmt_inputs(m, names, w) if names else "(no variables)"))
    return 0 if verdict == "sat" else 1


def register(sub, add_common):
    e = sub.add_parser("equiv", help="prove two programs equivalent, or find a distinguishing input")
    e.add_argument("a"); e.add_argument("b"); add_common(e)
    e.add_argument("--loop-bound", type=int, default=8)
    e.add_argument("--solver-budget", type=int, default=100000)
    e.add_argument("--no-overflow", action="store_true")
    e.set_defaults(fn=cmd_equiv)
    s = sub.add_parser("solve", help="solve a bit-vector formula, e.g. 'x*3 + y == 42 && x < y'")
    s.add_argument("formula"); add_common(s)
    s.add_argument("--prove", action="store_true", help="check validity: look for a counterexample instead")
    s.add_argument("-n", "--count", type=int, default=1, help="enumerate up to N solutions")
    s.set_defaults(fn=cmd_solve)
