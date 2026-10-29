"""LTL: normal form, direct evaluation on lassos, and the GPVW tableau → generalized Büchi.

Surface formulas (from the parser) use: ap, true, false, not, and, or, imp, iff, X, F, G, U, R, W.
Core (negation normal form) formulas use only: true, false, ap, nap, and, or, X, U, R.
"""
from itertools import count

TRUE, FALSE = ("true",), ("false",)


def mk_and(a, b):
    if a == FALSE or b == FALSE:
        return FALSE
    if a == TRUE:
        return b
    if b == TRUE or a == b:
        return a
    return ("and", a, b)


def mk_or(a, b):
    if a == TRUE or b == TRUE:
        return TRUE
    if a == FALSE:
        return b
    if b == FALSE or a == b:
        return a
    return ("or", a, b)


def nnf(f, pos=True):
    """Surface → core, pushing negations to the atoms."""
    t = f[0]
    if t == "true":
        return TRUE if pos else FALSE
    if t == "false":
        return FALSE if pos else TRUE
    if t == "ap":
        return ("ap", f[1]) if pos else ("nap", f[1])
    if t == "not":
        return nnf(f[1], not pos)
    if t == "and":
        a, b = nnf(f[1], pos), nnf(f[2], pos)
        return mk_and(a, b) if pos else mk_or(a, b)
    if t == "or":
        a, b = nnf(f[1], pos), nnf(f[2], pos)
        return mk_or(a, b) if pos else mk_and(a, b)
    if t == "imp":
        return nnf(("or", ("not", f[1]), f[2]), pos)
    if t == "iff":
        return nnf(("or", ("and", f[1], f[2]), ("and", ("not", f[1]), ("not", f[2]))), pos)
    if t == "X":
        return ("X", nnf(f[1], pos))
    if t == "F":
        return nnf(("U", TRUE, f[1]), pos)
    if t == "G":
        return nnf(("R", FALSE, f[1]), pos)
    if t == "W":                       # a W b  ==  b R (a or b)
        return nnf(("R", f[2], ("or", f[1], f[2])), pos)
    if t == "U":
        a, b = nnf(f[1], pos), nnf(f[2], pos)
        return ("U", a, b) if pos else ("R", a, b)
    if t == "R":
        a, b = nnf(f[1], pos), nnf(f[2], pos)
        return ("R", a, b) if pos else ("U", a, b)
    raise ValueError(f"unknown LTL operator {t}")


def fmt_core(f, names=None):
    nm = (lambda i: names[i]) if names else (lambda i: f"p{i}")
    t = f[0]
    if t in ("true", "false"):
        return t
    if t == "ap":
        return nm(f[1])
    if t == "nap":
        return "!" + nm(f[1])
    if t == "X":
        return f"X {fmt_core(f[1], names)}"
    if t == "and":
        return f"({fmt_core(f[1], names)} && {fmt_core(f[2], names)})"
    if t == "or":
        return f"({fmt_core(f[1], names)} || {fmt_core(f[2], names)})"
    return f"({fmt_core(f[1], names)} {t} {fmt_core(f[2], names)})"


def eval_lasso(f, vals, k):
    """Truth of core formula f at every position of the ultimately periodic word
    vals[0..n-1] where position n-1 is followed by position k.  vals[i] is a bitmask of atoms."""
    n = len(vals)
    nxt = [i + 1 if i < n - 1 else k for i in range(n)]
    memo = {}

    def ev(g):
        if g in memo:
            return memo[g]
        t = g[0]
        if t == "true":
            r = [True] * n
        elif t == "false":
            r = [False] * n
        elif t == "ap":
            r = [bool(v >> g[1] & 1) for v in vals]
        elif t == "nap":
            r = [not (v >> g[1] & 1) for v in vals]
        elif t == "and":
            a, b = ev(g[1]), ev(g[2])
            r = [x and y for x, y in zip(a, b)]
        elif t == "or":
            a, b = ev(g[1]), ev(g[2])
            r = [x or y for x, y in zip(a, b)]
        elif t == "X":
            a = ev(g[1])
            r = [a[nxt[i]] for i in range(n)]
        elif t == "U":                 # least fixpoint
            a, b = ev(g[1]), ev(g[2])
            r = [False] * n
            changed = True
            while changed:
                changed = False
                for i in range(n - 1, -1, -1):
                    v = b[i] or (a[i] and r[nxt[i]])
                    if v != r[i]:
                        r[i], changed = v, True
        elif t == "R":                 # greatest fixpoint
            a, b = ev(g[1]), ev(g[2])
            r = [True] * n
            changed = True
            while changed:
                changed = False
                for i in range(n - 1, -1, -1):
                    v = b[i] and (a[i] or r[nxt[i]])
                    if v != r[i]:
                        r[i], changed = v, True
        else:
            raise ValueError(t)
        memo[g] = r
        return r

    return ev(f)


def fair_class_of(m, pid, edge, granularity):
    return pid if granularity == "proc" else edge.id


# ----------------------------------------------------------------------------------------
# GPVW: LTL → generalized Büchi automaton with labels on states
# ----------------------------------------------------------------------------------------
class Buchi:
    """States carry literal constraints.  `acc` is a list of accepting sets (generalized).
    A run is accepting iff it visits every set infinitely often."""

    def __init__(self, nodes, init, succ, acc, formula):
        self.nodes = nodes      # list of (pos:frozenset, neg:frozenset)
        self.init = init
        self.succ = succ
        self.acc = acc
        self.formula = formula

    def accepts_lasso(self, vals, k):
        """Direct acceptance test on an ultimately periodic word (for cross-checking)."""
        n = len(vals)
        nxt = lambda i: i + 1 if i < n - 1 else k

        def ok(q, i):
            pos, neg = self.nodes[q]
            v = vals[i]
            return all(v >> a & 1 for a in pos) and not any(v >> a & 1 for a in neg)

        # product graph (q, i); find a reachable SCC containing a node of each acc set
        start = [(q, 0) for q in self.init if ok(q, 0)]
        seen, order, adj = {}, [], {}
        stack = list(start)
        for s in start:
            seen[s] = True
        while stack:
            u = stack.pop()
            order.append(u)
            adj[u] = []
            q, i = u
            for q2 in self.succ[q]:
                if ok(q2, nxt(i)):
                    w = (q2, nxt(i))
                    adj[u].append(w)
                    if w not in seen:
                        seen[w] = True
                        stack.append(w)
        for comp in _sccs(order, adj):
            cs = set(comp)
            if len(comp) == 1 and comp[0] not in adj[comp[0]]:
                continue
            if all(any(q in a for (q, _) in cs) for a in self.acc):
                return True
        return False

    def to_text(self, atom_names=None):
        nm = (lambda i: atom_names[i]) if atom_names else (lambda i: f"p{i}")
        lines = [f"generalized Büchi automaton: {len(self.nodes)} states, "
                 f"{len(self.acc)} acceptance set(s)", f"  formula: {fmt_core(self.formula, atom_names)}"]
        for i, (pos, neg) in enumerate(self.nodes):
            lab = " & ".join([nm(a) for a in sorted(pos)] + ["!" + nm(a) for a in sorted(neg)]) or "true"
            flags = ("init " if i in self.init else "") + "".join(f"F{j} " for j, a in enumerate(self.acc) if i in a)
            lines.append(f"  q{i}: [{lab}] {flags}-> " + (", ".join(f"q{j}" for j in self.succ[i]) or "(dead end)"))
        return "\n".join(lines)

    def to_dot(self, atom_names=None):
        nm = (lambda i: atom_names[i]) if atom_names else (lambda i: f"p{i}")
        out = ["digraph buchi {", "  rankdir=LR; node [shape=circle fontname=Helvetica];",
               '  start [shape=point];']
        for i, (pos, neg) in enumerate(self.nodes):
            lab = "\\n".join([nm(a) for a in sorted(pos)] + ["!" + nm(a) for a in sorted(neg)]) or "true"
            acc = [j for j, a in enumerate(self.acc) if i in a]
            shape = "doublecircle" if len(acc) == len(self.acc) else "circle"
            extra = f"\\nF{','.join(map(str, acc))}" if acc and self.acc else ""
            out.append(f'  q{i} [shape={shape} label="q{i}\\n{lab}{extra}"];')
        for i in self.init:
            out.append(f"  start -> q{i};")
        for i, ss in enumerate(self.succ):
            for j in ss:
                out.append(f"  q{i} -> q{j};")
        out.append("}")
        return "\n".join(out)


def _sccs(nodes, adj):
    """Iterative Tarjan over adjacency dict; yields lists of nodes."""
    index, low, onst, st, idx = {}, {}, set(), [], count()
    for root in nodes:
        if root in index:
            continue
        work = [(root, iter(adj.get(root, ())))]
        index[root] = low[root] = next(idx)
        st.append(root)
        onst.add(root)
        while work:
            u, it = work[-1]
            adv = False
            for w in it:
                if w not in index:
                    index[w] = low[w] = next(idx)
                    st.append(w)
                    onst.add(w)
                    work.append((w, iter(adj.get(w, ()))))
                    adv = True
                    break
                elif w in onst:
                    low[u] = min(low[u], index[w])
            if adv:
                continue
            work.pop()
            if work:
                low[work[-1][0]] = min(low[work[-1][0]], low[u])
            if low[u] == index[u]:
                comp = []
                while True:
                    w = st.pop()
                    onst.discard(w)
                    comp.append(w)
                    if w == u:
                        break
                yield comp


class _GNode:
    __slots__ = ("id", "incoming", "new", "old", "next")

    def __init__(self, i, incoming, new, old, nxt):
        self.id, self.incoming, self.new, self.old, self.next = i, incoming, new, old, nxt


def subformulas(f, acc=None):
    acc = set() if acc is None else acc
    acc.add(f)
    for x in f[1:]:
        if isinstance(x, tuple):
            subformulas(x, acc)
    return acc


def gpvw(phi):
    """Gerth–Peled–Vardi–Wolper on-the-fly tableau for a core (NNF) formula."""
    ids = count(1)
    done = {}                               # (old, next) -> node
    todo = [_GNode(next(ids), {0}, {phi}, set(), set())]
    while todo:
        n = todo.pop()
        if not n.new:
            key = (frozenset(n.old), frozenset(n.next))
            ex = done.get(key)
            if ex is not None:
                ex.incoming |= n.incoming
                continue
            done[key] = n
            todo.append(_GNode(next(ids), {n.id}, set(n.next), set(), set()))
            continue
        eta = min(n.new, key=repr)
        n.new.discard(eta)
        t = eta[0]
        if t in ("ap", "nap"):
            opp = ("nap" if t == "ap" else "ap", eta[1])
            if opp in n.old:
                continue
            n.old.add(eta)
            todo.append(n)
        elif t == "true":
            n.old.add(eta)          # recorded so `psi in old` holds for `x U true`
            todo.append(n)
        elif t == "false":
            continue
        elif t == "and":
            n.old.add(eta)
            n.new |= {eta[1], eta[2]} - n.old
            todo.append(n)
        elif t == "X":
            n.old.add(eta)
            n.next.add(eta[1])
            todo.append(n)
        else:
            old2 = n.old | {eta}
            if t == "or":
                parts = [({eta[1]}, set()), ({eta[2]}, set())]
            elif t == "U":
                parts = [({eta[1]}, {eta}), ({eta[2]}, set())]
            else:                            # R
                parts = [({eta[2]}, {eta}), ({eta[1], eta[2]}, set())]
            for new_i, next_i in parts:
                todo.append(_GNode(next(ids), set(n.incoming), n.new | (new_i - old2), set(old2),
                                   n.next | next_i))
    order = sorted(done.values(), key=lambda x: x.id)
    idx = {n.id: i for i, n in enumerate(order)}
    nodes, init, succ = [], [], [[] for _ in order]
    for i, n in enumerate(order):
        pos = frozenset(f[1] for f in n.old if f[0] == "ap")
        neg = frozenset(f[1] for f in n.old if f[0] == "nap")
        nodes.append((pos, neg))
        for q in n.incoming:
            if q == 0:
                init.append(i)
            else:
                succ[idx[q]].append(i)
    untils = sorted((f for f in subformulas(phi) if f[0] == "U"), key=repr)
    acc = []
    for u in untils:
        acc.append({i for i, n in enumerate(order) if u not in n.old or u[2] in n.old})
    return Buchi(nodes, sorted(set(init)), [sorted(set(s)) for s in succ], acc, phi)


def to_buchi(surface, negate=True):
    """Automaton for the *negation* of the surface formula (what a model checker needs)."""
    return gpvw(nnf(surface, not negate))
