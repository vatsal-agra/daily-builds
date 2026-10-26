"""Earley parser for arbitrary context-free grammars with a shared derivation forest.

Handles ε-rules and left/right/hidden recursion. Derivations are recorded as
back-pointers, so the parser can *count* parses, *enumerate* them, report the minimal
ambiguous spans, and detect infinite ambiguity (A ⇒+ A cycles).
"""
from __future__ import annotations

import sys
from collections import defaultdict
from dataclasses import dataclass
from itertools import islice
from typing import Dict, Iterator, List, Optional, Set, Tuple, Union

from .analysis import Analysis
from .grammar import END, Grammar
from .lexer import Token
from .lr import ParseError, _syntax_msg
from .tree import Node, flatten_children

Item = Tuple[int, int, int]           # (production, dot, origin)
INF = float("inf")


class _Chart:
    __slots__ = ("items", "seen", "waiting", "empty_done", "deriv")

    def __init__(self):
        self.items: List[Item] = []
        self.seen: Set[Item] = set()
        self.waiting: Dict[str, List[Item]] = defaultdict(list)
        self.empty_done: Dict[str, List[Item]] = defaultdict(list)
        self.deriv: Dict[Item, Set[Tuple[int, Optional[Item]]]] = defaultdict(set)


class EarleyResult:
    def __init__(self, parser: "EarleyParser", tokens: List[Token], charts: List[_Chart]):
        self.parser, self.tokens, self.charts = parser, tokens, charts
        n = len(tokens) - 1
        self.n = n
        g = parser.g
        self.roots = [it for it in charts[n].items
                      if it[2] == 0 and it[1] == len(g.productions[it[0]].rhs)
                      and g.productions[it[0]].lhs == g.start]
        self._memo: Dict[Tuple[Item, int], float] = {}
        self._active: Set[Tuple[Item, int]] = set()

    @property
    def accepted(self) -> bool:
        return bool(self.roots)

    # ---- counting -------------------------------------------------------
    def _count_item(self, item: Item, end: int) -> float:
        key = (item, end)
        if key in self._memo:
            return self._memo[key]
        if key in self._active:
            return INF
        pi, dot, origin = item
        if dot == 0:
            return 1
        self._active.add(key)
        total = 0
        for k, child in self.charts[end].deriv[item]:
            left = self._count_item((pi, dot - 1, origin), k)
            right = 1 if child is None else self._count_item(child, end)
            total += left * right
        self._active.discard(key)
        # a result computed while some ancestor was mid-flight and hit INF is itself INF
        self._memo[key] = total
        return total

    def count(self) -> float:
        """Number of distinct parse trees (``inf`` when the grammar is cyclic on this input)."""
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old, 200000))
        try:
            return sum(self._count_item(r, self.n) for r in self.roots)
        finally:
            sys.setrecursionlimit(old)

    # ---- enumeration ----------------------------------------------------
    def trees(self, limit: int = 10) -> List[Node]:
        old = sys.getrecursionlimit()
        sys.setrecursionlimit(max(old, 200000))
        try:
            return list(islice(self._root_trees(), limit))
        finally:
            sys.setrecursionlimit(old)

    def _root_trees(self) -> Iterator[Node]:
        for r in sorted(self.roots):
            yield from self._tree_of(r, self.n, frozenset())

    def _tree_of(self, item: Item, end: int, stack) -> Iterator[Node]:
        key = (item, end)
        if key in stack:                      # skip cyclic re-entry → finite sample
            return
        stack = stack | {key}
        p = self.parser.g.productions[item[0]]
        for kids in self._seq(item, end, stack):
            if p.lhs not in self.parser.g.hidden:
                kids = flatten_children(kids, self.parser.g.hidden)
            yield Node(p.lhs, list(kids))

    def _seq(self, item: Item, end: int, stack) -> Iterator[list]:
        pi, dot, origin = item
        if dot == 0:
            yield []
            return
        for k, child in sorted(self.charts[end].deriv[item], key=lambda d: (d[0], d[1] or ())):
            if child is None:
                tok = self.tokens[end - 1]
                for left in self._seq((pi, dot - 1, origin), k, stack):
                    yield left + [tok]
            else:
                for left in self._seq((pi, dot - 1, origin), k, stack):
                    for sub in self._tree_of(child, end, stack):
                        yield left + [sub]

    # ---- ambiguity ------------------------------------------------------
    def ambiguities(self) -> List[str]:
        """Minimal ambiguous spans: nonterminal groups with more than one *local* derivation."""
        groups: Dict[Tuple[str, int, int], Set[tuple]] = defaultdict(set)
        g = self.parser.g
        for end, ch in enumerate(self.charts):
            for item in ch.items:
                pi, dot, origin = item
                if dot != len(g.productions[pi].rhs) or end < origin:
                    continue
                p = g.productions[pi]
                for k, child in ch.deriv.get(item, ()):
                    groups[(p.lhs, origin, end)].add((pi, k, child))
                if dot == 0:
                    groups[(p.lhs, origin, end)].add((pi, None, None))
        out = []
        for (lhs, o, e), recs in sorted(groups.items(), key=lambda kv: (kv[0][2] - kv[0][1], kv[0])):
            if len(recs) > 1 and lhs not in g.hidden:
                text = " ".join(t.text for t in self.tokens[o:e]) or "ε"
                out.append(f"{lhs} over tokens [{o}:{e}] \"{text}\" can be derived {len(recs)} different ways")
        return out


class EarleyParser:
    def __init__(self, grammar: Grammar, analysis: Optional[Analysis] = None):
        self.g = grammar
        self.an = analysis or Analysis(grammar)
        self.terminals = set(grammar.terminals) | {END}

    def parse(self, tokens: List[Token]) -> EarleyResult:
        g = self.g
        toks = tokens
        n = len(toks) - 1                      # last token is $end
        charts = [_Chart() for _ in range(n + 1)]
        for p in g.by_lhs[g.start]:
            self._add(charts, 0, (p.index, 0, 0), None)
        for i in range(n + 1):
            ch = charts[i]
            idx = 0
            while idx < len(ch.items):
                item = ch.items[idx]; idx += 1
                pi, dot, origin = item
                p = g.productions[pi]
                if dot == len(p.rhs):
                    if origin == i:
                        ch.empty_done[p.lhs].append(item)
                    for parent in list(charts[origin].waiting.get(p.lhs, ())):
                        self._add(charts, i, (parent[0], parent[1] + 1, parent[2]), (origin, item))
                else:
                    sym = p.rhs[dot]
                    if sym not in self.terminals:
                        for q in g.by_lhs[sym]:
                            self._add(charts, i, (q.index, 0, i), None)
            if i < n:
                tok = toks[i].type
                for item in ch.items:
                    p = g.productions[item[0]]
                    if item[1] < len(p.rhs) and p.rhs[item[1]] == tok:
                        self._add(charts, i + 1, (item[0], item[1] + 1, item[2]), (i, None))
                if not charts[i + 1].items:
                    exp = sorted({g.productions[it[0]].rhs[it[1]] for it in ch.items
                                  if it[1] < len(g.productions[it[0]].rhs)
                                  and g.productions[it[0]].rhs[it[1]] in self.terminals})
                    raise ParseError(_syntax_msg(toks[i], exp), toks[i], exp)
        res = EarleyResult(self, toks, charts)
        if not res.accepted:
            last = charts[n]
            exp = sorted({g.productions[it[0]].rhs[it[1]] for it in last.items
                          if it[1] < len(g.productions[it[0]].rhs)
                          and g.productions[it[0]].rhs[it[1]] in self.terminals})
            raise ParseError(_syntax_msg(toks[n], exp), toks[n], exp)
        return res

    def _add(self, charts, i: int, item: Item, deriv):
        ch = charts[i]
        if deriv is not None:
            ch.deriv[item].add(deriv)
        if item in ch.seen:
            return
        ch.seen.add(item); ch.items.append(item)
        p = self.g.productions[item[0]]
        if item[1] < len(p.rhs):
            sym = p.rhs[item[1]]
            ch.waiting[sym].append(item)
            for done in ch.empty_done.get(sym, ()):
                self._add(charts, i, (item[0], item[1] + 1, item[2]), (i, done))
