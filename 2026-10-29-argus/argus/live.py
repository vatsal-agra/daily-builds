"""LTL model checking: system × Büchi(¬φ) product, then fair-accepting-cycle search via SCCs."""
import time
from collections import deque

from .ltl import _sccs, gpvw, nnf
from .lang import ArgusError
from .model import StepError, state_str, successors
from .trace import STUTTER, Trace, Violation


class LiveResult:
    def __init__(self):
        self.violation = None
        self.limited = False
        self.sys_states = 0
        self.product_states = 0
        self.product_edges = 0
        self.buchi_states = 0
        self.acc_sets = 0
        self.seconds = 0.0
        self.error = None      # Violation for a runtime error found while exploring

    @property
    def ok(self):
        return self.violation is None and not self.limited and self.error is None


def check_ltl(m, spec, fairness="weak", granularity="proc", max_states=1_500_000):
    t0 = time.time()
    res = LiveResult()
    aut = gpvw(nnf(spec.formula, False))
    res.buchi_states, res.acc_sets = len(aut.nodes), len(aut.acc)
    natoms = len(spec.atoms)
    pos_mask = [sum(1 << a for a in p) for p, _ in aut.nodes]
    neg_mask = [sum(1 << a for a in n) for _, n in aut.nodes]
    val_cache = {}
    sys_cache = {}

    def val(s):
        v = val_cache.get(s)
        if v is None:
            v = 0
            for i, (text, fn) in enumerate(spec.atoms):
                try:
                    if fn(s):
                        v |= 1 << i
                except Exception as ex:
                    raise ArgusError(f"ltl {spec.name}: cannot evaluate '{text}' in state "
                                     f"[{state_str(m, s)}]: {ex}")
            val_cache[s] = v
        return v

    def sat(q, v):
        return (v & pos_mask[q]) == pos_mask[q] and not (v & neg_mask[q])

    def expand(s):
        r = sys_cache.get(s)
        if r is None:
            succ = successors(m, s)
            en = 0
            for pid, e, _ in succ:
                en |= 1 << (pid if granularity == "proc" else e.id)
            r = (succ, en)
            sys_cache[s] = r
        return r

    ids, nodes, parent, adj, enmask = {}, [], [], [], []
    queue = deque()

    def intern(s, q, par):
        key = (s, q)
        i = ids.get(key)
        if i is None:
            i = len(nodes)
            ids[key] = i
            nodes.append(key)
            parent.append(par)
            adj.append([])
            queue.append(i)
        return i

    s0 = m.init
    v0 = val(s0)
    for q in aut.init:
        if sat(q, v0):
            intern(s0, q, None)
    enabled_of = []
    while queue:
        u = queue.popleft()
        s, q = nodes[u]
        try:
            succ, en = expand(s)
        except StepError as ex:
            kind = ex.kind
            root, steps = _prefix(parent, nodes, adj, u)
            res.error = Violation(kind, ex.edge.text, ex.msg, Trace(root, steps, fail=(ex.pid, ex.edge, ex.msg)))
            res.seconds = time.time() - t0
            return res
        while len(enabled_of) <= u:
            enabled_of.append(0)
        enabled_of[u] = en
        steps = [(pid, e, t) for pid, e, t in succ] or [(-1, STUTTER, s)]
        for pid, e, t in steps:
            vt = val(t)
            cls = -1 if e is STUTTER else (pid if granularity == "proc" else e.id)
            for q2 in aut.succ[q]:
                if sat(q2, vt):
                    v = intern(t, q2, (u, pid, e))
                    adj[u].append((v, cls, pid, e))
        if len(nodes) > max_states:
            res.limited = True
            break
    res.sys_states = len(sys_cache)
    res.product_states = len(nodes)
    res.product_edges = sum(len(a) for a in adj)
    if res.limited:
        res.seconds = time.time() - t0
        return res
    while len(enabled_of) < len(nodes):
        enabled_of.append(0)

    acc_of = [set() for _ in aut.acc]
    for i, (s, q) in enumerate(nodes):
        for j, a in enumerate(aut.acc):
            if q in a:
                acc_of[j].add(i)

    comp = _find_fair_scc(range(len(nodes)), adj, enabled_of, acc_of, fairness)
    if comp is not None:
        res.violation = _lasso(m, spec, nodes, parent, adj, enabled_of, acc_of, comp, fairness, granularity)
        res.violation.fairness, res.violation.granularity = fairness, granularity
    res.seconds = time.time() - t0
    return res


def _find_fair_scc(universe, adj, en, acc_of, fairness):
    work = [set(universe)]
    while work:
        S = work.pop()
        sub = {u: [e[0] for e in adj[u] if e[0] in S] for u in S}
        for comp in _sccs(sorted(S), sub):
            C = set(comp)
            internal = [(u, e) for u in comp for e in adj[u] if e[0] in C]
            if not internal:
                continue
            if not all(a & C for a in acc_of):
                continue
            if fairness == "none":
                return C
            taken = 0
            for _, e in internal:
                if e[1] >= 0:
                    taken |= 1 << e[1]
            any_en, all_en = 0, -1
            for u in comp:
                any_en |= en[u]
                all_en &= en[u]
            if fairness == "weak":
                if all_en & ~taken:
                    continue
                return C
            bad = any_en & ~taken            # strong: enabled somewhere but never taken
            if not bad:
                return C
            refined = {u for u in C if not (en[u] & bad)}
            if refined:
                work.append(refined)
    return None


def _prefix(parent, nodes, adj, u):
    steps = []
    while parent[u] is not None:
        p, pid, e = parent[u]
        steps.append((pid, e, nodes[u][0]))
        u = p
    steps.reverse()
    return nodes[u][0], steps


def _bfs_in(C, adj, src, pred, need_edge=False):
    """Shortest path inside C from src to a node satisfying pred, as a list of (from, edge) hops.
    With need_edge the path must use at least one edge (a non-trivial cycle back to src)."""
    if not need_edge and pred(src):
        return []
    reached, dq = {}, deque()

    def relax(u):
        for e in adj[u]:
            v = e[0]
            if v in C and v not in reached:
                reached[v] = (u, e)
                if pred(v):
                    return v
                dq.append(v)
        return None

    hit = relax(src)
    while hit is None and dq:
        hit = relax(dq.popleft())
    if hit is None:
        return None
    hops, x = [], hit
    while True:
        u, e = reached[x]
        hops.append((u, e))
        if u == src:
            break
        x = u
    hops.reverse()
    return hops


def _lasso(m, spec, nodes, parent, adj, en, acc_of, C, fairness, granularity):
    # required targets: one node per acceptance set, plus fairness repairs added iteratively
    node_targets = [min(a & C) for a in acc_of]
    edge_targets = []

    def build():
        start = (node_targets[0] if node_targets else
                 (edge_targets[0][0] if edge_targets else min(C)))
        hops = []
        cur = start
        for tgt in node_targets:
            hops += _walk(C, adj, cur, lambda x, t=tgt: x == t)
            cur = tgt
        for (u, e) in edge_targets:
            hops += _walk(C, adj, cur, lambda x, t=u: x == t)
            hops.append((u, e))
            cur = e[0]
        hops += _walk(C, adj, cur, lambda x: x == start)
        if not hops:
            hops = _walk(C, adj, start, lambda x: x == start, need_edge=True)
        return start, hops

    for _ in range(4 + 2 * len(en)):
        start, hops = build()
        if fairness == "none":
            break
        cyc_nodes = {u for u, _ in hops}
        taken = 0
        for _, e in hops:
            if e[1] >= 0:
                taken |= 1 << e[1]
        any_en, all_en = 0, -1
        for u in cyc_nodes:
            any_en |= en[u]
            all_en &= en[u]
        bad = (all_en if fairness == "weak" else any_en) & ~taken
        if not bad:
            break
        c = (bad & -bad).bit_length() - 1
        fixed = False
        for u in sorted(C):
            for e in adj[u]:
                if e[0] in C and e[1] == c:
                    edge_targets.append((u, e))
                    fixed = True
                    break
            if fixed:
                break
        if not fixed:        # weak fairness: break the "continuously enabled" premise instead
            for u in sorted(C):
                if not (en[u] >> c) & 1:
                    node_targets.append(u)
                    fixed = True
                    break
        if not fixed:
            raise AssertionError("fair SCC without a fairness witness")
    root, prefix = _prefix(parent, nodes, adj, start)
    steps = list(prefix)
    for u, e in hops:
        steps.append((e[2], e[3], nodes[e[0]][0]))
    return Violation("ltl", spec.name, "", Trace(root, steps, loop_to=len(prefix)), spec)


def _walk(C, adj, src, pred, need_edge=False):
    hops = _bfs_in(C, adj, src, pred, need_edge)
    if hops is None:
        raise AssertionError("SCC is not strongly connected?")
    return hops
