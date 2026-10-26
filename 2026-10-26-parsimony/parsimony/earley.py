"""Earley parser for arbitrary context-free grammars with a shared derivation forest.

Handles ε-rules and left/right/hidden recursion. Derivations are recorded as
back-pointers, so the parser can *count* parses, *enumerate* them, report the minimal
ambiguous spans, and detect infinite ambiguity (A ⇒+ A cycles).
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from itertools import islice
from typing import Dict, Iterator, List, Optional, Set, Tuple, Union

from .analysis import Analysis
from .grammar import END, Grammar
from .lexer import Token
from .lr import ParseError, _syntax_msg
from .tree import Node, flatten_children
from .util import run_deep

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
        return run_deep(lambda: sum(self._count_item(r, self.n) for r in self.roots))

    # ---- enumeration ----------------------------------------------------
    def trees(self, limit: int = 10) -> List[Node]:
        if limit == 1 and not self.parser.cyclic and self.roots:
            return [self._first_tree()]
        return run_deep(lambda: list(islice(self._root_trees(), limit)))

    def _first_tree(self) -> Node:
        """Iteratively build the canonical (first-in-order) tree; no recursion, linear time.

        Matches the first tree of the generator-based enumeration, so deep inputs such as a
        20 000-term left-recursive sum are handled without touching the recursion limit."""
        g = self.parser.g
        root_item = min(self.roots)
        root = Node(g.productions[root_item[0]].lhs, [])
        order, work = [root], [(root, root_item, self.n)]
        while work:
            node, (pi, dot, origin), pos = work.pop()
            kids = []
            while dot > 0:
                k, child = min(self.charts[pos].deriv[(pi, dot, origin)], key=lambda d: (d[0], d[1] or ()))
                if child is None:
                    kids.append(self.tokens[pos - 1])
                else:
                    sub = Node(g.productions[child[0]].lhs, [])
                    kids.append(sub); order.append(sub); work.append((sub, child, pos))
                dot -= 1; pos = k
            kids.reverse()
            node.children = kids
        for node in order:
            if node.name not in g.hidden:
                node.children = flatten_children(node.children, g.hidden)
        return root

    def _root_trees(self) -> Iterator[Node]:
        for r in sorted(self.roots):
            yield from self._tree_of(r, self.n, frozenset())

    def _tree_of(self, item: Item, end: int, stack) -> Iterator[Node]:
        if self.parser.cyclic:                # only cyclic grammars can loop; the check is O(depth)
            key = (item, end)
            if key in stack:                  # skip cyclic re-entry → finite sample
                return
            stack = stack | {key}
        hidden = self.parser.g.hidden
        lhs = self.parser.g.productions[item[0]].lhs
        for cell in self._seq(item, end, stack):
            kids = []
            while cell is not None:           # cons-list → list (keeps long sequences O(n))
                cell, v = cell
                kids.append(v)
            kids.reverse()
            if lhs not in hidden:
                kids = flatten_children(kids, hidden)
            yield Node(lhs, kids)

    def _seq(self, item: Item, end: int, stack) -> Iterator[Optional[tuple]]:
        """Yield derivations of ``rhs[:dot]`` over origin..end as cons cells ``(prev, child)``."""
        pi, dot, origin = item
        if dot == 0:
            yield None
            return
        for k, child in sorted(self.charts[end].deriv[item], key=lambda d: (d[0], d[1] or ())):
            for left in self._seq((pi, dot - 1, origin), k, stack):
                if child is None:
                    yield (left, self.tokens[end - 1])
                else:
                    for sub in self._tree_of(child, end, stack):
                        yield (left, sub)

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
        self.cyclic = bool(self.an.cyclic())

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
                    waiters = charts[origin].waiting.get(p.lhs, ())
                    for parent in (list(waiters) if origin == i else waiters):
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
