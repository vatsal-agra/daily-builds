"""Crux CDCL SAT solver.

A from-scratch conflict-driven clause-learning solver with the machinery that
makes real solvers fast and correct:

* **Two-watched-literals** unit propagation (BCP).
* **1-UIP** conflict analysis producing an asserting learned clause.
* **Non-chronological backjumping**.
* **VSIDS** (Variable State Independent Decaying Sum) branching with decay.
* **Phase saving** for decisions.
* **Luby-sequence restarts**.
* **Activity-based learned-clause deletion**.

The public entry point is :func:`solve`, or the :class:`Solver` class for finer
control (statistics, assumptions, proof logging).

Literals are signed ints (DIMACS convention). Internally variables are 1..nvars.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional, Sequence, Tuple

from .cnf import CNF

# Truth values
TRUE = True
FALSE = False
UNASSIGNED = None


class Clause:
    """A clause; ``lits[0]`` and ``lits[1]`` are the two watched literals.

    ``learnt`` distinguishes original clauses from learned ones, and ``activity``
    drives clause deletion.
    """

    __slots__ = ("lits", "learnt", "activity")

    def __init__(self, lits: List[int], learnt: bool = False):
        self.lits = lits
        self.learnt = learnt
        self.activity = 0.0

    def __len__(self):
        return len(self.lits)

    def __repr__(self):
        return f"Clause({self.lits}{', learnt' if self.learnt else ''})"


@dataclass
class Stats:
    decisions: int = 0
    propagations: int = 0
    conflicts: int = 0
    learned: int = 0
    restarts: int = 0
    removed_clauses: int = 0
    max_decision_level: int = 0

    def as_dict(self) -> dict:
        return {
            "decisions": self.decisions,
            "propagations": self.propagations,
            "conflicts": self.conflicts,
            "learned": self.learned,
            "restarts": self.restarts,
            "removed_clauses": self.removed_clauses,
            "max_decision_level": self.max_decision_level,
        }


@dataclass
class Result:
    sat: bool
    model: Optional[Dict[int, bool]]  # var -> bool, only when sat
    stats: Stats
    proof: Optional[List[List[int]]] = None  # learned-clause + deletion trace

    def assignment(self) -> Optional[List[int]]:
        """Model as a sorted list of signed literals (DIMACS style)."""
        if self.model is None:
            return None
        return [v if val else -v for v, val in sorted(self.model.items())]


def luby(i: int) -> int:
    """The Luby sequence value at index ``i`` (1-indexed): 1,1,2,1,1,2,4,..."""
    # Knuth's closed form.
    k = 1
    while True:
        if i == (1 << k) - 1:
            return 1 << (k - 1)
        if (1 << (k - 1)) <= i < (1 << k) - 1:
            return luby(i - (1 << (k - 1)) + 1)
        k += 1


class Solver:
    def __init__(
        self,
        cnf: Optional[CNF] = None,
        *,
        var_decay: float = 0.95,
        clause_decay: float = 0.999,
        restart_base: int = 100,
        rng_seed: int = 1,
        record_proof: bool = False,
        trace: Optional[Callable[[str, dict], None]] = None,
    ):
        self.nvars = 0
        self.clauses: List[Clause] = []      # original (problem) clauses
        self.learnts: List[Clause] = []      # learned clauses
        self.watches: Dict[int, List[Clause]] = {}

        # Assignment state (1-indexed; index 0 unused).
        self.value: List[Optional[bool]] = [UNASSIGNED]
        self.level: List[int] = [0]
        self.reason: List[Optional[Clause]] = [None]
        self.trail: List[int] = []           # assigned literals in order
        self.trail_lim: List[int] = []       # trail index where each level began
        self.qhead = 0                       # propagation queue head into trail

        # VSIDS
        self.activity: List[float] = [0.0]
        self.var_inc = 1.0
        self.var_decay = var_decay
        self.order: List[Tuple[float, int]] = []  # lazy max-heap (-act, var)

        # phase saving
        self.phase: List[bool] = [True]

        # clause activity
        self.cla_inc = 1.0
        self.cla_decay = clause_decay

        self.restart_base = restart_base
        self.stats = Stats()
        self.ok = True                       # False once top-level UNSAT proven

        self.record_proof = record_proof
        self.proof: List[List[int]] = []      # ('a', clause) adds; ('d', clause) deletes
        self._trace = trace
        self.max_learnts = 0

        if cnf is not None:
            self.add_cnf(cnf)

    # ------------------------------------------------------------------ vars
    def new_var(self) -> int:
        self.nvars += 1
        v = self.nvars
        self.value.append(UNASSIGNED)
        self.level.append(0)
        self.reason.append(None)
        self.activity.append(0.0)
        self.phase.append(True)
        self.watches.setdefault(v, [])
        self.watches.setdefault(-v, [])
        import heapq
        heapq.heappush(self.order, (-0.0, v))
        return v

    def _ensure_var(self, v: int):
        while self.nvars < v:
            self.new_var()

    def add_cnf(self, cnf: CNF):
        self._ensure_var(cnf.nvars)
        for c in cnf.clauses:
            self.add_clause(c)

    # ----------------------------------------------------------- clause add
    def add_clause(self, lits: Sequence[int]) -> bool:
        """Add an original clause. Returns False if it makes the formula UNSAT.

        Performs the standard top-level simplifications: drop tautologies and
        already-true clauses, remove false literals, detect empty/unit clauses.
        """
        if not self.ok:
            return False
        # normalise
        seen = {}
        clause: List[int] = []
        for lit in lits:
            v = abs(lit)
            self._ensure_var(v)
            if lit in seen:
                continue
            if -lit in seen:
                return True  # tautology -> trivially satisfied, ignore
            seen[lit] = True
            val = self._lit_value(lit)
            if val is TRUE:
                return True  # already satisfied at level 0
            if val is FALSE:
                continue     # drop false literal (only valid at level 0)
            clause.append(lit)

        if len(clause) == 0:
            # empty clause -> UNSAT
            self.ok = False
            if self.record_proof:
                self.proof.append(["a"])  # empty clause
            return False
        if len(clause) == 1:
            # unit clause -> enqueue at level 0
            if not self._enqueue(clause[0], None):
                self.ok = False
                return False
            # propagate immediately so subsequent adds see it
            confl = self._propagate()
            if confl is not None:
                self.ok = False
                return False
            return True

        cl = Clause(clause, learnt=False)
        self.clauses.append(cl)
        self._attach(cl)
        return True

    def _attach(self, cl: Clause):
        # watch the negation of the first two literals
        self.watches[-cl.lits[0]].append(cl)
        self.watches[-cl.lits[1]].append(cl)

    def _detach(self, cl: Clause):
        try:
            self.watches[-cl.lits[0]].remove(cl)
        except ValueError:
            pass
        try:
            self.watches[-cl.lits[1]].remove(cl)
        except ValueError:
            pass

    # ------------------------------------------------------------- helpers
    def _lit_value(self, lit: int) -> Optional[bool]:
        v = self.value[abs(lit)]
        if v is UNASSIGNED:
            return UNASSIGNED
        return v if lit > 0 else (not v)

    @property
    def decision_level(self) -> int:
        return len(self.trail_lim)

    def _enqueue(self, lit: int, reason: Optional[Clause]) -> bool:
        """Assign ``lit`` true. Return False if it contradicts current value."""
        val = self._lit_value(lit)
        if val is not UNASSIGNED:
            return val is TRUE
        v = abs(lit)
        self.value[v] = lit > 0
        self.level[v] = self.decision_level
        self.reason[v] = reason
        self.trail.append(lit)
        if self._trace:
            self._trace(
                "enqueue",
                {"lit": lit, "level": self.decision_level,
                 "reason": list(reason.lits) if reason else None},
            )
        return True

    # ------------------------------------------------------------ propagate
    def _propagate(self) -> Optional[Clause]:
        """Boolean constraint propagation. Returns a conflict clause or None."""
        conflict = None
        while self.qhead < len(self.trail):
            p = self.trail[self.qhead]
            self.qhead += 1
            self.stats.propagations += 1
            watchers = self.watches[p]   # clauses watching -p (now false)
            i = 0
            keep = 0
            n = len(watchers)
            while i < n:
                cl = watchers[i]
                i += 1
                lits = cl.lits
                false_lit = -p
                # make false_lit be lits[1]
                if lits[0] == false_lit:
                    lits[0], lits[1] = lits[1], lits[0]
                first = lits[0]
                if first != lits[1] and self._lit_value(first) is TRUE:
                    # clause already satisfied; keep this watch
                    watchers[keep] = cl
                    keep += 1
                    continue
                # look for a new, non-false literal to watch
                found = False
                for k in range(2, len(lits)):
                    if self._lit_value(lits[k]) is not FALSE:
                        lits[1] = lits[k]
                        lits[k] = false_lit
                        self.watches[-lits[1]].append(cl)
                        found = True
                        break
                if found:
                    continue  # do not keep in this watch list
                # no new watch: clause is unit or conflicting
                watchers[keep] = cl
                keep += 1
                if self._lit_value(first) is FALSE:
                    # conflict: drain remaining watchers untouched
                    while i < n:
                        watchers[keep] = watchers[i]
                        keep += 1
                        i += 1
                    del watchers[keep:]
                    self.qhead = len(self.trail)  # stop
                    return cl
                else:
                    if not self._enqueue(first, cl):
                        # shouldn't happen (first is unassigned)
                        while i < n:
                            watchers[keep] = watchers[i]
                            keep += 1
                            i += 1
                        del watchers[keep:]
                        self.qhead = len(self.trail)
                        return cl
            del watchers[keep:]
        return conflict

    # ------------------------------------------------------------- VSIDS
    def _var_bump(self, v: int):
        self.activity[v] += self.var_inc
        if self.activity[v] > 1e100:
            for i in range(1, self.nvars + 1):
                self.activity[i] *= 1e-100
            self.var_inc *= 1e-100
        import heapq
        heapq.heappush(self.order, (-self.activity[v], v))

    def _var_decay(self):
        self.var_inc /= self.var_decay

    def _cla_bump(self, cl: Clause):
        cl.activity += self.cla_inc
        if cl.activity > 1e20:
            for c in self.learnts:
                c.activity *= 1e-20
            self.cla_inc *= 1e-20

    def _cla_decay_step(self):
        self.cla_inc /= self.cla_decay

    def _pick_branch(self) -> Optional[int]:
        """Choose an unassigned variable by max VSIDS activity; assign by phase."""
        import heapq
        while self.order:
            neg_act, v = self.order[0]
            if self.value[v] is not UNASSIGNED:
                heapq.heappop(self.order)
                continue
            # lazy: skip stale entries whose activity is out of date
            if -neg_act != self.activity[v]:
                heapq.heappop(self.order)
                continue
            heapq.heappop(self.order)
            lit = v if self.phase[v] else -v
            return lit
        # fall back: linear scan (heap may have been emptied of a var)
        for v in range(1, self.nvars + 1):
            if self.value[v] is UNASSIGNED:
                return v if self.phase[v] else -v
        return None

    # ------------------------------------------------------- backtracking
    def _new_decision_level(self):
        self.trail_lim.append(len(self.trail))

    def _cancel_until(self, level: int):
        if self.decision_level <= level:
            return
        import heapq
        for i in range(len(self.trail) - 1, self.trail_lim[level] - 1, -1):
            lit = self.trail[i]
            v = abs(lit)
            self.phase[v] = self.value[v]      # phase saving
            self.value[v] = UNASSIGNED
            self.reason[v] = None
            heapq.heappush(self.order, (-self.activity[v], v))
        del self.trail[self.trail_lim[level]:]
        del self.trail_lim[level:]
        self.qhead = len(self.trail)

    # --------------------------------------------------------- analyze
    def _analyze(self, conflict: Clause) -> Tuple[List[int], int]:
        """1-UIP conflict analysis. Returns (learned literals, backjump level).

        learned[0] is the asserting literal (will be unit after backjump).
        """
        seen = [False] * (self.nvars + 1)
        learnt: List[int] = [0]  # reserve slot 0 for the asserting literal
        p = 0
        path_count = 0
        confl: Optional[Clause] = conflict
        index = len(self.trail) - 1

        while True:
            assert confl is not None
            if confl.learnt:
                self._cla_bump(confl)
            start = 0 if p == 0 else 1
            for j in range(start, len(confl.lits)):
                q = confl.lits[j]
                v = abs(q)
                if not seen[v] and self.level[v] > 0:
                    self._var_bump(v)
                    seen[v] = True
                    if self.level[v] >= self.decision_level:
                        path_count += 1
                    else:
                        learnt.append(q)
            # find the next literal on the trail that we've seen
            while not seen[abs(self.trail[index])]:
                index -= 1
            p = self.trail[index]
            v = abs(p)
            seen[v] = False
            confl = self.reason[v]
            path_count -= 1
            index -= 1
            if path_count <= 0:
                break

        learnt[0] = -p  # asserting literal = negation of the 1-UIP

        # optional: minimize learned clause (self-subsuming resolution, simple form)
        learnt = self._minimize(learnt, seen)

        # backjump level: second-highest level in the clause
        if len(learnt) == 1:
            btlevel = 0
        else:
            maxi = 1
            for k in range(2, len(learnt)):
                if self.level[abs(learnt[k])] > self.level[abs(learnt[maxi])]:
                    maxi = k
            learnt[1], learnt[maxi] = learnt[maxi], learnt[1]
            btlevel = self.level[abs(learnt[1])]
        return learnt, btlevel

    def _minimize(self, learnt: List[int], seen: List[bool]) -> List[int]:
        """Local self-subsuming minimization: drop a literal if all the literals
        in its reason are already in the learned clause (i.e., redundant)."""
        # Mark current learned literals.
        marked = set(abs(l) for l in learnt)
        out = [learnt[0]]
        for lit in learnt[1:]:
            v = abs(lit)
            r = self.reason[v]
            if r is None:
                out.append(lit)
                continue
            redundant = True
            for q in r.lits:
                if abs(q) == v:
                    continue
                if abs(q) not in marked and self.level[abs(q)] > 0:
                    redundant = False
                    break
            if not redundant:
                out.append(lit)
        return out

    # ------------------------------------------------------------- learn
    def _record_learnt(self, learnt: List[int]) -> Optional[Clause]:
        if self.record_proof:
            self.proof.append(["a"] + list(learnt))
        if len(learnt) == 1:
            self._enqueue(learnt[0], None)
            self.stats.learned += 1
            return None
        cl = Clause(list(learnt), learnt=True)
        self.learnts.append(cl)
        self._attach(cl)
        self._cla_bump(cl)
        self.stats.learned += 1
        self._enqueue(learnt[0], cl)
        return cl

    def _reduce_db(self):
        """Delete roughly half the learned clauses (low activity, size > 2,
        not currently a reason)."""
        if not self.learnts:
            return
        # protect clauses that are reasons for current assignments
        reasons = set(id(self.reason[abs(l)]) for l in self.trail
                      if self.reason[abs(l)] is not None)
        self.learnts.sort(key=lambda c: c.activity)
        limit = self.cla_inc / max(1, len(self.learnts))
        keep: List[Clause] = []
        half = len(self.learnts) // 2
        for i, cl in enumerate(self.learnts):
            if (len(cl.lits) > 2 and id(cl) not in reasons
                    and (i < half or cl.activity < limit)):
                self._detach(cl)
                self.stats.removed_clauses += 1
                if self.record_proof:
                    self.proof.append(["d"] + list(cl.lits))
            else:
                keep.append(cl)
        self.learnts = keep

    # --------------------------------------------------------------- solve
    def solve(self, assumptions: Optional[Sequence[int]] = None) -> Result:
        """Run CDCL. ``assumptions`` are literals forced true at the bottom.

        Each assumption occupies its own bottom decision level, so we never
        backjump past them; if an assumption is falsified the result is UNSAT
        *under those assumptions* (the formula itself may still be SAT).
        """
        if not self.ok:
            return self._unsat_result()

        assumptions = list(assumptions or [])
        for a in assumptions:
            self._ensure_var(abs(a))
        n_assump = len(assumptions)

        # initial top-level propagation
        if self._propagate() is not None:
            self.ok = False
            return self._unsat_result()

        self.max_learnts = max(100, len(self.clauses) // 3)
        restart_no = 1
        conflicts_until_restart = self.restart_base * luby(restart_no)
        conflict_count = 0

        while True:
            confl = self._propagate()
            if confl is not None:
                self.stats.conflicts += 1
                conflict_count += 1
                if self.decision_level <= n_assump:
                    # conflict at or below the assumption floor -> UNSAT here.
                    if self.decision_level == 0:
                        self.ok = False
                        if self.record_proof:
                            self.proof.append(["a"])  # derived empty clause
                    return self._unsat_result()
                learnt, btlevel = self._analyze(confl)
                btlevel = max(btlevel, n_assump)
                self._cancel_until(btlevel)
                self._record_learnt(learnt)
                self._var_decay()
                self._cla_decay_step()
                if self.stats.max_decision_level < self.decision_level:
                    self.stats.max_decision_level = self.decision_level
            else:
                # restart? (never past the assumption floor)
                if conflict_count >= conflicts_until_restart:
                    self.stats.restarts += 1
                    restart_no += 1
                    conflict_count = 0
                    conflicts_until_restart = self.restart_base * luby(restart_no)
                    self._cancel_until(n_assump)
                # reduce clause DB?
                if len(self.learnts) >= self.max_learnts + len(self.trail):
                    self._reduce_db()
                    self.max_learnts = int(self.max_learnts * 1.1)

                # next assumption to place, if any
                next_lit = None
                if self.decision_level < n_assump:
                    a = assumptions[self.decision_level]
                    val = self._lit_value(a)
                    if val is FALSE:
                        return self._unsat_result()
                    if val is TRUE:
                        # already implied; occupy an empty decision level to keep
                        # the floor count aligned
                        self._new_decision_level()
                        continue
                    next_lit = a
                else:
                    next_lit = self._pick_branch()

                if next_lit is None:
                    model = {v: self.value[v] for v in range(1, self.nvars + 1)}
                    return Result(True, model, self.stats,
                                  self.proof if self.record_proof else None)
                self.stats.decisions += 1
                self._new_decision_level()
                self._enqueue(next_lit, None)

    def _unsat_result(self) -> Result:
        return Result(False, None, self.stats,
                      self.proof if self.record_proof else None)


def solve(cnf: CNF, **kw) -> Result:
    """Convenience: build a solver from a CNF and solve it."""
    return Solver(cnf, **kw).solve()
