"""A from-scratch CDCL SAT solver.

Implements the modern MiniSat/Glucose-class architecture:

* two-watched-literal unit propagation (BCP),
* VSIDS activity-based branching with a lazy binary heap,
* 1-UIP conflict analysis with clause learning,
* non-chronological backjumping,
* phase saving,
* Luby-sequence restarts,
* clause-database reduction (reduceDB) at decision level 0.

It also records, for each conflict, the implication-graph data and the
sequence of learned clauses, so the visualizer and the DRAT proof checker can
work from real solver traces.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from .cnf import CNF

UNASSIGNED = None


def luby(i: int) -> int:
    """The i-th term (1-indexed) of the Luby restart sequence.

    1 1 2 1 1 2 4 1 1 2 1 1 2 4 8 ...
    """
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
    removed_clauses: int = 0
    max_decision_level: int = 0


@dataclass
class ConflictRecord:
    """Captured implication-graph data for one conflict (for the visualizer)."""

    conflict_clause: List[int]
    learned_clause: List[int]
    backjump_level: int
    decision_level: int
    # var -> (value, level, reason_clause_or_None)
    assignment: Dict[int, Tuple[bool, int, Optional[List[int]]]] = field(default_factory=dict)
    trail: List[int] = field(default_factory=list)


class Solver:
    def __init__(self, cnf: CNF, *, record_proof: bool = False,
                 record_conflicts: bool = False, restarts: bool = True,
                 reduce_db: bool = True, rng_seed: int = 0):
        self.n = cnf.nvars
        self.clauses: List[List[int]] = []          # all clauses (original + learned)
        self.learned_flag: List[bool] = []          # parallel: is clause learned?
        self.cla_activity: List[float] = []
        self.watches: Dict[int, List[int]] = {}     # literal -> clause indices
        for v in range(1, self.n + 1):
            self.watches[v] = []
            self.watches[-v] = []

        # assignment state (index by variable 1..n)
        self.assign: List[Optional[bool]] = [UNASSIGNED] * (self.n + 1)
        self.level: List[int] = [0] * (self.n + 1)
        self.reason: List[Optional[int]] = [None] * (self.n + 1)  # clause idx or None
        self.trail: List[int] = []
        self.trail_lim: List[int] = []              # trail index where each level starts
        self.qhead = 0

        # VSIDS
        self.activity: List[float] = [0.0] * (self.n + 1)
        self.var_inc = 1.0
        self.var_decay = 1.0 / 0.95
        self.cla_inc = 1.0
        self.cla_decay = 1.0 / 0.999
        self.phase: List[bool] = [False] * (self.n + 1)  # saved polarity
        self.heap: List[Tuple[float, int]] = []
        for v in range(1, self.n + 1):
            heapq.heappush(self.heap, (0.0, v))

        self.stats = Stats()
        self.use_restarts = restarts
        self.use_reduce = reduce_db
        self.ok = True                              # False => proven UNSAT at top level

        self.record_proof = record_proof
        self.proof: List[Tuple[str, List[int]]] = []   # ('a'|'d', clause)
        self.record_conflicts = record_conflicts
        self.conflict_records: List[ConflictRecord] = []

        # install original clauses
        self.n_original = 0
        for c in cnf.clauses:
            if not self._add_clause(list(c), learned=False):
                self.ok = False
        self.n_original = len(self.clauses)

    # ------------------------------------------------------------------ #
    # value helpers                                                      #
    # ------------------------------------------------------------------ #
    def value(self, lit: int) -> Optional[bool]:
        a = self.assign[abs(lit)]
        if a is UNASSIGNED:
            return UNASSIGNED
        return a if lit > 0 else (not a)

    @property
    def decision_level(self) -> int:
        return len(self.trail_lim)

    # ------------------------------------------------------------------ #
    # clause database                                                    #
    # ------------------------------------------------------------------ #
    def _add_clause(self, lits: List[int], *, learned: bool) -> bool:
        """Add a clause. Returns False if it makes the formula UNSAT outright.

        Original clauses are simplified (dedupe literals, drop tautologies,
        apply level-0 facts). Learned clauses are added as-is (already minimal).
        """
        if not learned:
            seen = set()
            simplified: List[int] = []
            for lit in lits:
                if -lit in seen:
                    return True  # tautology: clause trivially satisfied, skip
                if lit in seen:
                    continue
                seen.add(lit)
                # drop literals already false at level 0; satisfied => skip clause
                val = self.value(lit)
                if val is True and self.level[abs(lit)] == 0:
                    return True
                if val is False and self.level[abs(lit)] == 0:
                    continue
                simplified.append(lit)
            lits = simplified

        if len(lits) == 0:
            if self.record_proof:
                self.proof.append(("a", []))
            return False  # empty clause -> UNSAT
        if len(lits) == 1:
            # unit clause: enqueue as a level-0 fact
            v = self.value(lits[0])
            if v is False:
                return False
            if v is UNASSIGNED:
                self._enqueue(lits[0], None)
            return True

        idx = len(self.clauses)
        self.clauses.append(lits)
        self.learned_flag.append(learned)
        self.cla_activity.append(0.0)
        # watch the first two literals
        self.watches[lits[0]].append(idx)
        self.watches[lits[1]].append(idx)
        return True

    # ------------------------------------------------------------------ #
    # trail / assignment                                                 #
    # ------------------------------------------------------------------ #
    def _enqueue(self, lit: int, reason: Optional[int]) -> None:
        v = abs(lit)
        self.assign[v] = lit > 0
        self.level[v] = self.decision_level
        self.reason[v] = reason
        self.trail.append(lit)

    def _new_decision_level(self) -> None:
        self.trail_lim.append(len(self.trail))

    def _cancel_until(self, level: int) -> None:
        if self.decision_level <= level:
            return
        start = self.trail_lim[level]
        for i in range(len(self.trail) - 1, start - 1, -1):
            lit = self.trail[i]
            v = abs(lit)
            self.phase[v] = self.assign[v]   # phase saving
            self.assign[v] = UNASSIGNED
            self.reason[v] = None
            heapq.heappush(self.heap, (-self.activity[v], v))
        del self.trail[start:]
        del self.trail_lim[level:]
        self.qhead = min(self.qhead, len(self.trail))

    # ------------------------------------------------------------------ #
    # unit propagation (two-watched literals)                            #
    # ------------------------------------------------------------------ #
    def _propagate(self) -> Optional[int]:
        """Propagate until fixpoint. Returns the index of a conflicting clause,
        or None if no conflict."""
        while self.qhead < len(self.trail):
            p = self.trail[self.qhead]
            self.qhead += 1
            self.stats.propagations += 1
            neg = -p                       # this literal just became false
            ws = self.watches[neg]
            self.watches[neg] = []
            keep = self.watches[neg]       # rebuilt list for clauses still watching neg
            i = 0
            conflict = None
            while i < len(ws):
                cidx = ws[i]
                i += 1
                c = self.clauses[cidx]
                # make sure the false (watched) literal is at position 1
                if c[0] == neg:
                    c[0], c[1] = c[1], c[0]
                first = c[0]
                if self.value(first) is True:
                    keep.append(cidx)      # clause already satisfied; keep watch
                    continue
                # search for a non-false literal to watch instead
                found = False
                for k in range(2, len(c)):
                    if self.value(c[k]) is not False:
                        c[1], c[k] = c[k], c[1]
                        self.watches[c[1]].append(cidx)
                        found = True
                        break
                if found:
                    continue
                # no replacement: clause is unit or conflicting under `first`
                keep.append(cidx)
                if self.value(first) is False:
                    # conflict; copy the rest of the watch list back and bail
                    conflict = cidx
                    while i < len(ws):
                        keep.append(ws[i])
                        i += 1
                    self.qhead = len(self.trail)
                    break
                else:
                    self._enqueue(first, cidx)
            if conflict is not None:
                return conflict
        return None

    # ------------------------------------------------------------------ #
    # VSIDS                                                               #
    # ------------------------------------------------------------------ #
    def _bump_var(self, v: int) -> None:
        self.activity[v] += self.var_inc
        if self.activity[v] > 1e100:
            for u in range(1, self.n + 1):
                self.activity[u] *= 1e-100
            self.var_inc *= 1e-100
        heapq.heappush(self.heap, (-self.activity[v], v))

    def _decay_vars(self) -> None:
        self.var_inc *= self.var_decay

    def _bump_clause(self, cidx: int) -> None:
        self.cla_activity[cidx] += self.cla_inc
        if self.cla_activity[cidx] > 1e20:
            for j in range(len(self.cla_activity)):
                self.cla_activity[j] *= 1e-20
            self.cla_inc *= 1e-20

    def _pick_branch(self) -> Optional[int]:
        while self.heap:
            _, v = heapq.heappop(self.heap)
            if self.assign[v] is UNASSIGNED:
                return v
        # fallback linear scan (heap can transiently miss a var? shouldn't, but safe)
        for v in range(1, self.n + 1):
            if self.assign[v] is UNASSIGNED:
                return v
        return None

    # ------------------------------------------------------------------ #
    # conflict analysis: 1-UIP                                            #
    # ------------------------------------------------------------------ #
    def _analyze(self, confl: int) -> Tuple[List[int], int]:
        seen = [False] * (self.n + 1)
        learnt: List[int] = [0]        # placeholder for the asserting literal
        counter = 0
        p = 0                          # 0 == "no literal yet"
        idx = len(self.trail) - 1
        btlevel = 0
        dl = self.decision_level
        while True:
            self._bump_clause(confl)
            for q in self.clauses[confl]:
                if q == p:
                    continue
                v = abs(q)
                if not seen[v] and self.level[v] > 0:
                    seen[v] = True
                    self._bump_var(v)
                    if self.level[v] >= dl:
                        counter += 1
                    else:
                        learnt.append(q)
                        if self.level[v] > btlevel:
                            btlevel = self.level[v]
            # pick the next literal to resolve: latest on the trail that is seen
            while not seen[abs(self.trail[idx])]:
                idx -= 1
            p = self.trail[idx]
            seen[abs(p)] = False
            counter -= 1
            idx -= 1
            if counter == 0:
                break
            confl = self.reason[abs(p)]
        learnt[0] = -p                 # the 1-UIP asserting literal

        learnt = self._minimize(learnt)
        # move the highest-level literal (after the asserting one) to position 1
        if len(learnt) > 1:
            max_i = 1
            for j in range(2, len(learnt)):
                if self.level[abs(learnt[j])] > self.level[abs(learnt[max_i])]:
                    max_i = j
            learnt[1], learnt[max_i] = learnt[max_i], learnt[1]
            btlevel = self.level[abs(learnt[1])]
        else:
            btlevel = 0
        return learnt, btlevel

    def _minimize(self, learnt: List[int]) -> List[int]:
        """Self-subsuming resolution: drop a literal if all of its reason's
        literals are already in the learnt clause (recursively)."""
        # mark current learnt literals
        mark = set(abs(l) for l in learnt)
        out = [learnt[0]]
        for lit in learnt[1:]:
            v = abs(lit)
            r = self.reason[v]
            if r is None:
                out.append(lit)      # a decision literal: must keep
                continue
            redundant = True
            stack = [u for u in self.clauses[r] if abs(u) != v]
            local_seen = set()
            work = list(stack)
            while work:
                u = work.pop()
                uv = abs(u)
                if uv in mark or uv in local_seen:
                    continue
                local_seen.add(uv)
                if self.level[uv] == 0:
                    continue
                ur = self.reason[uv]
                if ur is None:
                    redundant = False
                    break
                work.extend(x for x in self.clauses[ur] if abs(x) != uv)
            if not redundant:
                out.append(lit)
        return out

    # ------------------------------------------------------------------ #
    # reduceDB                                                           #
    # ------------------------------------------------------------------ #
    def _reduce_db(self) -> None:
        """Remove ~half of the low-activity learned clauses, then renumber the
        clause database and rewrite every reference into it.

        Only called at decision level 0. Because the clause list is rebuilt and
        reindexed, we must (a) never delete a clause that is currently a reason
        for an assigned variable (a "locked" clause), and (b) remap every
        ``self.reason[v]`` index from the old numbering to the new one.
        """
        learnable = [i for i in range(len(self.clauses))
                     if self.learned_flag[i] and len(self.clauses[i]) > 2]
        if len(learnable) < 50:
            return
        # clauses currently serving as a reason are locked (cannot be removed)
        locked = set(r for r in self.reason if r is not None)
        candidates = [i for i in learnable if i not in locked]
        candidates.sort(key=lambda i: self.cla_activity[i])
        remove = set(candidates[: len(candidates) // 2])
        if not remove:
            return
        new_clauses: List[List[int]] = []
        new_learned: List[bool] = []
        new_act: List[float] = []
        remap: Dict[int, int] = {}
        for i, c in enumerate(self.clauses):
            if i in remove:
                if self.record_proof:
                    self.proof.append(("d", list(c)))
                self.stats.removed_clauses += 1
                continue
            remap[i] = len(new_clauses)
            new_clauses.append(c)
            new_learned.append(self.learned_flag[i])
            new_act.append(self.cla_activity[i])
        self.clauses = new_clauses
        self.learned_flag = new_learned
        self.cla_activity = new_act
        self.n_original = sum(1 for f in new_learned if not f)
        # remap every reason pointer into the new numbering
        for v in range(1, self.n + 1):
            r = self.reason[v]
            if r is not None:
                self.reason[v] = remap[r]   # locked clauses are guaranteed to survive
        # rebuild watches from scratch (safe at level 0)
        for lit in self.watches:
            self.watches[lit] = []
        for idx, c in enumerate(self.clauses):
            if len(c) >= 2:
                self.watches[c[0]].append(idx)
                self.watches[c[1]].append(idx)

    # ------------------------------------------------------------------ #
    # main search                                                        #
    # ------------------------------------------------------------------ #
    def solve(self, max_conflicts: Optional[int] = None) -> Optional[bool]:
        """Return True (SAT), False (UNSAT), or None (gave up at max_conflicts)."""
        if not self.ok:
            return False
        if self._propagate() is not None:
            self.ok = False
            if self.record_proof:
                self.proof.append(("a", []))
            return False

        restart_no = 0
        conflicts_since_restart = 0
        budget = luby(restart_no + 1) * 100
        while True:
            confl = self._propagate()
            if confl is not None:
                self.stats.conflicts += 1
                conflicts_since_restart += 1
                if self.decision_level == 0:
                    self.ok = False
                    if self.record_proof:
                        self.proof.append(("a", []))
                    return False
                if self.record_conflicts:
                    self._record_conflict(confl)
                learnt, btlevel = self._analyze(confl)
                self._cancel_until(btlevel)
                self.stats.learned += 1
                if self.record_proof:
                    self.proof.append(("a", list(learnt)))
                if len(learnt) == 1:
                    self._enqueue(learnt[0], None)
                else:
                    idx = len(self.clauses)
                    self.clauses.append(learnt)
                    self.learned_flag.append(True)
                    self.cla_activity.append(0.0)
                    self.watches[learnt[0]].append(idx)
                    self.watches[learnt[1]].append(idx)
                    self._bump_clause(idx)
                    self._enqueue(learnt[0], idx)
                self._decay_vars()
                self.cla_inc *= self.cla_decay
                if max_conflicts is not None and self.stats.conflicts >= max_conflicts:
                    self._cancel_until(0)
                    return None
            else:
                # restart?
                if self.use_restarts and conflicts_since_restart >= budget:
                    self._cancel_until(0)
                    restart_no += 1
                    self.stats.restarts += 1
                    conflicts_since_restart = 0
                    budget = luby(restart_no + 1) * 100
                    if self.use_reduce:
                        self._reduce_db()
                    continue
                # decide
                v = self._pick_branch()
                if v is None:
                    return True   # all variables assigned -> SAT
                self.stats.decisions += 1
                self._new_decision_level()
                self.stats.max_decision_level = max(
                    self.stats.max_decision_level, self.decision_level)
                lit = v if self.phase[v] else -v
                self._enqueue(lit, None)

    def _record_conflict(self, confl: int) -> None:
        learnt, btlevel = self._analyze_readonly(confl)
        rec = ConflictRecord(
            conflict_clause=list(self.clauses[confl]),
            learned_clause=learnt,
            backjump_level=btlevel,
            decision_level=self.decision_level,
            trail=list(self.trail),
        )
        for lit in self.trail:
            v = abs(lit)
            r = self.reason[v]
            rec.assignment[v] = (
                self.assign[v],
                self.level[v],
                list(self.clauses[r]) if r is not None else None,
            )
        self.conflict_records.append(rec)

    def _analyze_readonly(self, confl: int) -> Tuple[List[int], int]:
        """Like _analyze but with no side effects (no activity bumps), for the
        visualizer record."""
        seen = [False] * (self.n + 1)
        learnt: List[int] = [0]
        counter = 0
        p = 0
        idx = len(self.trail) - 1
        btlevel = 0
        dl = self.decision_level
        while True:
            for q in self.clauses[confl]:
                if q == p:
                    continue
                v = abs(q)
                if not seen[v] and self.level[v] > 0:
                    seen[v] = True
                    if self.level[v] >= dl:
                        counter += 1
                    else:
                        learnt.append(q)
                        btlevel = max(btlevel, self.level[v])
            while not seen[abs(self.trail[idx])]:
                idx -= 1
            p = self.trail[idx]
            seen[abs(p)] = False
            counter -= 1
            idx -= 1
            if counter == 0:
                break
            confl = self.reason[abs(p)]
        learnt[0] = -p
        return learnt, btlevel

    # ------------------------------------------------------------------ #
    # results                                                            #
    # ------------------------------------------------------------------ #
    def model(self) -> Dict[int, bool]:
        return {v: bool(self.assign[v]) for v in range(1, self.n + 1)}


def solve_cnf(cnf: CNF, *, max_conflicts: Optional[int] = None,
              **kwargs) -> Tuple[Optional[bool], Optional[Dict[int, bool]], Solver]:
    s = Solver(cnf, **kwargs)
    res = s.solve(max_conflicts=max_conflicts)
    model = s.model() if res is True else None
    return res, model, s
