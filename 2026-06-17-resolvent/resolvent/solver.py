"""A from-scratch CDCL (Conflict-Driven Clause Learning) SAT solver.

Implements the modern MiniSat-style architecture:

* two-watched-literal unit propagation,
* 1-UIP conflict analysis with learned clauses,
* non-chronological backjumping,
* VSIDS variable activity with exponential decay,
* phase saving (polarity caching),
* Luby-sequence restarts,
* activity-based learned-clause database reduction,
* optional DRAT-style clausal proof emission for UNSAT.

All assignment state is explicit; the solver makes no use of recursion for the
search loop, so it handles thousands of variables without hitting Python's
recursion limit.
"""
from __future__ import annotations

import heapq
from dataclasses import dataclass, field
from typing import List, Optional, Dict

from .cnf import CNF

# Truth values for variables.
TRUE = 1
FALSE = 0
UNASSIGNED = -1


@dataclass
class Clause:
    """A clause plus solver bookkeeping. ``lits[0]`` and ``lits[1]`` are the two
    watched literals (maintained as an invariant by propagation)."""
    lits: List[int]
    learnt: bool = False
    activity: float = 0.0


@dataclass
class Stats:
    decisions: int = 0
    propagations: int = 0
    conflicts: int = 0
    learned: int = 0
    restarts: int = 0
    db_reductions: int = 0
    removed_clauses: int = 0
    max_decision_level: int = 0


class Solver:
    def __init__(self, formula: CNF, *, record_proof: bool = False,
                 var_decay: float = 0.95, clause_decay: float = 0.999,
                 restart_base: int = 100, rng_seed: int = 0):
        self.nvars = formula.nvars
        self.var_decay = var_decay
        self.clause_decay = clause_decay
        self.restart_base = restart_base

        # Assignment state, indexed by variable 1..nvars (index 0 unused).
        self.value: List[int] = [UNASSIGNED] * (self.nvars + 1)
        self.level: List[int] = [0] * (self.nvars + 1)
        self.reason: List[Optional[Clause]] = [None] * (self.nvars + 1)
        self.phase: List[int] = [FALSE] * (self.nvars + 1)  # saved polarity

        # Trail of assigned literals in assignment order; trail_lim[d] marks the
        # start of decision level d+1.
        self.trail: List[int] = []
        self.trail_lim: List[int] = []
        self.qhead = 0

        # Watch lists: watches[lit] = clauses watching literal `lit`.
        # Indexed by lit+nvars so negative literals map cleanly.
        self.watches: List[List[Clause]] = [[] for _ in range(2 * self.nvars + 1)]

        # VSIDS activity and a lazy max-heap of (-activity, var).
        self.activity: List[float] = [0.0] * (self.nvars + 1)
        self.var_inc = 1.0
        self.clause_inc = 1.0
        self.heap: List = []

        self.clauses: List[Clause] = []
        self.learnts: List[Clause] = []
        self.stats = Stats()
        self.ok = True  # becomes False if a top-level conflict is found

        self.record_proof = record_proof
        self.proof: List[List[int]] = []  # DRAT-style additions (learned clauses)

        for v in range(1, self.nvars + 1):
            self._heap_push(v)

        for clause in formula.clauses:
            self.add_clause(list(clause))

    # ---- watch-list index helpers -----------------------------------------
    def _wi(self, lit: int) -> int:
        return lit + self.nvars

    # ---- VSIDS heap (lazy) -------------------------------------------------
    # Implemented as a lazy binary heap: an entry is (-activity, var). When a
    # variable's activity changes, a fresh entry is pushed and the old one is
    # treated as stale on pop. Invariant we rely on for completeness: every
    # *unassigned* variable always has at least one heap entry whose stored
    # activity matches its current activity. We maintain it by pushing a var
    # whenever it becomes unassigned (backtrack) or is bumped while unassigned.
    def _heap_push(self, v: int) -> None:
        heapq.heappush(self.heap, (-self.activity[v], v))

    def _heap_pop_max(self) -> Optional[int]:
        while self.heap:
            negact, v = heapq.heappop(self.heap)
            if -negact != self.activity[v]:
                continue  # stale priority, a newer entry exists
            if self.value[v] != UNASSIGNED:
                continue  # already assigned; a fresh entry follows on backtrack
            return v
        return None

    def _bump_var(self, v: int) -> None:
        self.activity[v] += self.var_inc
        if self.activity[v] > 1e100:
            for u in range(1, self.nvars + 1):
                self.activity[u] *= 1e-100
            self.var_inc *= 1e-100
            # Activities just changed wholesale; refresh entries for all
            # currently-unassigned variables to preserve the heap invariant.
            for u in range(1, self.nvars + 1):
                if self.value[u] == UNASSIGNED:
                    self._heap_push(u)
        elif self.value[v] == UNASSIGNED:
            self._heap_push(v)

    def _decay_var(self) -> None:
        self.var_inc /= self.var_decay

    def _bump_clause(self, c: Clause) -> None:
        c.activity += self.clause_inc
        if c.activity > 1e20:
            for cl in self.learnts:
                cl.activity *= 1e-20
            self.clause_inc *= 1e-20

    def _decay_clause(self) -> None:
        self.clause_inc /= self.clause_decay

    # ---- assignment helpers ------------------------------------------------
    def _val_lit(self, lit: int) -> int:
        v = self.value[abs(lit)]
        if v == UNASSIGNED:
            return UNASSIGNED
        if lit > 0:
            return v
        return TRUE if v == FALSE else FALSE

    @property
    def decision_level(self) -> int:
        return len(self.trail_lim)

    def _enqueue(self, lit: int, reason: Optional[Clause]) -> None:
        v = abs(lit)
        self.value[v] = TRUE if lit > 0 else FALSE
        self.level[v] = self.decision_level
        self.reason[v] = reason
        self.trail.append(lit)

    def _new_decision_level(self) -> None:
        self.trail_lim.append(len(self.trail))

    # ---- clause addition ---------------------------------------------------
    def add_clause(self, lits: List[int]) -> bool:
        """Add an original (problem) clause. Returns False if it makes the
        formula trivially UNSAT at the top level."""
        if not self.ok:
            return False
        # Drop tautologies & duplicate literals; detect already-true/false.
        seen = {}
        simplified: List[int] = []
        for lit in lits:
            v = self._val_lit(lit)
            if v == TRUE and self.decision_level == 0:
                return True  # clause already satisfied at root
            if v == FALSE and self.decision_level == 0:
                continue  # false literal at root: drop it
            if -lit in seen:
                return True  # tautology
            if lit in seen:
                continue
            seen[lit] = True
            simplified.append(lit)

        if len(simplified) == 0:
            self.ok = False
            return False
        if len(simplified) == 1:
            # Unit clause: enqueue as a root fact.
            if self._val_lit(simplified[0]) == FALSE:
                self.ok = False
                return False
            if self._val_lit(simplified[0]) == UNASSIGNED:
                self._enqueue(simplified[0], None)
            return True

        c = Clause(simplified, learnt=False)
        self.clauses.append(c)
        self._attach(c)
        return True

    def _attach(self, c: Clause) -> None:
        self.watches[self._wi(c.lits[0])].append(c)
        self.watches[self._wi(c.lits[1])].append(c)

    def _learn(self, lits: List[int]) -> Clause:
        c = Clause(lits, learnt=True)
        self.learnts.append(c)
        self._bump_clause(c)
        if len(lits) >= 2:
            self._attach(c)
        return c

    # ---- unit propagation (two watched literals) ---------------------------
    def _propagate(self) -> Optional[Clause]:
        """Propagate all enqueued facts. Returns the conflicting clause, or
        None if propagation completed without conflict."""
        conflict = None
        while self.qhead < len(self.trail):
            p = self.trail[self.qhead]
            self.qhead += 1
            self.stats.propagations += 1
            ws = self.watches[self._wi(-p)]  # clauses watching the now-false -p
            i = 0
            j = 0
            n = len(ws)
            while i < n:
                c = ws[i]
                lits = c.lits
                # Ensure the false (currently-watched) literal sits at lits[1].
                if lits[0] == -p:
                    lits[0], lits[1] = lits[1], lits[0]
                # lits[1] == -p now.
                first = lits[0]
                if self._val_lit(first) == TRUE:
                    # Clause already satisfied; keep this watch.
                    ws[j] = c
                    j += 1
                    i += 1
                    continue
                # Search for a non-false literal to watch instead.
                found = False
                for k in range(2, len(lits)):
                    if self._val_lit(lits[k]) != FALSE:
                        lits[1] = lits[k]
                        lits[k] = -p
                        self.watches[self._wi(lits[1])].append(c)
                        found = True
                        break
                if found:
                    i += 1
                    continue
                # No replacement: clause is unit or conflicting under `first`.
                ws[j] = c
                j += 1
                i += 1
                if self._val_lit(first) == FALSE:
                    # Conflict: copy the remaining watches over and stop.
                    while i < n:
                        ws[j] = ws[i]
                        j += 1
                        i += 1
                    del ws[j:]
                    self.qhead = len(self.trail)
                    return c
                else:
                    self._enqueue(first, c)
            del ws[j:]
        return conflict

    # ---- conflict analysis (1-UIP) ----------------------------------------
    def _analyze(self, conflict: Clause):
        """Return (learned_clause, backtrack_level). The learned clause's first
        literal is the asserting (1-UIP) literal."""
        learnt: List[int] = [0]  # placeholder for the asserting literal
        seen = [False] * (self.nvars + 1)
        counter = 0
        p = 0
        index = len(self.trail) - 1
        btlevel = 0
        c: Optional[Clause] = conflict

        while True:
            self._bump_clause(c) if c.learnt else None
            for q in c.lits:
                if q == p:
                    continue
                v = abs(q)
                if not seen[v] and self.level[v] > 0:
                    seen[v] = True
                    self._bump_var(v)
                    if self.level[v] >= self.decision_level:
                        counter += 1
                    else:
                        learnt.append(q)
                        if self.level[v] > btlevel:
                            btlevel = self.level[v]
            # Pick the next literal to resolve on: the most recently assigned
            # `seen` variable at the current decision level.
            while not seen[abs(self.trail[index])]:
                index -= 1
            p = self.trail[index]
            seen[abs(p)] = False
            counter -= 1
            index -= 1
            if counter == 0:
                break
            c = self.reason[abs(p)]

        learnt[0] = -p  # the 1-UIP asserting literal (negated)
        learnt = self._minimize(learnt, seen)
        return learnt, btlevel

    def _minimize(self, learnt: List[int], seen: List[bool]) -> List[int]:
        """Recursive (self-subsuming) clause minimization: drop a literal if all
        the literals in its reason are already present in the learned clause."""
        marked = set(abs(l) for l in learnt)
        out = [learnt[0]]
        for lit in learnt[1:]:
            r = self.reason[abs(lit)]
            if r is None:
                out.append(lit)  # decision literal, must keep
                continue
            redundant = True
            for q in r.lits:
                if abs(q) == abs(lit):
                    continue
                if abs(q) not in marked and self.level[abs(q)] > 0:
                    redundant = False
                    break
            if not redundant:
                out.append(lit)
        return out

    # ---- backtracking ------------------------------------------------------
    def _backtrack(self, level: int) -> None:
        if self.decision_level <= level:
            return
        start = self.trail_lim[level]
        for i in range(len(self.trail) - 1, start - 1, -1):
            v = abs(self.trail[i])
            self.phase[v] = self.value[v]  # save polarity
            self.value[v] = UNASSIGNED
            self.reason[v] = None
            self._heap_push(v)  # restore to the decision heap with current activity
        del self.trail[start:]
        del self.trail_lim[level:]
        self.qhead = len(self.trail)

    # ---- decision ----------------------------------------------------------
    def _pick_branch(self) -> Optional[int]:
        v = self._heap_pop_max()
        while v is not None and self.value[v] != UNASSIGNED:
            v = self._heap_pop_max()
        if v is None:
            return None
        # Phase saving: reuse the variable's last polarity.
        return v if self.phase[v] == TRUE else -v

    # ---- restart schedule (Luby) ------------------------------------------
    @staticmethod
    def _luby(i: int) -> int:
        # Luby sequence: 1 1 2 1 1 2 4 1 1 2 1 1 2 4 8 ...
        k = 1
        while True:
            if i == (1 << k) - 1:
                return 1 << (k - 1)
            if (1 << (k - 1)) <= i < (1 << k) - 1:
                return Solver._luby(i - (1 << (k - 1)) + 1)
            k += 1

    # ---- learned-clause DB reduction --------------------------------------
    def _reduce_db(self) -> None:
        self.learnts.sort(key=lambda c: c.activity)
        limit = len(self.learnts) // 2
        removed = 0
        keep: List[Clause] = []
        for idx, c in enumerate(self.learnts):
            if idx < limit and len(c.lits) > 2 and not self._is_locked(c):
                self._detach(c)
                removed += 1
            else:
                keep.append(c)
        self.learnts = keep
        self.stats.db_reductions += 1
        self.stats.removed_clauses += removed

    def _is_locked(self, c: Clause) -> bool:
        # A clause is locked if it is the reason for a current assignment.
        v = abs(c.lits[0])
        return self.reason[v] is c

    def _detach(self, c: Clause) -> None:
        for lit in (c.lits[0], c.lits[1]):
            wl = self.watches[self._wi(lit)]
            try:
                wl.remove(c)
            except ValueError:
                pass

    # ---- main search loop --------------------------------------------------
    def solve(self) -> bool:
        if not self.ok:
            return False
        # Propagate root-level units first.
        if self._propagate() is not None:
            self.ok = False
            return False

        restart_no = 0
        conflicts_until_restart = self.restart_base * self._luby(restart_no + 1)
        conflict_count = 0
        max_learnts = max(100, len(self.clauses) // 3)

        while True:
            conflict = self._propagate()
            if conflict is not None:
                self.stats.conflicts += 1
                conflict_count += 1
                if self.decision_level == 0:
                    self.ok = False
                    return False
                learnt, btlevel = self._analyze(conflict)
                self._backtrack(btlevel)
                if self.record_proof:
                    self.proof.append(list(learnt))
                if len(learnt) == 1:
                    self._enqueue(learnt[0], None)
                else:
                    c = self._learn(learnt)
                    self._enqueue(learnt[0], c)
                self.stats.learned += 1
                self._decay_var()
                self._decay_clause()

                if conflict_count >= conflicts_until_restart:
                    self.stats.restarts += 1
                    restart_no += 1
                    conflict_count = 0
                    conflicts_until_restart = self.restart_base * self._luby(restart_no + 1)
                    self._backtrack(0)
                    if len(self.learnts) > max_learnts:
                        self._reduce_db()
                        max_learnts = int(max_learnts * 1.1)
            else:
                self.stats.max_decision_level = max(
                    self.stats.max_decision_level, self.decision_level)
                lit = self._pick_branch()
                if lit is None:
                    return True  # all variables assigned -> SAT
                self.stats.decisions += 1
                self._new_decision_level()
                self._enqueue(lit, None)

    # ---- result extraction -------------------------------------------------
    def model(self) -> Dict[int, bool]:
        """Return a full variable->bool assignment. Only valid after solve()
        returned True."""
        m = {}
        for v in range(1, self.nvars + 1):
            val = self.value[v]
            # Unconstrained variables default to False.
            m[v] = (val == TRUE)
        return m

    def get_proof(self) -> List[List[int]]:
        """The DRAT-style proof (sequence of learned clauses) ending in the
        empty clause for UNSAT. Requires record_proof=True."""
        proof = list(self.proof)
        if not self.ok:
            proof.append([])  # empty clause derives UNSAT
        return proof


def solve_cnf(formula: CNF, **kwargs):
    """Convenience: returns (sat: bool, model_or_None, solver)."""
    s = Solver(formula, **kwargs)
    sat = s.solve()
    return (True, s.model(), s) if sat else (False, None, s)
