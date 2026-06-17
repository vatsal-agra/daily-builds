"""A from-scratch CDCL SAT solver.

Implements the modern conflict-driven clause-learning algorithm:
  * two-watched-literal unit propagation
  * VSIDS branching heuristic (activity bumping + decay)
  * 1-UIP conflict analysis -> learned clause
  * recursive learned-clause minimization
  * non-chronological backjumping
  * Luby-sequence restarts
  * phase saving

The solver can optionally record a DRAT-style proof (the sequence of learned
clauses) so that an UNSAT result is independently checkable (see proof.py).
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import List, Optional, Dict, Tuple

from .cnf import CNF

SAT = "SAT"
UNSAT = "UNSAT"
UNKNOWN = "UNKNOWN"


def luby(i: int) -> int:
    """The Luby sequence (1-indexed): 1,1,2,1,1,2,4,1,1,2,1,1,2,4,8,..."""
    # Knuth's closed form
    k = 1
    while True:
        if i == (1 << k) - 1:
            return 1 << (k - 1)
        if (1 << (k - 1)) <= i < (1 << k) - 1:
            return luby(i - (1 << (k - 1)) + 1)
        k += 1


@dataclass
class Stats:
    decisions: int = 0
    propagations: int = 0
    conflicts: int = 0
    learned: int = 0
    restarts: int = 0
    max_decision_level: int = 0
    minimized_lits: int = 0


class Solver:
    def __init__(self, num_vars: int = 0, record_proof: bool = False,
                 var_decay: float = 0.95, restart_base: int = 100):
        self.num_vars = num_vars
        # value[v] in {None, True, False}; index 0 unused
        self.val: List[Optional[bool]] = [None] * (num_vars + 1)
        self.level: List[int] = [-1] * (num_vars + 1)
        self.reason: List[Optional[int]] = [None] * (num_vars + 1)
        self.phase: List[bool] = [False] * (num_vars + 1)

        self.clauses: List[List[int]] = []      # both original and learned
        self.is_learnt: List[bool] = []
        self.num_original = 0
        self.watches: Dict[int, List[int]] = {}  # literal -> clause refs

        self.trail: List[int] = []
        self.trail_lim: List[int] = []
        self.qhead = 0

        # VSIDS
        self.activity: List[float] = [0.0] * (num_vars + 1)
        self.var_inc = 1.0
        self.var_decay = var_decay
        self.heap: List[Tuple[float, int]] = []  # (-activity, var), lazy

        self.ok = True
        self.stats = Stats()
        self.restart_base = restart_base

        # proof recording (DRAT additions; deletions omitted -> still valid RUP)
        self.record_proof = record_proof
        self.proof: List[List[int]] = []

        # optional structured tracer (set externally)
        self.tracer = None

    # ---- helpers ---------------------------------------------------------
    def _ensure_var(self, v: int) -> None:
        if v <= self.num_vars:
            return
        extra = v - self.num_vars
        self.val.extend([None] * extra)
        self.level.extend([-1] * extra)
        self.reason.extend([None] * extra)
        self.phase.extend([False] * extra)
        self.activity.extend([0.0] * extra)
        self.num_vars = v

    def _w(self, lit: int) -> List[int]:
        lst = self.watches.get(lit)
        if lst is None:
            lst = []
            self.watches[lit] = lst
        return lst

    def lit_val(self, lit: int) -> Optional[bool]:
        v = self.val[abs(lit)]
        if v is None:
            return None
        return v if lit > 0 else (not v)

    def lit_true(self, lit: int) -> bool:
        return self.lit_val(lit) is True

    def lit_false(self, lit: int) -> bool:
        return self.lit_val(lit) is False

    def decision_level(self) -> int:
        return len(self.trail_lim)

    # ---- clause database -------------------------------------------------
    def add_clause(self, lits) -> bool:
        """Add an *original* clause. Returns False if it makes the formula UNSAT."""
        if not self.ok:
            return False
        seen = set()
        cl: List[int] = []
        for l in lits:
            l = int(l)
            if l == 0:
                raise ValueError("0 is not a literal")
            self._ensure_var(abs(l))
            if -l in seen:
                return True  # tautology: a v ~a v ... is always satisfied
            if l in seen:
                continue
            seen.add(l)
            cl.append(l)
        if len(cl) == 0:
            self.ok = False
            return False
        if len(cl) == 1:
            return self._enqueue_initial(cl[0])
        cref = len(self.clauses)
        self.clauses.append(cl)
        self.is_learnt.append(False)
        self.num_original += 1
        self._w(cl[0]).append(cref)
        self._w(cl[1]).append(cref)
        return True

    def _enqueue_initial(self, lit: int) -> bool:
        v = self.lit_val(lit)
        if v is True:
            return True
        if v is False:
            self.ok = False
            return False
        self._enqueue(lit, None)
        return True

    def _add_learnt(self, lits: List[int]) -> int:
        cref = len(self.clauses)
        self.clauses.append(lits)
        self.is_learnt.append(True)
        if len(lits) >= 2:
            self._w(lits[0]).append(cref)
            self._w(lits[1]).append(cref)
        return cref

    # ---- assignment ------------------------------------------------------
    def _enqueue(self, lit: int, reason: Optional[int]) -> None:
        v = abs(lit)
        self.val[v] = (lit > 0)
        self.level[v] = self.decision_level()
        self.reason[v] = reason
        self.trail.append(lit)

    def _new_decision_level(self) -> None:
        self.trail_lim.append(len(self.trail))

    def _backtrack_to(self, level: int) -> None:
        if self.decision_level() <= level:
            return
        target = self.trail_lim[level]
        for k in range(len(self.trail) - 1, target - 1, -1):
            lit = self.trail[k]
            v = abs(lit)
            self.phase[v] = self.val[v]  # phase saving
            self.val[v] = None
            self.reason[v] = None
            self.level[v] = -1
            heapq.heappush(self.heap, (-self.activity[v], v))
        del self.trail[target:]
        del self.trail_lim[level:]
        self.qhead = min(self.qhead, len(self.trail))

    # ---- VSIDS -----------------------------------------------------------
    def _bump(self, v: int) -> None:
        self.activity[v] += self.var_inc
        if self.activity[v] > 1e100:
            self._rescale()
        heapq.heappush(self.heap, (-self.activity[v], v))

    def _rescale(self) -> None:
        for v in range(1, self.num_vars + 1):
            self.activity[v] *= 1e-100
        self.var_inc *= 1e-100
        # heap absolute values now stale -> rebuild from unassigned vars
        self.heap = [(-self.activity[v], v)
                     for v in range(1, self.num_vars + 1) if self.val[v] is None]
        heapq.heapify(self.heap)

    def _decay(self) -> None:
        self.var_inc /= self.var_decay

    def _pick_branch_var(self) -> Optional[int]:
        while self.heap:
            negact, v = heapq.heappop(self.heap)
            if self.val[v] is None:
                return v
        # heap exhausted (can happen after rescale/rebuild) — linear fallback
        best, best_act = None, -1.0
        for v in range(1, self.num_vars + 1):
            if self.val[v] is None and self.activity[v] >= best_act:
                best, best_act = v, self.activity[v]
        return best

    # ---- propagation -----------------------------------------------------
    def propagate(self) -> Optional[int]:
        while self.qhead < len(self.trail):
            p = self.trail[self.qhead]
            self.qhead += 1
            self.stats.propagations += 1
            neg = -p  # literals that just became FALSE
            ws = self.watches.get(neg, [])
            new_ws: List[int] = []
            i = 0
            conflict = None
            n = len(ws)
            while i < n:
                cref = ws[i]
                i += 1
                c = self.clauses[cref]
                # ensure the false literal sits at c[1]
                if c[0] == neg:
                    c[0], c[1] = c[1], c[0]
                first = c[0]
                if first != neg and self.lit_true(first):
                    new_ws.append(cref)  # clause already satisfied
                    continue
                # find a new, non-false literal to watch
                found = False
                for k in range(2, len(c)):
                    if not self.lit_false(c[k]):
                        c[1], c[k] = c[k], c[1]
                        self._w(c[1]).append(cref)
                        found = True
                        break
                if found:
                    continue
                # no replacement: keep watching neg
                new_ws.append(cref)
                if self.lit_false(first):
                    conflict = cref
                    while i < n:  # preserve the rest of the watch list
                        new_ws.append(ws[i])
                        i += 1
                    break
                else:
                    self._enqueue(first, cref)
            self.watches[neg] = new_ws
            if conflict is not None:
                self.qhead = len(self.trail)
                return conflict
        return None

    # ---- conflict analysis (1-UIP) --------------------------------------
    def analyze(self, confl: int) -> Tuple[List[int], int]:
        learnt: List[int] = [0]  # placeholder for the asserting literal
        seen = [False] * (self.num_vars + 1)
        path_count = 0
        p = 0
        index = len(self.trail) - 1
        cur_level = self.decision_level()
        confl_lits = self.clauses[confl]

        while True:
            start = 0 if p == 0 else 1
            for j in range(start, len(confl_lits)):
                q = confl_lits[j]
                v = abs(q)
                if not seen[v] and self.level[v] > 0:
                    seen[v] = True
                    self._bump(v)
                    if self.level[v] >= cur_level:
                        path_count += 1
                    else:
                        learnt.append(q)
            # find the next literal on the trail that we've seen
            while not seen[abs(self.trail[index])]:
                index -= 1
            p = self.trail[index]
            seen[abs(p)] = False
            index -= 1
            path_count -= 1
            if path_count <= 0:
                break
            r = self.reason[abs(p)]
            assert r is not None, "implied literal must have a reason"
            confl_lits = self.clauses[r]

        learnt[0] = -p  # asserting literal = negation of the UIP

        # ---- recursive minimization -------------------------------------
        before = len(learnt)
        learnt = self._minimize(learnt, seen)
        self.stats.minimized_lits += before - len(learnt)

        # ---- compute backjump level -------------------------------------
        if len(learnt) == 1:
            bt = 0
        else:
            # second-highest level literal goes to position 1
            max_i = 1
            for i in range(2, len(learnt)):
                if self.level[abs(learnt[i])] > self.level[abs(learnt[max_i])]:
                    max_i = i
            learnt[1], learnt[max_i] = learnt[max_i], learnt[1]
            bt = self.level[abs(learnt[1])]
        return learnt, bt

    def _minimize(self, learnt: List[int], seen: List[bool]) -> List[int]:
        """Recursive self-subsumption: drop literals whose negation is implied by
        the other learnt literals (i.e. redundant given their reasons)."""
        # `seen` currently marks all vars in `learnt` (analyze left them set
        # except the UIP which it cleared). Rebuild reliably:
        mark = set(abs(l) for l in learnt)
        out = [learnt[0]]
        for l in learnt[1:]:
            r = self.reason[abs(l)]
            if r is None:
                out.append(l)  # decision literal — must stay
            elif not self._redundant(l, mark):
                out.append(l)
        return out

    def _redundant(self, lit: int, mark: set, depth: int = 0) -> bool:
        r = self.reason[abs(lit)]
        if r is None:
            return False
        if depth > 200:  # guard against pathological recursion
            return False
        for q in self.clauses[r]:
            if abs(q) == abs(lit):
                continue
            v = abs(q)
            if self.level[v] == 0:
                continue  # level-0 literals are globally fixed
            if v in mark:
                continue
            if self.reason[v] is None:
                return False  # depends on a decision not in the clause
            if not self._redundant(q, mark, depth + 1):
                return False
        return True

    # ---- main search -----------------------------------------------------
    def solve(self, max_conflicts: Optional[int] = None) -> str:
        if not self.ok:
            if self.record_proof:
                self.proof.append([])  # empty clause
            return UNSAT
        # init activity heap
        if not self.heap:
            self.heap = [(-self.activity[v], v) for v in range(1, self.num_vars + 1)]
            heapq.heapify(self.heap)

        # propagate any initial unit clauses
        if self.propagate() is not None:
            self.ok = False
            if self.record_proof:
                self.proof.append([])
            return UNSAT

        restart_no = 0
        conflicts_until_restart = self.restart_base * luby(restart_no + 1)
        conflicts_this_run = 0

        while True:
            confl = self.propagate()
            if confl is not None:
                self.stats.conflicts += 1
                conflicts_this_run += 1
                if max_conflicts is not None and self.stats.conflicts > max_conflicts:
                    return UNKNOWN
                if self.tracer:
                    self.tracer.on_conflict(self, confl)
                if self.decision_level() == 0:
                    if self.record_proof:
                        self.proof.append([])
                    return UNSAT
                learnt, bt = self.analyze(confl)
                self.stats.learned += 1
                if self.record_proof:
                    self.proof.append(list(learnt))
                if self.tracer:
                    self.tracer.on_learnt(self, learnt, bt)
                self._backtrack_to(bt)
                if len(learnt) == 1:
                    self._enqueue(learnt[0], None)
                else:
                    cref = self._add_learnt(learnt)
                    self._enqueue(learnt[0], cref)
                self._decay()
            else:
                if self.decision_level() > self.stats.max_decision_level:
                    self.stats.max_decision_level = self.decision_level()
                if conflicts_this_run >= conflicts_until_restart:
                    self.stats.restarts += 1
                    restart_no += 1
                    conflicts_this_run = 0
                    conflicts_until_restart = self.restart_base * luby(restart_no + 1)
                    self._backtrack_to(0)
                    continue
                v = self._pick_branch_var()
                if v is None:
                    return SAT  # all variables assigned, no conflict
                self.stats.decisions += 1
                self._new_decision_level()
                lit = v if self.phase[v] else -v
                if self.tracer:
                    self.tracer.on_decision(self, lit)
                self._enqueue(lit, None)

    def model(self) -> Dict[int, bool]:
        return {v: bool(self.val[v]) if self.val[v] is not None else False
                for v in range(1, self.num_vars + 1)}


def solve_cnf(cnf: CNF, record_proof: bool = False, **kw):
    """Convenience: build a solver from a CNF and solve.

    Returns (result, model_or_None, solver).
    """
    s = Solver(num_vars=cnf.num_vars, record_proof=record_proof, **kw)
    for cl in cnf.clauses:
        if not s.add_clause(cl):
            break
    res = s.solve()
    mdl = s.model() if res == SAT else None
    return res, mdl, s
