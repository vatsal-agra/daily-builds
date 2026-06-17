"""`explain` / anatomy mode: capture one conflict's implication graph and the
1-UIP analysis, then render it as human-readable ASCII.

A tracer is attached to a Solver (solver.tracer = ...). The solver calls
on_decision / on_conflict / on_learnt as it runs; we snapshot the implication
graph at the chosen conflict (while the trail is still intact) and the learned
clause produced from it.
"""
from __future__ import annotations

from typing import List, Optional, Dict


def _lit(l: int) -> str:
    return f"x{l}" if l > 0 else f"¬x{-l}"


class ExplainTracer:
    def __init__(self, target_conflict: int = 1):
        self.target = target_conflict
        self.conflict_no = 0
        self.captured = False
        self.graph = None        # {nodes, edges, conflict_clause}
        self.learnt = None
        self.bt = None
        self.decisions_before: List[int] = []

    def on_decision(self, solver, lit):
        if not self.captured:
            self.decisions_before.append(lit)

    def on_conflict(self, solver, confl):
        self.conflict_no += 1
        if self.captured or self.conflict_no != self.target:
            return
        self.graph = self._snapshot(solver, confl)

    def on_learnt(self, solver, learnt, bt):
        if self.captured or self.graph is None or self.learnt is not None:
            return
        if self.conflict_no == self.target:
            self.learnt = list(learnt)
            self.bt = bt
            self.captured = True

    # build the implication-graph cone feeding the conflict
    def _snapshot(self, s, confl) -> Dict:
        nodes: Dict[int, dict] = {}
        edges = []

        def add(lit):
            v = abs(lit)
            if v not in nodes:
                cur = v if s.val[v] else -v
                nodes[v] = {"lit": cur, "level": s.level[v],
                            "decision": s.reason[v] is None}

        from collections import deque
        q = deque()
        for l in s.clauses[confl]:
            add(l)
            edges.append((-l, "K"))
            q.append(abs(l))
        seen = set()
        while q:
            v = q.popleft()
            if v in seen:
                continue
            seen.add(v)
            r = s.reason[v]
            if r is None:
                continue
            implied = s.clauses[r][0]
            for qd in s.clauses[r]:
                if abs(qd) == v:
                    continue
                add(qd)
                edges.append((-qd, implied))
                q.append(abs(qd))
        return {"nodes": list(nodes.values()), "edges": edges,
                "conflict_clause": list(s.clauses[confl])}

    # ---- ASCII rendering -------------------------------------------------
    def render(self) -> str:
        if not self.captured:
            return ("(no conflict captured — the instance was solved without "
                    "reaching conflict #%d)" % self.target)
        g = self.graph
        out = []
        out.append(f"Conflict #{self.target} anatomy")
        out.append("=" * 52)
        out.append(f"Conflicting clause : {_clause(g['conflict_clause'])}")
        out.append("")
        # group nodes by level
        by_level: Dict[int, List[dict]] = {}
        for n in g["nodes"]:
            by_level.setdefault(n["level"], []).append(n)
        out.append("Implication graph (assignments that forced the conflict):")
        for lvl in sorted(by_level):
            chips = []
            for n in sorted(by_level[lvl], key=lambda x: abs(x["lit"])):
                tag = "decision" if n["decision"] else "implied"
                chips.append(f"{_lit(n['lit'])}[{tag}]")
            out.append(f"  level {lvl}: " + "  ".join(chips))
        out.append("")
        # edges grouped by target
        out.append("Reason edges (antecedent ⇒ consequent):")
        by_to: Dict[str, List[int]] = {}
        for frm, to in g["edges"]:
            key = "κ (conflict)" if to == "K" else _lit(to)
            by_to.setdefault(key, []).append(frm)
        for to, froms in by_to.items():
            src = ", ".join(_lit(f) for f in sorted(set(froms), key=abs))
            out.append(f"  {src}  ⇒  {to}")
        out.append("")
        uip = -self.learnt[0]
        out.append(f"1-UIP (the single dominator at the conflict level): {_lit(uip)}")
        out.append(f"Learned clause : {_clause(self.learnt)}")
        out.append(f"Backjump level : {self.bt}")
        out.append("")
        out.append("Reading it: every path from a decision to κ passes through the")
        out.append("1-UIP, so negating the conflict side gives a clause that forbids")
        out.append("this whole mistake — and we jump straight back to where it bites.")
        return "\n".join(out)


def _clause(c: List[int]) -> str:
    if not c:
        return "⊥ (empty clause)"
    return "(" + " ∨ ".join(_lit(l) for l in c) + ")"
