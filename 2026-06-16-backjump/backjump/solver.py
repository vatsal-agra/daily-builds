"""A CDCL SAT solver.

Implements the modern conflict-driven clause-learning loop:

  * two-watched-literal unit propagation,
  * 1-UIP conflict analysis with clause learning,
  * non-chronological backjumping,
  * VSIDS branching with activity decay (indexed binary heap),
  * phase saving,
  * Luby-sequence restarts,
  * an optional DRUP-style proof log (learned clauses in derivation order),
  * an optional event trace for the visualizer.

The solver is deterministic: given the same CNF (and options) it makes exactly
the same decisions every run.
"""

from __future__ import annotations

from typing import List, Optional, Dict, Tuple

SAT = "SAT"
UNSAT = "UNSAT"


class OrderHeap:
    """Max-heap of variables keyed by activity, with O(log n) key updates.

    Mirrors the indexed heap used by MiniSat (a min-heap over -activity); here
    we keep a max-heap over activity directly.
    """

    def __init__(self, activity: List[float]):
        self.act = activity
        self.heap: List[int] = []
        self.pos: Dict[int, int] = {}

    def __len__(self) -> int:
        return len(self.heap)

    def empty(self) -> bool:
        return not self.heap

    def contains(self, v: int) -> bool:
        return v in self.pos

    def _greater(self, a: int, b: int) -> bool:
        return self.act[a] > self.act[b]

    def _up(self, i: int) -> None:
        v = self.heap[i]
        while i > 0:
            parent = (i - 1) >> 1
            if not self._greater(v, self.heap[parent]):
                break
            self.heap[i] = self.heap[parent]
            self.pos[self.heap[i]] = i
            i = parent
        self.heap[i] = v
        self.pos[v] = i

    def _down(self, i: int) -> None:
        v = self.heap[i]
        n = len(self.heap)
        while True:
            left = 2 * i + 1
            if left >= n:
                break
            right = left + 1
            child = right if (right < n and self._greater(self.heap[right], self.heap[left])) else left
            if not self._greater(self.heap[child], v):
                break
            self.heap[i] = self.heap[child]
            self.pos[self.heap[i]] = i
            i = child
        self.heap[i] = v
        self.pos[v] = i

    def insert(self, v: int) -> None:
        if v in self.pos:
            return
        self.heap.append(v)
        self.pos[v] = len(self.heap) - 1
        self._up(self.pos[v])

    def increased(self, v: int) -> None:
        """Call after activity[v] increased: restore heap order."""
        if v in self.pos:
            self._up(self.pos[v])

    def rebuild(self) -> None:
        for i in range(len(self.heap) // 2 - 1, -1, -1):
            self._down(i)

    def pop_max(self) -> int:
        top = self.heap[0]
        last = self.heap.pop()
        del self.pos[top]
        if self.heap:
            self.heap[0] = last
            self.pos[last] = 0
            self._down(0)
        return top


def luby(i: int) -> int:
    """The Luby restart sequence: 1 1 2 1 1 2 4 1 1 2 1 1 2 4 8 ...  (i >= 1)."""
    k = 1
    while True:
        if i == (1 << k) - 1:
            return 1 << (k - 1)
        if (1 << (k - 1)) <= i < (1 << k) - 1:
            return luby(i - (1 << (k - 1)) + 1)
        k += 1


class Stats:
    def __init__(self):
        self.decisions = 0
        self.propagations = 0
        self.conflicts = 0
        self.learned = 0
        self.restarts = 0
        self.max_depth = 0

    def as_dict(self) -> dict:
        return {
            "decisions": self.decisions,
            "propagations": self.propagations,
            "conflicts": self.conflicts,
            "learned": self.learned,
            "restarts": self.restarts,
            "max_depth": self.max_depth,
        }

    def __str__(self) -> str:
        return (
            f"decisions={self.decisions} propagations={self.propagations} "
            f"conflicts={self.conflicts} learned={self.learned} "
            f"restarts={self.restarts} max_depth={self.max_depth}"
        )


class Solver:
    def __init__(
        self,
        cnf,
        record_trace: bool = False,
        emit_proof: bool = False,
        var_decay: float = 0.95,
        restart_base: int = 100,
        max_conflicts: Optional[int] = None,
    ):
        self.n = cnf.num_vars
        # clauses are mutable lists; watched literals kept at index 0 and 1.
        self.clauses: List[List[int]] = [list(c) for c in cnf.clauses]
        self.num_originals = len(self.clauses)

        # assignment state (1-indexed; index 0 unused)
        self.value: List[Optional[bool]] = [None] * (self.n + 1)
        self.level: List[int] = [-1] * (self.n + 1)
        self.reason: List[Optional[int]] = [None] * (self.n + 1)  # clause index or None
        self.saved_phase: List[bool] = [False] * (self.n + 1)

        self.trail: List[int] = []
        self.trail_lim: List[int] = []  # trail index where each decision level begins
        self.qhead = 0

        # watches[lit] -> list of clause indices currently watching `lit`
        self.watches: Dict[int, List[int]] = {}
        for lit in range(-self.n, self.n + 1):
            if lit != 0:
                self.watches[lit] = []

        # VSIDS
        self.activity: List[float] = [0.0] * (self.n + 1)
        self.var_inc = 1.0
        self.var_decay = var_decay
        self.order = OrderHeap(self.activity)

        self.stats = Stats()
        self.restart_base = restart_base
        self.max_conflicts = max_conflicts
        self._seen = bytearray(self.n + 1)

        # proof + trace
        self.emit_proof = emit_proof
        self.proof: List[List[int]] = []  # learned clauses in order (then empty)
        self.record_trace = record_trace
        self.trace: List[dict] = []

        self.status: Optional[str] = None
        self._build_watches()
        for v in range(1, self.n + 1):
            self.order.insert(v)

    # ----- low level -----------------------------------------------------
    def _build_watches(self) -> None:
        for ci, clause in enumerate(self.clauses):
            self._attach(ci, clause)

    def _attach(self, ci: int, clause: List[int]) -> None:
        if len(clause) == 0:
            return  # empty clause handled at solve() start
        if len(clause) == 1:
            # unit clause: watch its single literal (no second watch)
            self.watches[clause[0]].append(ci)
            return
        self.watches[clause[0]].append(ci)
        self.watches[clause[1]].append(ci)

    def value_lit(self, lit: int) -> Optional[bool]:
        v = self.value[abs(lit)]
        if v is None:
            return None
        return v if lit > 0 else (not v)

    def decision_level(self) -> int:
        return len(self.trail_lim)

    def enqueue(self, lit: int, reason: Optional[int]) -> None:
        v = abs(lit)
        self.value[v] = lit > 0
        self.level[v] = self.decision_level()
        self.reason[v] = reason
        self.trail.append(lit)

    # ----- VSIDS ---------------------------------------------------------
    def bump_var(self, v: int) -> None:
        self.activity[v] += self.var_inc
        if self.activity[v] > 1e100:
            for i in range(1, self.n + 1):
                self.activity[i] *= 1e-100
            self.var_inc *= 1e-100
            self.order.rebuild()
        self.order.increased(v)

    def decay_vars(self) -> None:
        self.var_inc /= self.var_decay

    # ----- propagation ---------------------------------------------------
    def propagate(self) -> Optional[int]:
        """Boolean constraint propagation.  Returns a conflicting clause index,
        or None if no conflict."""
        while self.qhead < len(self.trail):
            p = self.trail[self.qhead]
            self.qhead += 1
            self.stats.propagations += 1
            false_lit = -p
            watchers = self.watches[false_lit]
            self.watches[false_lit] = []
            i = 0
            conflict = None
            while i < len(watchers):
                ci = watchers[i]
                clause = self.clauses[ci]
                # unit clause being watched on its only literal
                if len(clause) == 1:
                    self.watches[false_lit].append(ci)
                    i += 1
                    # clause[0] == false_lit and is now false -> conflict
                    conflict = ci
                    break
                # ensure clause[1] is the falsified watch
                if clause[0] == false_lit:
                    clause[0], clause[1] = clause[1], clause[0]
                first = clause[0]
                if self.value_lit(first) is True:
                    # already satisfied: keep watching false_lit
                    self.watches[false_lit].append(ci)
                    i += 1
                    continue
                # find a replacement watch among clause[2:]
                replaced = False
                for k in range(2, len(clause)):
                    if self.value_lit(clause[k]) is not False:
                        clause[1] = clause[k]
                        clause[k] = false_lit
                        self.watches[clause[1]].append(ci)
                        replaced = True
                        break
                if replaced:
                    i += 1
                    continue
                # no replacement: clause is unit or conflicting on `first`
                self.watches[false_lit].append(ci)
                if self.value_lit(first) is False:
                    conflict = ci
                    i += 1
                    break
                else:
                    self.enqueue(first, ci)
                    if self.record_trace:
                        self.trace.append({
                            "type": "propagate", "lit": first,
                            "reason": list(clause), "level": self.decision_level(),
                        })
                    i += 1
            if conflict is not None:
                # copy back any remaining watchers we didn't process
                while i < len(watchers):
                    self.watches[false_lit].append(watchers[i])
                    i += 1
                self.qhead = len(self.trail)
                if self.record_trace:
                    self.trace.append({"type": "conflict", "clause": list(self.clauses[conflict])})
                return conflict
        return None

    # ----- conflict analysis (1-UIP) ------------------------------------
    def analyze(self, confl: int) -> Tuple[List[int], int]:
        learnt: List[int] = [0]  # reserve slot 0 for the asserting literal
        seen = self._seen
        pathC = 0
        p = 0  # 0 means "no pivot yet" (first, conflict clause)
        index = len(self.trail) - 1
        btlevel = 0
        cur_level = self.decision_level()
        touched: List[int] = []
        while True:
            clause = self.clauses[confl]
            for q in clause:
                if q == p:
                    continue
                v = abs(q)
                if not seen[v] and self.level[v] > 0:
                    self.bump_var(v)
                    seen[v] = 1
                    touched.append(v)
                    if self.level[v] >= cur_level:
                        pathC += 1
                    else:
                        learnt.append(q)
                        if self.level[v] > btlevel:
                            btlevel = self.level[v]
            # pick the next literal to resolve: most recent on the trail that is seen
            while not seen[abs(self.trail[index])]:
                index -= 1
            p = self.trail[index]
            index -= 1
            seen[abs(p)] = 0
            confl = self.reason[abs(p)]
            pathC -= 1
            if pathC <= 0:
                break
        learnt[0] = -p  # the unique implication point, negated → asserting literal
        # clear seen
        for v in touched:
            seen[v] = 0
        self.decay_vars()
        return learnt, btlevel

    # ----- backjump ------------------------------------------------------
    def backjump(self, level: int) -> None:
        if self.decision_level() <= level:
            return
        target = self.trail_lim[level]
        while len(self.trail) > target:
            lit = self.trail.pop()
            v = abs(lit)
            self.saved_phase[v] = self.value[v]
            self.value[v] = None
            self.reason[v] = None
            self.level[v] = -1
            self.order.insert(v)
        del self.trail_lim[level:]
        self.qhead = len(self.trail)

    # ----- decisions -----------------------------------------------------
    def pick_branch(self) -> Optional[int]:
        while not self.order.empty():
            v = self.order.pop_max()
            if self.value[v] is None:
                # phase saving (default phase is False on first encounter)
                return v if self.saved_phase[v] else -v
        return None

    def new_decision_level(self) -> None:
        self.trail_lim.append(len(self.trail))

    # ----- learnt clause install ----------------------------------------
    def add_learnt(self, learnt: List[int]) -> int:
        ci = len(self.clauses)
        self.clauses.append(learnt)
        if len(learnt) == 1:
            self.watches[learnt[0]].append(ci)
        else:
            self.watches[learnt[0]].append(ci)
            self.watches[learnt[1]].append(ci)
        self.stats.learned += 1
        if self.emit_proof:
            self.proof.append(list(learnt))
        return ci

    # ----- main loop -----------------------------------------------------
    def solve(self) -> str:
        # empty clause present → trivially UNSAT
        for c in self.clauses:
            if len(c) == 0:
                self.status = UNSAT
                if self.emit_proof:
                    self.proof.append([])
                return UNSAT

        restart_no = 1
        conflicts_until_restart = self.restart_base * luby(restart_no)
        conflict_count_since_restart = 0

        # enqueue all top-level unit clauses at decision level 0
        for ci, clause in enumerate(self.clauses):
            if len(clause) == 1:
                lit = clause[0]
                cur = self.value_lit(lit)
                if cur is False:
                    self.status = UNSAT  # contradictory units
                    if self.emit_proof:
                        self.proof.append([])
                    return UNSAT
                if cur is None:
                    self.enqueue(lit, ci)
                    if self.record_trace:
                        self.trace.append({
                            "type": "propagate", "lit": lit,
                            "reason": list(clause), "level": 0,
                        })

        # initial propagation of any top-level units
        confl = self.propagate()
        if confl is not None:
            self.status = UNSAT
            if self.emit_proof:
                self.proof.append([])
            return UNSAT

        while True:
            confl = self.propagate()
            if confl is not None:
                self.stats.conflicts += 1
                conflict_count_since_restart += 1
                if self.decision_level() == 0:
                    self.status = UNSAT
                    if self.emit_proof:
                        self.proof.append([])
                    return UNSAT
                learnt, btlevel = self.analyze(confl)
                if self.record_trace:
                    self.trace.append({
                        "type": "learn",
                        "clause": list(learnt),
                        "btlevel": btlevel,
                        "uip": learnt[0],
                    })
                self.backjump(btlevel)
                if self.record_trace:
                    self.trace.append({"type": "backjump", "level": btlevel})
                ci = self.add_learnt(learnt)
                # the learnt clause is asserting at btlevel: propagate its unit
                self.enqueue(learnt[0], ci)
                if self.record_trace:
                    self.trace.append({
                        "type": "propagate", "lit": learnt[0],
                        "reason": list(learnt), "level": self.decision_level(),
                    })
                continue

            if self.max_conflicts is not None and self.stats.conflicts >= self.max_conflicts:
                self.status = None
                return "UNKNOWN"

            # restart?
            if conflict_count_since_restart >= conflicts_until_restart:
                self.stats.restarts += 1
                self.backjump(0)
                restart_no += 1
                conflicts_until_restart = self.restart_base * luby(restart_no)
                conflict_count_since_restart = 0
                if self.record_trace:
                    self.trace.append({"type": "restart"})
                continue

            lit = self.pick_branch()
            if lit is None:
                # all variables assigned and no conflict → SAT
                self.status = SAT
                if self.record_trace:
                    self.trace.append({"type": "sat", "model": self.model()})
                return SAT
            self.stats.decisions += 1
            self.new_decision_level()
            self.enqueue(lit, None)
            if self.decision_level() > self.stats.max_depth:
                self.stats.max_depth = self.decision_level()
            if self.record_trace:
                self.trace.append({
                    "type": "decision", "lit": lit, "level": self.decision_level(),
                    "activity": [round(self.activity[v], 6) for v in range(1, self.n + 1)],
                })

    # ----- results -------------------------------------------------------
    def model(self) -> List[int]:
        """Return the model as a list of signed literals (one per variable)."""
        out = []
        for v in range(1, self.n + 1):
            val = self.value[v]
            if val is None:
                val = False  # free variable: any value works; pick False
            out.append(v if val else -v)
        return out

    def value_map(self) -> Dict[int, bool]:
        return {v: (self.value[v] if self.value[v] is not None else False)
                for v in range(1, self.n + 1)}
