"""Incremental CDCL SAT solver: 2-watched literals, 1-UIP learning, VSIDS,
phase saving, Luby restarts, learned-clause reduction, solving under assumptions.

Literals are non-zero ints: +v / -v for variable v >= 1.
"""
import heapq


def _idx(l):
    return l * 2 if l > 0 else -l * 2 + 1


def _luby(i):
    k = 1
    while (1 << k) - 1 < i:
        k += 1
    while True:
        if (1 << k) - 1 == i:
            return 1 << (k - 1)
        i -= (1 << (k - 1)) - 1
        k = 1
        while (1 << k) - 1 < i:
            k += 1


class Solver:
    def __init__(self):
        self.nvars = 0
        self.val = [0]            # val[v] in {1,-1,0}
        self.level = [0]
        self.reason = [None]
        self.phase = [False]
        self.act = [0.0]
        self.watches = [[], []]   # index by _idx(lit)
        self.clauses = []         # problem clauses
        self.learnts = []
        self.lbd = {}             # id(clause) -> lbd
        self.trail = []
        self.trail_lim = []
        self.qhead = 0
        self.ok = True
        self.var_inc = 1.0
        self.heap = []
        self.stats = {"conflicts": 0, "decisions": 0, "propagations": 0,
                      "restarts": 0, "learnts": 0, "solves": 0}
        self.conflict_core = []
        self.model = [0]

    # ---------------------------------------------------------------- vars
    def new_var(self):
        self.nvars += 1
        v = self.nvars
        self.val.append(0)
        self.level.append(0)
        self.reason.append(None)
        self.phase.append(False)
        self.act.append(0.0)
        self.watches.append([])
        self.watches.append([])
        heapq.heappush(self.heap, (0.0, v))
        return v

    def value(self, l):
        v = self.val[abs(l)]
        return v if l > 0 else -v

    # ------------------------------------------------------------- clauses
    def add_clause(self, lits):
        """Add a problem clause. Must be called at decision level 0."""
        if not self.ok:
            return False
        self._cancel_until(0)
        seen = set()
        out = []
        for l in lits:
            if -l in seen:
                return True       # tautology
            if l in seen:
                continue
            vl = self.value(l)
            if vl == 1:
                return True
            if vl == -1:
                continue
            seen.add(l)
            out.append(l)
        if not out:
            self.ok = False
            return False
        if len(out) == 1:
            self._enqueue(out[0], None)
            if self._propagate() is not None:
                self.ok = False
                return False
            return True
        self._attach(out)
        self.clauses.append(out)
        return True

    def _attach(self, c):
        self.watches[_idx(c[0])].append(c)
        self.watches[_idx(c[1])].append(c)

    def _enqueue(self, l, reason):
        v = abs(l)
        self.val[v] = 1 if l > 0 else -1
        self.level[v] = len(self.trail_lim)
        self.reason[v] = reason
        self.trail.append(l)

    # --------------------------------------------------------- propagation
    def _propagate(self):
        trail = self.trail
        val = self.val
        watches = self.watches
        while self.qhead < len(trail):
            p = trail[self.qhead]
            self.qhead += 1
            self.stats["propagations"] += 1
            fl = -p                       # literal that just became false
            ws = watches[_idx(fl)]
            i = j = 0
            n = len(ws)
            while i < n:
                c = ws[i]
                i += 1
                if c[0] == fl:
                    c[0], c[1] = c[1], c[0]
                first = c[0]
                fv = val[first] if first > 0 else -val[-first]
                if fv == 1:
                    ws[j] = c
                    j += 1
                    continue
                found = False
                for k in range(2, len(c)):
                    lk = c[k]
                    kv = val[lk] if lk > 0 else -val[-lk]
                    if kv != -1:
                        c[1], c[k] = lk, fl
                        watches[_idx(lk)].append(c)
                        found = True
                        break
                if found:
                    continue
                ws[j] = c
                j += 1
                if fv == -1:
                    while i < n:          # conflict: keep remaining watches
                        ws[j] = ws[i]
                        j += 1
                        i += 1
                    del ws[j:]
                    self.qhead = len(trail)
                    return c
                self._enqueue(first, c)
            del ws[j:]
        return None

    # ------------------------------------------------------------- analyze
    def _bump(self, v):
        self.act[v] += self.var_inc
        if self.act[v] > 1e100:
            for u in range(1, self.nvars + 1):
                self.act[u] *= 1e-100
            self.var_inc *= 1e-100
            self.heap = [(-self.act[u], u) for u in range(1, self.nvars + 1) if self.val[u] == 0]
            heapq.heapify(self.heap)
        if self.val[v] == 0:
            heapq.heappush(self.heap, (-self.act[v], v))

    def _analyze(self, confl):
        seen = set()
        learnt = [0]
        counter = 0
        p = None
        idx = len(self.trail) - 1
        cur = len(self.trail_lim)
        c = confl
        while True:
            for q in c:
                if p is not None and q == p:
                    continue
                v = abs(q)
                if v not in seen and self.level[v] > 0:
                    seen.add(v)
                    self._bump(v)
                    if self.level[v] >= cur:
                        counter += 1
                    else:
                        learnt.append(q)
            while abs(self.trail[idx]) not in seen:
                idx -= 1
            p = self.trail[idx]
            idx -= 1
            seen.discard(abs(p))
            counter -= 1
            if counter == 0:
                break
            c = self.reason[abs(p)]
        learnt[0] = -p
        # minimization: drop literals implied by others in the clause
        keep = [learnt[0]]
        lvset = set(abs(x) for x in learnt)
        for q in learnt[1:]:
            r = self.reason[abs(q)]
            if r is None:
                keep.append(q)
                continue
            if all((abs(x) == abs(q)) or (abs(x) in lvset) or self.level[abs(x)] == 0 for x in r):
                continue
            keep.append(q)
        learnt = keep
        if len(learnt) == 1:
            bt = 0
        else:
            mi = max(range(1, len(learnt)), key=lambda k: self.level[abs(learnt[k])])
            learnt[1], learnt[mi] = learnt[mi], learnt[1]
            bt = self.level[abs(learnt[1])]
        lbd = len(set(self.level[abs(x)] for x in learnt))
        return learnt, bt, lbd

    def _cancel_until(self, lvl):
        if len(self.trail_lim) <= lvl:
            return
        lim = self.trail_lim[lvl]
        for l in reversed(self.trail[lim:]):
            v = abs(l)
            self.phase[v] = l > 0
            self.val[v] = 0
            self.reason[v] = None
            heapq.heappush(self.heap, (-self.act[v], v))
        del self.trail[lim:]
        del self.trail_lim[lvl:]
        self.qhead = len(self.trail)

    def _pick(self):
        while self.heap:
            _, v = heapq.heappop(self.heap)
            if self.val[v] == 0:
                return v if self.phase[v] else -v
        return 0

    def _reduce_db(self):
        locked = set()
        for l in self.trail:
            r = self.reason[abs(l)]
            if r is not None:
                locked.add(id(r))
        cand = [c for c in self.learnts if id(c) not in locked and self.lbd.get(id(c), 9) > 2 and len(c) > 2]
        cand.sort(key=lambda c: (-self.lbd.get(id(c), 9), -len(c)))
        drop = set(id(c) for c in cand[: len(cand) // 2])
        if not drop:
            return
        for c in self.learnts:
            if id(c) in drop:
                for w in (c[0], c[1]):
                    ws = self.watches[_idx(w)]
                    for k in range(len(ws)):
                        if ws[k] is c:
                            ws[k] = ws[-1]
                            ws.pop()
                            break
                self.lbd.pop(id(c), None)
        self.learnts = [c for c in self.learnts if id(c) not in drop]

    # --------------------------------------------------------------- solve
    def solve(self, assumptions=(), conflict_budget=None):
        """Return True (SAT), False (UNSAT under assumptions) or None (budget)."""
        self.stats["solves"] += 1
        self.conflict_core = []
        if not self.ok:
            return False
        assumptions = list(assumptions)
        self._cancel_until(0)
        if self._propagate() is not None:
            self.ok = False
            return False
        restarts = 0
        spent = 0
        max_learnts = max(2000, len(self.clauses) // 2)
        while True:
            budget = 100 * _luby(restarts + 1)
            r = self._search(budget, assumptions)
            if r is not None:
                if r:
                    self.model = list(self.val)
                self._cancel_until(0)
                return r
            restarts += 1
            self.stats["restarts"] += 1
            spent += budget
            if conflict_budget is not None and spent >= conflict_budget:
                self._cancel_until(0)
                return None
            if len(self.learnts) > max_learnts:
                self._cancel_until(0)
                self._reduce_db()
                max_learnts = int(max_learnts * 1.3)

    def _search(self, budget, assumptions):
        nconf = 0
        while True:
            confl = self._propagate()
            if confl is not None:
                self.stats["conflicts"] += 1
                nconf += 1
                if not self.trail_lim:
                    self.ok = False
                    return False
                learnt, bt, lbd = self._analyze(confl)
                self._cancel_until(bt)
                if len(learnt) == 1:
                    self._enqueue(learnt[0], None)
                else:
                    self._attach(learnt)
                    self.learnts.append(learnt)
                    self.lbd[id(learnt)] = lbd
                    self.stats["learnts"] += 1
                    self._enqueue(learnt[0], learnt)
                self.var_inc *= 1.05
                continue
            if nconf >= budget:
                self._cancel_until(0)
                return None
            # assumptions first
            nxt = 0
            while len(self.trail_lim) < len(assumptions):
                a = assumptions[len(self.trail_lim)]
                va = self.value(a)
                if va == 1:
                    self.trail_lim.append(len(self.trail))
                elif va == -1:
                    self.conflict_core = self._core(a)
                    self._cancel_until(0)
                    return False
                else:
                    nxt = a
                    break
            if nxt == 0:
                nxt = self._pick()
                if nxt == 0:
                    return True
                self.stats["decisions"] += 1
            self.trail_lim.append(len(self.trail))
            self._enqueue(nxt, None)

    def _core(self, a):
        """Subset of assumptions responsible for the failed assumption a."""
        core = {a}
        seen = set()
        stack = [abs(a)]
        while stack:
            v = stack.pop()
            if v in seen:
                continue
            seen.add(v)
            r = self.reason[v]
            if r is None:
                if self.level[v] > 0:
                    core.add(self.trail[self.trail_lim[self.level[v] - 1]])
            else:
                for q in r:
                    if abs(q) != v:
                        stack.append(abs(q))
        return sorted(core, key=abs)

    def model_value(self, v):
        return self.model[v] == 1

    def lit_model(self, l):
        return self.model_value(l) if l > 0 else not self.model_value(-l)
