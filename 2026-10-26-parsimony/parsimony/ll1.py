"""LL(1) predictive table, conflict report and table-driven top-down parser."""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from typing import Dict, List, Optional, Tuple

from .analysis import Analysis
from .grammar import END, Grammar, GrammarError
from .lexer import Token
from .lr import ParseError, TraceRow, _syntax_msg
from .tree import Node, flatten_children


@dataclass
class LL1Conflict:
    kind: str                     # 'FIRST/FIRST' or 'FIRST/FOLLOW'
    nonterminal: str
    terminal: str
    productions: List[int]


class LL1Table:
    def __init__(self, g: Grammar):
        self.g = g
        self.table: Dict[Tuple[str, str], List[int]] = defaultdict(list)
        self.conflicts: List[LL1Conflict] = []

    def row(self, nt: str) -> Dict[str, List[int]]:
        return {t: ps for (n, t), ps in self.table.items() if n == nt}

    def dump(self) -> str:
        g = self.g
        out = []
        for nt in g.nonterminals:
            if nt in g.hidden:
                continue
            row = self.row(nt)
            if not row:
                continue
            out.append(f"{nt}")
            for t in sorted(row):
                alts = " | ".join(str(g.productions[i]) + (" ⚠" if len(row[t]) > 1 else "") for i in row[t])
                out.append(f"    {t:<10} → {alts}")
        out.append("")
        if not self.conflicts:
            out.append("LL(1): no conflicts")
        else:
            out.append(f"LL(1): {len(self.conflicts)} conflict(s)")
            for c in self.conflicts:
                alts = "; ".join(str(g.productions[i]) for i in c.productions)
                out.append(f"  {c.kind} on {c.terminal} for {c.nonterminal}: {alts}")
            lr = Analysis(g).left_recursive()
            if any(not all(x in g.hidden for x in comp) for comp in lr):
                out.append("  hint: the grammar is left-recursive — try `parsimony transform`")
        return "\n".join(out)


def build_ll1(g: Grammar, an: Optional[Analysis] = None) -> LL1Table:
    an = an or Analysis(g)
    t = LL1Table(g)
    for p in g.productions:
        first, null = an.first_of(p.rhs)
        for a in first:
            t.table[(p.lhs, a)].append(p.index)
        if null:
            for a in an.follow[p.lhs]:
                t.table[(p.lhs, a)].append(p.index)
    for (nt, a), ps in sorted(t.table.items()):
        ps[:] = sorted(set(ps))
        if len(ps) > 1:
            nullable_alt = any(an.first_of(g.productions[i].rhs)[1] for i in ps)
            t.conflicts.append(LL1Conflict("FIRST/FOLLOW" if nullable_alt else "FIRST/FIRST", nt, a, ps))
    return t


class LL1Parser:
    def __init__(self, g: Grammar, an: Optional[Analysis] = None):
        self.g = g
        self.t = build_ll1(g, an)
        if self.t.conflicts:
            raise GrammarError(f"grammar is not LL(1): {len(self.t.conflicts)} conflict(s) "
                               f"(first: {self.t.conflicts[0].kind} on {self.t.conflicts[0].terminal} "
                               f"for {self.t.conflicts[0].nonterminal}); see `ll1` / `transform`")
        self.terminals = set(g.terminals) | {END}

    def parse(self, tokens: List[Token], trace: Optional[List[TraceRow]] = None) -> Node:
        g = self.g
        root = Node(g.start, [])
        order = [root]
        stack: List = [(END, None, 0), (g.start, root, 0)]      # top is the end of the list
        pos, step = 0, 0
        while stack:
            sym, node, slot = stack.pop()
            tok = tokens[pos]
            if sym in self.terminals:
                if sym != tok.type:
                    exp = sorted({sym})
                    raise ParseError(_syntax_msg(tok, exp), tok, exp)
                if trace is not None:
                    step += 1
                    trace.append(TraceRow(step, self._stack_str(stack + [(sym, None, 0)]), tok.type, f"match {tok.type}"))
                if node is not None:
                    node.children[slot] = tok
                pos += 1
                continue
            alts = self.t.table.get((sym, tok.type))
            if not alts:
                exp = sorted(t for (n, t) in self.t.table if n == sym)
                raise ParseError(_syntax_msg(tok, exp), tok, exp)
            p = g.productions[alts[0]]
            if trace is not None:
                step += 1
                trace.append(TraceRow(step, self._stack_str(stack + [(sym, None, 0)]), tok.type, f"predict {p}"))
            kids = []
            for s in p.rhs:
                if s in self.terminals:
                    kids.append((s, node, len(node.children)))
                    node.children.append(None)           # filled when the token is matched
                else:
                    n = Node(s, [])
                    kids.append((s, n, 0))
                    node.children.append(n); order.append(n)
            stack.extend(reversed(kids))
        for n in order:
            if n.name not in g.hidden:
                n.children = flatten_children(n.children, g.hidden)
        return root

    @staticmethod
    def _stack_str(stack) -> str:
        return " ".join(e[0] for e in reversed(stack))
