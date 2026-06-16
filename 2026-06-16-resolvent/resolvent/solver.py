"""A CDCL SAT solver: two-watched-literal propagation, 1-UIP clause learning,
non-chronological backjumping, VSIDS branching, phase saving, Luby restarts,
and learned-clause database reduction.

The algorithms follow the MiniSAT lineage. Literals are signed ints (see
:mod:`resolvent.cnf`). Internally a variable ``v`` has an assignment in
``{None, True, False}`` and an associated decision level + reason clause.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import List, Optional

from .cnf import CNF


class Clause:
    """A clause whose first two literals (``lits[0]``, ``lits[1]``) are watched.

    For a learned clause that is currently a reason, ``lits[0]`` is the implied
    (asserting) literal — analyze() relies on the implied literal being at index 0.
    """

    __slots__ = ("lits", "learnt", "lbd", "activity")

    def __init__(self, lits: List[int], learnt: bool = False):
        self.lits = lits
        self.learnt = learnt
        self.lbd = 0
        self.activity = 0.0

    def __repr__(self) -> str:
        kind = "L" if self.learnt else "O"
        return f"Clause[{kind}]({self.lits})"


@dataclass
class Stats:
    decisions: int = 0
    propagations: int = 0
    conflicts: int = 0
    learned: int = 0
    restarts: int = 0
    deleted_clauses: int = 0
    db_reductions: int = 0
    max_decision_level: int = 0


def luby(i: int) -> int:
    """The Luby restart sequence: 1,1,2,1,1,2,4,1,1,2,1,1,2,4,8,... (1-indexed)."""
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
        cnf: CNF,
        var_decay: float = 0.95,
        clause_decay: float = 0.999,
        restart_unit: int = 100,
        use_restarts: bool = True,
        use_vsids: bool = True,
        reduce_db: bool = True,
        record_conflict_graph: bool = False,
        log_proof: bool = False,
        seed: int = 0,
    ):
        self.nvars = cnf.nvars
        self.var_decay = var_decay
        self.clause_decay = clause_decay
        self.restart_unit = restart_unit
        self.use_restarts = use_restarts
        self.use_vsids = use_vsids
        self.reduce_db_enabled = reduce_db
        self.record_conflict_graph = record_conflict_graph
        self.log_proof = log_proof
        self.seed = seed

        n = self.nvars
        # var-indexed arrays, 1..n (index 0 unused)
        self.assign: List[Optional[bool]] = [None] * (n + 1)
        self.level: List[int] = [0] * (n + 1)
        self.reason: List[Optional[Clause]] = [None] * (n + 1)
        self.activity: List[float] = [0.0] * (n + 1)
        self.phase: List[bool] = [False] * (n + 1)  # saved polarity; default False

        self.trail: List[int] = []
        self.trail_lim: List[int] = []
        self.qhead = 0

        self.clauses: List[Clause] = []   # original clauses
        self.learnts: List[Clause] = []   # learned clauses
        self.watches: dict[int, List[Clause]] = {}
        for v in range(1, n + 1):
            self.watches[v] = []
            self.watches[-v] = []

        self.var_inc = 1.0
        self.cla_inc = 1.0
        self.ok = True  # becomes False if a top-level empty/unit conflict is found

        self.stats = Stats()
        self.max_learnts = max(100, cnf.nclauses // 3)
        self._restart_no = 1
        self._conflicts_since_restart = 0

        # proof / viz capture
        self.proof: List[List[int]] = []
        self.conflict_graph = None

        # Load clauses. Empty clause => immediately UNSAT.
        for lits in cnf.clauses:
            if not self.add_original_clause(lits):
                self.ok = False

    # -- assignment helpers ----------------------------------------------
    def value_lit(self, lit: int) -> Optional[bool]:
        v = self.assign[abs(lit)]
        if v is None:
            return None
        return v if lit > 0 else (not v)

    @property
    def decision_level(self) -> int:
        return len(self.trail_lim)

    def new_decision_level(self) -> None:
        self.trail_lim.append(len(self.trail))

    def enqueue(self, lit: int, reason: Optional[Clause]) -> None:
        v = abs(lit)
        self.assign[v] = lit > 0
        self.level[v] = self.decision_level
        self.reason[v] = reason
        self.trail.append(lit)

    # -- clause attachment ------------------------------------------------
    def attach(self, c: Clause) -> None:
        self.watches[c.lits[0]].append(c)
        self.watches[c.lits[1]].append(c)

    def detach(self, c: Clause) -> None:
        w0 = self.watches[c.lits[0]]
        w1 = self.watches[c.lits[1]]
        # remove first occurrence (identity)
        for i, x in enumerate(w0):
            if x is c:
                w0.pop(i)
                break
        for i, x in enumerate(w1):
            if x is c:
                w1.pop(i)
                break

    def add_original_clause(self, lits) -> bool:
        """Add an original clause at decision level 0. Returns False if it makes
        the formula trivially UNSAT (empty clause) or conflicts immediately."""
        # Simplify against level-0 assignments and dedupe.
        seen = set()
        simplified: List[int] = []
        for lit in lits:
            val = self.value_lit(lit)
            if val is True:
                return True  # clause already satisfied at level 0
            if val is False:
                continue  # drop falsified literal
            if -lit in seen:
                return True  # tautology x or -x
            if lit in seen:
                continue
            seen.add(lit)
            simplified.append(lit)
        if len(simplified) == 0:
            return False  # empty clause -> UNSAT
        if len(simplified) == 1:
            # unit: enqueue at level 0
            if self.value_lit(simplified[0]) is False:
                return False
            self.enqueue(simplified[0], None)
            return True
        c = Clause(simplified, learnt=False)
        self.clauses.append(c)
        self.attach(c)
        return True

    def add_learnt(self, lits: List[int]) -> Clause:
        c = Clause(list(lits), learnt=True)
        # compute LBD (number of distinct decision levels)
        c.lbd = len({self.level[abs(l)] for l in lits})
        c.activity = self.cla_inc
        self.learnts.append(c)
        if len(lits) >= 2:
            self.attach(c)
        self.stats.learned += 1
        return c

    # -- VSIDS ------------------------------------------------------------
    def bump_var(self, v: int) -> None:
        if not self.use_vsids:
            return
        self.activity[v] += self.var_inc
        if self.activity[v] > 1e100:
            for i in range(1, self.nvars + 1):
                self.activity[i] *= 1e-100
            self.var_inc *= 1e-100

    def decay_vars(self) -> None:
        if self.use_vsids:
            self.var_inc /= self.var_decay

    def bump_clause(self, c: Clause) -> None:
        if not c.learnt:
            return
        c.activity += self.cla_inc
        if c.activity > 1e100:
            for cl in self.learnts:
                cl.activity *= 1e-100
            self.cla_inc *= 1e-100

    def decay_clauses(self) -> None:
        self.cla_inc /= self.clause_decay

    # -- propagation (two watched literals) ------------------------------
    def propagate(self) -> Optional[Clause]:
        while self.qhead < len(self.trail):
            p = self.trail[self.qhead]
            self.qhead += 1
            self.stats.propagations += 1
            false_lit = -p
            ws = self.watches[false_lit]
            i = 0
            j = 0
            n = len(ws)
            while i < n:
                c = ws[i]
                # Ensure the falsified literal is at position 1.
                if c.lits[0] == false_lit:
                    c.lits[0], c.lits[1] = c.lits[1], c.lits[0]
                first = c.lits[0]
                if self.value_lit(first) is True:
                    ws[j] = c
                    j += 1
                    i += 1
                    continue
                # search for a non-false literal to watch instead
                found = False
                for k in range(2, len(c.lits)):
                    if self.value_lit(c.lits[k]) is not False:
                        c.lits[1] = c.lits[k]
                        c.lits[k] = false_lit
                        self.watches[c.lits[1]].append(c)
                        found = True
                        break
                if found:
                    i += 1
                    continue  # c moved to another watch list; drop from this one
                # no replacement: clause is unit or conflicting on `first`
                ws[j] = c
                j += 1
                i += 1
                if self.value_lit(first) is False:
                    # conflict: keep remaining watches, then bail
                    while i < n:
                        ws[j] = ws[i]
                        i += 1
                        j += 1
                    del ws[j:]
                    self.qhead = len(self.trail)
                    return c
                else:
                    self.enqueue(first, c)
            del ws[j:]
        return None

    # -- conflict analysis (1-UIP) ---------------------------------------
    def analyze(self, confl: Clause):
        seen = [False] * (self.nvars + 1)
        learnt: List[int] = [0]  # slot 0 reserved for the asserting literal
        counter = 0
        index = len(self.trail) - 1
        c = confl
        first = True
        antecedents = []  # (implied_lit, reason_clause) for viz

        while True:
            self.bump_clause(c)
            start = 0 if first else 1
            first = False
            for q in c.lits[start:]:
                v = abs(q)
                if not seen[v] and self.level[v] > 0:
                    self.bump_var(v)
                    seen[v] = True
                    if self.level[v] >= self.decision_level:
                        counter += 1
                    else:
                        learnt.append(q)
            # pick the next literal to resolve: latest on the trail that is seen
            while not seen[abs(self.trail[index])]:
                index -= 1
                assert index >= 0, "analyze invariant broken: no UIP on trail"
            p = self.trail[index]
            seen[abs(p)] = False
            counter -= 1
            index -= 1
            if counter == 0:
                break
            c = self.reason[abs(p)]
            antecedents.append((p, c))

        learnt[0] = -p  # the UIP literal, negated => asserting literal

        # backjump level = second-highest decision level in the clause
        if len(learnt) == 1:
            bt = 0
        else:
            maxi = 1
            for k in range(2, len(learnt)):
                if self.level[abs(learnt[k])] > self.level[abs(learnt[maxi])]:
                    maxi = k
            learnt[1], learnt[maxi] = learnt[maxi], learnt[1]
            bt = self.level[abs(learnt[1])]
        return learnt, bt

    # -- backtracking -----------------------------------------------------
    def backtrack(self, level: int) -> None:
        if self.decision_level <= level:
            return
        for i in range(len(self.trail) - 1, self.trail_lim[level] - 1, -1):
            lit = self.trail[i]
            v = abs(lit)
            self.phase[v] = self.assign[v]  # phase saving
            self.assign[v] = None
            self.reason[v] = None
        del self.trail[self.trail_lim[level]:]
        del self.trail_lim[level:]
        self.qhead = len(self.trail)

    # -- branching --------------------------------------------------------
    def pick_branch(self) -> int:
        best = 0
        best_act = -1.0
        for v in range(1, self.nvars + 1):
            if self.assign[v] is None:
                a = self.activity[v]
                if a > best_act:
                    best_act = a
                    best = v
        if best == 0:
            return 0  # all assigned
        # phase saving: reuse last polarity (default False)
        return best if self.phase[best] else -best

    # -- clause DB reduction ---------------------------------------------
    def reduce_db(self) -> None:
        if not self.learnts:
            return
        # Keep clauses that are reasons (locked) or have small LBD (<=2).
        locked = set()
        for v in range(1, self.nvars + 1):
            r = self.reason[v]
            if r is not None and r.learnt:
                locked.add(id(r))
        removable = [c for c in self.learnts if id(c) not in locked and c.lbd > 2]
        keep = [c for c in self.learnts if id(c) in locked or c.lbd <= 2]
        removable.sort(key=lambda c: c.activity)
        cut = len(removable) // 2  # drop the least-active half
        to_delete = removable[:cut]
        survivors = removable[cut:]
        for c in to_delete:
            self.detach(c)
            self.stats.deleted_clauses += 1
        self.learnts = keep + survivors
        self.stats.db_reductions += 1

    # -- main loop --------------------------------------------------------
    def solve(self) -> bool:
        if not self.ok:
            # decided UNSAT during clause loading; the empty clause is RUP from
            # the original units, so log it for a verifiable proof.
            if self.log_proof and not self.proof:
                self.proof.append([])
            return False
        # propagate top-level units first
        if self.propagate() is not None:
            self.ok = False
            if self.log_proof:
                self.proof.append([])  # empty clause
            return False

        while True:
            confl = self.propagate()
            if confl is not None:
                self.stats.conflicts += 1
                self._conflicts_since_restart += 1
                if self.decision_level == 0:
                    self.ok = False
                    if self.log_proof:
                        self.proof.append([])  # derived empty clause
                    return False
                learnt, bt = self.analyze(confl)
                if self.record_conflict_graph and self.conflict_graph is None \
                        and self.decision_level >= 1:
                    self._capture_conflict_graph(confl, learnt)
                if self.log_proof:
                    self.proof.append(list(learnt))
                self.backtrack(bt)
                if len(learnt) == 1:
                    self.enqueue(learnt[0], None)
                else:
                    c = self.add_learnt(learnt)
                    self.enqueue(learnt[0], c)
                self.decay_vars()
                self.decay_clauses()
                self.stats.max_decision_level = max(
                    self.stats.max_decision_level, self.decision_level
                )
            else:
                if len(self.trail) == self.nvars:
                    return True  # complete, conflict-free assignment => SAT
                # restart?
                if self.use_restarts:
                    limit = luby(self._restart_no) * self.restart_unit
                    if self._conflicts_since_restart >= limit:
                        self.stats.restarts += 1
                        self._restart_no += 1
                        self._conflicts_since_restart = 0
                        self.backtrack(0)
                        if self.reduce_db_enabled and len(self.learnts) > self.max_learnts:
                            self.reduce_db()
                            self.max_learnts += self.max_learnts // 10
                        continue
                lit = self.pick_branch()
                if lit == 0:
                    return True
                self.stats.decisions += 1
                self.new_decision_level()
                self.enqueue(lit, None)
                self.stats.max_decision_level = max(
                    self.stats.max_decision_level, self.decision_level
                )

    # -- results ----------------------------------------------------------
    def model(self) -> List[int]:
        """Return the satisfying assignment as a list of signed literals."""
        out = []
        for v in range(1, self.nvars + 1):
            val = self.assign[v]
            if val is None:
                out.append(v)  # free variable; pick positive arbitrarily
            else:
                out.append(v if val else -v)
        return out

    # -- conflict-graph capture (for the visualizer) ---------------------
    def _capture_conflict_graph(self, confl: Clause, learnt: List[int]):
        nodes = {}
        for lit in self.trail:
            v = abs(lit)
            r = self.reason[v]
            nodes[lit] = {
                "lit": lit,
                "var": v,
                "level": self.level[v],
                "decision": r is None,
                "reason": list(r.lits) if r is not None else None,
            }
        self.conflict_graph = {
            "nodes": nodes,
            "conflict_clause": list(confl.lits),
            "learnt": list(learnt),
            "decision_level": self.decision_level,
            "trail": list(self.trail),
        }
