"""Safety checking: level-synchronous BFS over the interleaving space.

Finds invariant violations, assertion failures, runtime errors and deadlocks, always with a
*shortest* counterexample (BFS order), optionally with partial-order reduction.
"""
import time

from .model import StepError, is_end, successors
from .trace import Trace, Violation


class SafetyResult:
    def __init__(self):
        self.violations = []
        self.states = 0
        self.transitions = 0
        self.depth = 0
        self.limited = False
        self.seconds = 0.0
        self.por = False
        self.por_reduced = 0       # states where an ample set was used
        self.terminal = 0          # valid end states reached

    @property
    def ok(self):
        return not self.violations and not self.limited


def _path(visited, s):
    steps = []
    while True:
        rec = visited[s]
        if rec is None:
            break
        parent, pid, edge = rec
        steps.append((pid, edge, s))
        s = parent
    steps.reverse()
    return s, steps


def _ample(m, s, succ, visited, observed):
    """Pick an ample set (or the full successor list).

    Conditions (Peled/Clarke-Grumberg-Peled):
      C0  non-empty iff some transition is enabled           -- we only reduce when non-empty
      C1  nothing dependent on the ample set can fire before it -- ample = *all* transitions of one
          process out of its current location, and every outgoing edge (enabled or not) touches only
          that process' private locals: no other process can read/affect them.
      C2  invisibility -- the process is not mentioned by any invariant (at()/inst.var), and local
          edges change nothing but the process' own pc/locals.
      C3  cycle proviso (BFS queue proviso, conservative) -- every ample successor is *new*; if any
          already exists we expand fully, so no cycle of reduced states can ignore a transition.
    """
    for p in m.procs:
        if p.id in observed:
            continue
        outs = p.out[s[p.pc_slot]]
        if not outs or not all(e.local for e in outs):
            continue
        mine = [x for x in succ if x[0] == p.id]
        if not mine or len(mine) == len(succ):
            continue
        if all(t not in visited for _, _, t in mine):
            return mine, True
    return succ, False


def check_safety(m, max_states=1_500_000, find_all=False, por=False, deadlock=True, invariants=True,
                 progress=None):
    t0 = time.time()
    res = SafetyResult()
    res.por = por
    observed = {p.id for p in m.procs if p.name in m.observed}
    init = m.init
    visited = {init: None}
    level = [init]
    found = {}            # key -> Violation
    depth = 0

    def record(key, kind, name, msg, s, fail=None, prop=None, extra_depth=0):
        if key in found:
            return
        root, steps = _path(visited, s)
        found[key] = Violation(kind, name, msg, Trace(root, steps, fail=fail), prop)
        res.violations.append(found[key])

    while level:
        nxt = []
        step_err = None
        for s in level:
            if invariants:
                for iv in m.invariants:
                    try:
                        good = iv.fn(s)
                    except Exception as ex:
                        record(("inv-err", iv.name), "error", iv.name, f"evaluating invariant '{iv.name}': {ex}", s)
                        continue
                    if not good:
                        record(("inv", iv.name), "invariant", iv.name, "", s, prop=iv)
            if res.violations and not find_all and not step_err:
                break
            errs = []
            succ = successors(m, s, errs)
            for ex in errs:
                key = (ex.kind, ex.edge.id, ex.msg)
                if key not in found:
                    if find_all:
                        record(key, ex.kind, ex.edge.text, ex.msg, s, fail=(ex.pid, ex.edge, ex.msg))
                    elif step_err is None:
                        step_err = (key, ex, s)
            if not succ and errs:
                continue          # every enabled statement faulted; not a deadlock
            if not succ:
                if is_end(m, s):
                    res.terminal += 1
                elif deadlock:
                    record(("deadlock",), "deadlock", "deadlock", "no process can move", s)
                continue
            if por:
                succ, reduced = _ample(m, s, succ, visited, observed)
                res.por_reduced += reduced
            res.transitions += len(succ)
            for pid, e, t in succ:
                if t not in visited:
                    visited[t] = (s, pid, e)
                    nxt.append(t)
            if len(visited) > max_states:
                res.limited = True
                break
        if res.violations and not find_all:
            break
        if step_err is not None:
            key, ex, s = step_err
            record(key, ex.kind, ex.edge.text, ex.msg, s, fail=(ex.pid, ex.edge, ex.msg))
            break
        if res.limited:
            break
        level = nxt
        depth += 1
        if progress:
            progress(len(visited), depth)
    res.states = len(visited)
    res.depth = depth
    res.seconds = time.time() - t0
    return res
