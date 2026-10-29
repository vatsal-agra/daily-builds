"""Counterexample traces: data model, rendering, JSON, and the independent replay validator."""
import json

from .model import ModelError, StepError, diff_str, fmt_slot, is_end, state_str, successors


class Trace:
    """init state, then steps [(pid, edge, state_after)].

    `loop_to` (liveness): the state after the last step equals the state at position loop_to
    (0 = init, k = state after step k).  `fail` (safety step errors): (pid, edge, message) of the
    transition that blew up from the last state (it has no resulting state).
    `stutter` marks steps that are the implicit "terminal state repeats forever" self-loop.
    """

    def __init__(self, init, steps, loop_to=None, fail=None):
        self.init, self.steps, self.loop_to, self.fail = init, steps, loop_to, fail

    def states(self):
        return [self.init] + [st for _, _, st in self.steps]


class Violation:
    def __init__(self, kind, name, message, trace, prop=None):
        self.kind, self.name, self.message, self.trace, self.prop = kind, name, message, trace, prop

    def title(self):
        return {"invariant": f"invariant '{self.name}' violated",
                "deadlock": "deadlock",
                "assert": "assertion violated",
                "error": "runtime error",
                "ltl": f"LTL property '{self.name}' violated"}[self.kind]


STUTTER = None   # edge placeholder for the terminal-state self-loop


def step_label(m, pid, edge, state=None):
    pw = max(len(p.name) for p in m.procs)
    if edge is STUTTER:
        why = ("all processes finished" if state is not None and is_end(m, state)
               else "DEADLOCKED: no process can move")
        return f"{'-':<{pw}}  (system idle — {why}; this state repeats forever)"
    return f"{m.procs[pid].name:<{pw}}  {edge.text}"


def render(m, v, filename=None, color=False):
    """Human-readable counterexample."""
    tr = v.trace
    fn = (filename or m.filename).split("/")[-1]
    n = len(tr.steps) + (1 if tr.fail else 0)
    msg = v.message[len("runtime error: "):] if v.message.startswith("runtime error: ") else v.message
    how = ("violated in the initial state" if n == 0 else f"{n} step{'s' if n != 1 else ''}")
    out = [f"✗ {v.title()}" + (f": {msg}" if msg and v.kind in ("assert", "error") else ""),
           f"  counterexample: {how}" +
           (f" + loop of {len(tr.steps) - tr.loop_to}" if tr.loop_to is not None else ""), ""]
    if v.kind == "invariant" and v.prop is not None:
        out.insert(1, f"  condition: {v.prop.text}")
    width = len(str(len(tr.steps) + 1))
    pw = max(len(p.name) for p in m.procs)
    out.append(f"  {'#':>{width}}  {'process':<{pw}}  statement")
    out.append(f"  {'0':>{width}}  {'init':<{pw}}  " + state_str(m, tr.init))
    prev = tr.init
    for i, (pid, edge, st) in enumerate(tr.steps, 1):
        if tr.loop_to is not None and i == tr.loop_to + 1:
            out.append(f"  {'':>{width}}  ┌── loop starts here (state after step {tr.loop_to})")
        loc = f"  ({fn}:{edge.line})" if edge is not STUTTER else ""
        ch = diff_str(m, prev, st)
        if edge is not STUTTER:
            ch = [c for c in ch if not c.split(":")[0].endswith(".pc")] or ch[:0]
        out.append(f"  {i:>{width}}  {step_label(m, pid, edge, st)}{loc}")
        if ch:
            out.append(f"  {'':>{width}}  {'':<{pw}}  ↳ " + "; ".join(ch))
        prev = st
    if tr.fail:
        pid, edge, msg = tr.fail
        out.append(f"  {len(tr.steps) + 1:>{width}}  {step_label(m, pid, edge)}  ({fn}:{edge.line})")
        out.append(f"  {'':>{width}}  {'':<{pw}}  ✗ {msg}")
    if tr.loop_to is not None:
        out.append(f"  {'':>{width}}  └── back to state after step {tr.loop_to}; this cycle repeats forever")
    out.append("")
    out.append("  final state: " + state_str(m, prev))
    return "\n".join(out)


def to_json(m, v):
    tr = v.trace
    steps = []
    prev = tr.init
    for pid, edge, st in tr.steps:
        steps.append({
            "process": m.procs[pid].name if edge is not STUTTER else None,
            "statement": edge.text if edge is not STUTTER else "(stutter)",
            "line": edge.line if edge is not STUTTER else None,
            "edge": edge.id if edge is not STUTTER else None,
            "changes": diff_str(m, prev, st),
            "state": list(_jsonable(st)),
        })
        prev = st
    d = {"kind": v.kind, "name": v.name, "message": v.message,
         "init": list(_jsonable(tr.init)), "steps": steps, "loop_to": tr.loop_to}
    if tr.fail:
        d["fail"] = {"process": m.procs[tr.fail[0]].name, "edge": tr.fail[1].id, "message": tr.fail[2]}
    return d


def _jsonable(s):
    return [list(map(list, x)) if isinstance(x, tuple) else x for x in s]


def _unjson(row):
    return tuple(tuple(tuple(msg) for msg in x) if isinstance(x, list) else x for x in row)


def trace_from_json(m, d):
    steps = []
    for st in d["steps"]:
        if st["edge"] is None:
            steps.append((-1, STUTTER, _unjson(st["state"])))
        else:
            e = m.edges[st["edge"]]
            steps.append((e.pid, e, _unjson(st["state"])))
    fail = None
    if d.get("fail"):
        e = m.edges[d["fail"]["edge"]]
        fail = (e.pid, e, d["fail"]["message"])
    v = Violation(d["kind"], d["name"], d.get("message", ""),
                  Trace(_unjson(d["init"]), steps, d.get("loop_to"), fail))
    return v


# ----------------------------------------------------------------------------------------
# independent replay validation
# ----------------------------------------------------------------------------------------
class ValidationError(Exception):
    pass


def validate(m, v, fairness="weak", granularity="proc"):
    """Re-execute a counterexample from scratch and re-check that it demonstrates the violation.

    Returns a list of human-readable facts that were verified; raises ValidationError otherwise.
    Deliberately shares no code with the search algorithms (BFS / product / SCC): it only uses the
    one-step successor function and, for LTL, a direct lasso-word evaluator.
    """
    tr = v.trace
    facts = []
    if tr.init != m.init:
        raise ValidationError("trace does not start at the model's initial state")
    s = tr.init
    states = [s]
    enabled_masks = []
    for i, (pid, edge, claimed) in enumerate(tr.steps, 1):
        succ = successors(m, s, [])
        enabled_masks.append(succ)
        if edge is STUTTER:
            if succ:
                raise ValidationError(f"step {i}: stutter step taken from a non-terminal state")
            if claimed != s:
                raise ValidationError(f"step {i}: stutter changes the state")
            s = claimed
        else:
            hit = [t for (p, e, t) in succ if e is edge]
            if not hit:
                raise ValidationError(f"step {i}: '{edge.text}' is not enabled in the preceding state")
            if hit[0] != claimed:
                raise ValidationError(f"step {i}: recorded state differs from re-executed state")
            s = claimed
        states.append(s)
    facts.append(f"replayed {len(tr.steps)} steps from the initial state; every step is enabled and deterministic")

    last = states[-1]
    if v.kind == "invariant":
        inv = next((x for x in m.invariants if x.name == v.name), None)
        if inv is None:
            raise ValidationError(f"unknown invariant {v.name}")
        if inv.fn(last):
            raise ValidationError("invariant actually holds in the final state")
        facts.append(f"invariant '{v.name}' ({inv.text}) is false in the final state")
    elif v.kind == "deadlock":
        errs = []
        if successors(m, last, errs) or errs:
            raise ValidationError("final state has enabled transitions")
        if is_end(m, last):
            raise ValidationError("final state is a valid end state, not a deadlock")
        facts.append("final state has no enabled transition and some process is not at an end state")
    elif v.kind in ("assert", "error"):
        if tr.fail is None:
            inv = next((x for x in m.invariants if x.name == v.name), None)
            if v.kind != "error" or inv is None:
                raise ValidationError("safety violation trace without a failing step")
            try:
                inv.fn(last)
            except Exception as ex:
                facts.append(f"evaluating invariant '{inv.name}' in the final state raises: {ex}")
                return facts
            raise ValidationError("invariant evaluates without error in the final state")
        pid, edge, msg = tr.fail
        errs = []
        successors(m, last, errs)
        ex = next((x for x in errs if x.edge is edge), None)
        if ex is None:
            raise ValidationError("firing the final transition does not fail")
        if (ex.kind == "assert") != (v.kind == "assert"):
            raise ValidationError("failure kind mismatch")
        facts.append(f"firing '{edge.text}' in the final state raises: {ex.msg}")
    elif v.kind == "ltl":
        facts.extend(_validate_lasso(m, v, states, enabled_masks, fairness, granularity))
    return facts


def _validate_lasso(m, v, states, step_succ, fairness, granularity):
    from .ltl import eval_lasso, nnf
    tr = v.trace
    spec = next((x for x in m.ltls if x.name == v.name), None)
    if spec is None:
        raise ValidationError(f"unknown ltl property {v.name}")
    if tr.loop_to is None:
        raise ValidationError("liveness counterexample has no loop")
    k = tr.loop_to
    if states[-1] != states[k]:
        raise ValidationError("lasso does not close: last state != loop-start state")
    facts = ["lasso closes: the final state equals the state at the loop start"]
    cyc_states = states[k:-1]          # states visited repeatedly (positions k..n-1)
    n = len(states) - 1                # word positions 0..n-1 ; position n == position k
    if not cyc_states:
        raise ValidationError("empty loop")
    vals = []
    for s in states[:-1]:
        mask = 0
        for i, (_, fn) in enumerate(spec.atoms):
            try:
                if fn(s):
                    mask |= 1 << i
            except Exception as ex:      # property evaluation error
                raise ValidationError(f"atom evaluation failed: {ex}")
        vals.append(mask)
    phi = nnf(spec.formula, True)
    truth = eval_lasso(phi, vals, k)
    if truth[0]:
        raise ValidationError("the formula actually holds on the counterexample word")
    facts.append(f"evaluated the formula directly on the lasso word ({k} prefix + {n - k} loop positions): it is FALSE")
    if fairness != "none":
        cls_enabled, cls_taken = _fair_classes(m, states, step_succ, tr, k, granularity)
        for c in sorted(cls_enabled):
            en_all = all(c in e for e in cls_enabled[c])
            en_some = any(c in e for e in cls_enabled[c])
            taken = c in cls_taken
            if fairness == "weak" and en_all and not taken:
                raise ValidationError(f"weak fairness violated: class {c} enabled throughout the loop but never taken")
            if fairness == "strong" and en_some and not taken:
                raise ValidationError(f"strong fairness violated: class {c} enabled in the loop but never taken")
        facts.append(f"the loop is {fairness}ly fair per {granularity} (every continuously/repeatedly enabled "
                     f"{'process' if granularity == 'proc' else 'statement'} also moves inside it)")
    return facts


def _fair_classes(m, states, step_succ, tr, k, granularity):
    """For each fairness class: list (over loop positions) of its enabled-sets; and classes taken."""
    from .ltl import fair_class_of
    cyc_range = range(k, len(states) - 1)
    enabled = {}
    taken = set()
    for pos in cyc_range:
        succ = step_succ[pos]
        en = set(fair_class_of(m, p, e, granularity) for (p, e, _) in succ)
        enabled.setdefault("_all", [])
        enabled["_all"].append(en)
    classes = set().union(*enabled["_all"]) if enabled.get("_all") else set()
    for pos in cyc_range:
        pid, edge, _ = tr.steps[pos]
        if edge is not STUTTER:
            taken.add(fair_class_of(m, pid, edge, granularity))
    per = {c: [en for en in enabled["_all"]] for c in classes}
    return per, taken
