"""Static grammar analysis: nullable, FIRST, FOLLOW, useless symbols, left recursion,
cycles and shortest terminal derivations."""
from __future__ import annotations

from typing import Dict, Iterable, List, Set, Tuple

from .grammar import END, Grammar


class Analysis:
    def __init__(self, g: Grammar):
        self.g = g
        self.nullable: Set[str] = set()
        self.first: Dict[str, Set[str]] = {}
        self.follow: Dict[str, Set[str]] = {}
        self._nullable_fixpoint()
        self._first_fixpoint()
        self._follow_fixpoint()

    # -- core sets
    def _nullable_fixpoint(self):
        g, changed = self.g, True
        while changed:
            changed = False
            for p in g.productions:
                if p.lhs not in self.nullable and all(s in self.nullable for s in p.rhs):
                    self.nullable.add(p.lhs); changed = True

    def _first_fixpoint(self):
        g = self.g
        for t in g.terminals:
            self.first[t] = {t}
        self.first[END] = {END}
        for nt in g.nonterminals:
            self.first[nt] = set()
        changed = True
        while changed:
            changed = False
            for p in g.productions:
                f = self.first[p.lhs]
                before = len(f)
                for s in p.rhs:
                    f |= self.first[s]
                    if s not in self.nullable:
                        break
                changed |= len(f) != before

    def first_of(self, seq: Iterable[str]) -> Tuple[Set[str], bool]:
        """FIRST of a symbol string and whether the whole string is nullable."""
        out: Set[str] = set()
        for s in seq:
            out |= self.first[s]
            if s not in self.nullable:
                return out, False
        return out, True

    def _follow_fixpoint(self):
        g = self.g
        for nt in g.nonterminals:
            self.follow[nt] = set()
        self.follow[g.start].add(END)
        changed = True
        while changed:
            changed = False
            for p in g.productions:
                for i, s in enumerate(p.rhs):
                    if s not in self.follow:
                        continue
                    f, null = self.first_of(p.rhs[i + 1:])
                    tgt = self.follow[s]
                    before = len(tgt)
                    tgt |= f
                    if null:
                        tgt |= self.follow[p.lhs]
                    changed |= len(tgt) != before

    # -- structural diagnostics
    def non_productive(self) -> List[str]:
        g, prod = self.g, set(self.g.terminals)
        changed = True
        while changed:
            changed = False
            for p in g.productions:
                if p.lhs not in prod and all(s in prod for s in p.rhs):
                    prod.add(p.lhs); changed = True
        return [nt for nt in g.nonterminals if nt not in prod]

    def unreachable(self) -> List[str]:
        g, seen, stack = self.g, {self.g.start}, [self.g.start]
        while stack:
            for p in g.by_lhs.get(stack.pop(), []):
                for s in p.rhs:
                    if s not in seen:
                        seen.add(s); stack.append(s)
        return [s for s in g.nonterminals + g.terminals if s not in seen]

    def _graph_cycles(self, edges: Dict[str, Set[str]]) -> List[List[str]]:
        """Strongly connected components (Tarjan) that contain a cycle."""
        index, low, on, stack, sccs, counter = {}, {}, set(), [], [], [0]

        def visit(v):
            index[v] = low[v] = counter[0]; counter[0] += 1
            stack.append(v); on.add(v)
            for w in sorted(edges.get(v, ())):
                if w not in index:
                    visit(w); low[v] = min(low[v], low[w])
                elif w in on:
                    low[v] = min(low[v], index[w])
            if low[v] == index[v]:
                comp = []
                while True:
                    w = stack.pop(); on.discard(w); comp.append(w)
                    if w == v: break
                if len(comp) > 1 or v in edges.get(v, ()):
                    sccs.append(sorted(comp))

        for v in sorted(edges):
            if v not in index:
                visit(v)
        return sccs

    def left_recursive(self) -> List[List[str]]:
        """Groups of nonterminals that can derive a sentential form starting with themselves."""
        edges: Dict[str, Set[str]] = {nt: set() for nt in self.g.nonterminals}
        for p in self.g.productions:
            for s in p.rhs:
                if s in edges:
                    edges[p.lhs].add(s)
                if s not in self.nullable:
                    break
        return self._graph_cycles(edges)

    def cyclic(self) -> List[List[str]]:
        """A =>+ A derivations: such grammars have infinitely many parse trees."""
        edges: Dict[str, Set[str]] = {nt: set() for nt in self.g.nonterminals}
        for p in self.g.productions:
            for i, s in enumerate(p.rhs):
                if s in edges and all(x in self.nullable for x in p.rhs[:i] + p.rhs[i + 1:]):
                    edges[p.lhs].add(s)
        return self._graph_cycles(edges)

    # -- shortest terminal yields (used to print concrete conflict examples)
    def shortest(self) -> Dict[str, List[str]]:
        g = self.g
        best: Dict[str, List[str]] = {t: [t] for t in g.terminals}
        best[END] = []
        changed = True
        while changed:
            changed = False
            for p in g.productions:
                if all(s in best for s in p.rhs):
                    cand = [x for s in p.rhs for x in best[s]]
                    cur = best.get(p.lhs)
                    if cur is None or len(cand) < len(cur):
                        best[p.lhs] = cand; changed = True
        return best

    def report(self) -> str:
        g = self.g
        vis = [nt for nt in g.nonterminals if nt not in g.hidden]
        fmt = lambda s: "{" + ", ".join(sorted(s)) + "}"
        lines = [f"start symbol : {g.start}",
                 f"terminals    : {len(g.terminals)}   nonterminals: {len(vis)} "
                 f"(+{len(g.hidden)} EBNF helpers)   productions: {len(g.productions)}"]
        lines.append(f"nullable     : {', '.join(sorted(n for n in self.nullable if n not in g.hidden)) or '—'}")
        lines.append("")
        lines.append(f"{'symbol':<14} {'FIRST':<38} FOLLOW")
        for nt in g.nonterminals:
            if nt in g.hidden:
                continue
            lines.append(f"{nt:<14} {fmt(self.first[nt]):<38} {fmt(self.follow[nt])}")
        lines.append("")
        issues = []
        if (np := self.non_productive()):
            issues.append(f"non-productive nonterminals (derive no string): {', '.join(np)}")
        un = [u for u in self.unreachable() if u not in g.hidden]
        if un:
            issues.append(f"unreachable symbols: {', '.join(un)}")
        for comp in self.left_recursive():
            issues.append("left recursion: " + " ⇒ ".join(comp))
        for comp in self.cyclic():
            issues.append("cyclic derivation (A ⇒+ A, infinitely ambiguous): " + ", ".join(comp))
        lines.append("diagnostics  : " + ("none" if not issues else ""))
        lines += [f"  - {i}" for i in issues]
        return "\n".join(lines)
