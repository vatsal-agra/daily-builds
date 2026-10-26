"""Ambiguity witnesses: find a concrete sentence of the grammar that has two parse trees.

Sentences are enumerated shortest-first by expanding the leftmost nonterminal of sentential
forms (best-first on the minimal terminal length they can still reach); each fully terminal
sentence is checked with the Earley parser, which counts its parses exactly. No ambiguity
found within the budget proves nothing — an honest "not found" is reported."""
from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .analysis import Analysis
from .earley import EarleyParser
from .grammar import END, Grammar
from .lexer import Token
from .tree import Node


@dataclass
class Witness:
    sentence: List[str]          # display text per token
    parses: float
    trees: List[Node]

    def text(self) -> str:
        return " ".join(self.sentence) or "ε (the empty input)"


def find_ambiguity(g: Grammar, max_len: int = 10, budget: int = 40000,
                   an: Optional[Analysis] = None, want_trees: int = 2) -> Optional[Witness]:
    an = an or Analysis(g)
    shortest = an.shortest()
    if g.start not in shortest:
        return None
    minlen = {s: len(v) for s, v in shortest.items()}
    ep = EarleyParser(g, an)
    heap: List[Tuple[int, int, tuple]] = [(minlen[g.start], 0, (g.start,))]
    seen = {(g.start,)}
    tick, tested = 0, set()
    while heap and budget > 0:
        _, _, form = heapq.heappop(heap)
        budget -= 1
        idx = next((i for i, s in enumerate(form) if s not in ep.terminals), None)
        if idx is None:
            if form in tested:
                continue
            tested.add(form)
            toks = [Token(t, g.literals.get(t, t), 1, i + 1) for i, t in enumerate(form)]
            toks.append(Token(END, "", 1, len(form) + 1))
            try:
                res = ep.parse(toks)
            except Exception:
                continue
            n = res.count()
            if n > 1:
                return Witness([t.text for t in toks[:-1]], n, res.trees(want_trees))
            continue
        for p in g.by_lhs[form[idx]]:
            new = form[:idx] + p.rhs + form[idx + 1:]
            if new in seen:
                continue
            est = sum(minlen.get(s, 1) if s not in ep.terminals else 1 for s in new)
            if est > max_len:
                continue
            seen.add(new)
            tick += 1
            heapq.heappush(heap, (est, tick, new))
    return None
