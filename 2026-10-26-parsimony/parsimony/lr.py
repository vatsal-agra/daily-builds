"""LR(0) / SLR(1) / LALR(1) / canonical LR(1) table construction and the shift-reduce driver."""
from __future__ import annotations

from collections import defaultdict, deque
from dataclasses import dataclass, field
from typing import Dict, FrozenSet, List, Optional, Set, Tuple

from .analysis import Analysis
from .grammar import ACCEPT, END, Grammar, Production
from .lexer import Token
from .tree import Node, flatten_children

METHODS = ("lr0", "slr", "lalr", "lr1")
Core = Tuple[int, int]  # (production index, dot position)
DUMMY = "#"


class ParseError(Exception):
    def __init__(self, msg, token: Optional[Token] = None, expected: Optional[List[str]] = None):
        self.token, self.expected = token, expected or []
        super().__init__(msg)


@dataclass
class Conflict:
    kind: str                 # 'shift/reduce' or 'reduce/reduce'
    state: int
    terminal: str
    reduces: List[int]        # augmented production indices
    shift_to: Optional[int]
    resolved_as: str          # what the table does by default
    example: str

    def short(self) -> str:
        return f"state {self.state}: {self.kind} on {self.terminal}"


@dataclass
class LRTable:
    method: str
    grammar: Grammar
    prods: List[Production]
    kernels: List[List[Core]]
    trans: List[Dict[str, int]]
    action: List[Dict[str, tuple]]
    goto: List[Dict[str, int]]
    conflicts: List[Conflict] = field(default_factory=list)
    resolved: List[str] = field(default_factory=list)   # conflicts settled by precedence
    closures: List[Dict[Core, Set[str]]] = field(default_factory=list)

    @property
    def n_states(self) -> int:
        return len(self.kernels)

    @property
    def is_deterministic(self) -> bool:
        return not self.conflicts

    # ---- display helpers
    def item_str(self, core: Core, las: Optional[Set[str]] = None) -> str:
        p = self.prods[core[0]]
        rhs = list(p.rhs)
        rhs.insert(core[1], "•")
        s = f"{p.lhs} -> {' '.join(rhs)}"
        if las and self.method in ("lalr", "lr1"):
            s += "   [" + ", ".join(sorted(las)) + "]"
        return s

    def dump_states(self) -> str:
        out = [f"{self.method.upper()} automaton: {self.n_states} states, "
               f"{len(self.conflicts)} unresolved conflicts, {len(self.resolved)} resolved by precedence\n"]
        for s in range(self.n_states):
            out.append(f"state {s}")
            kern = set(self.kernels[s])
            for core in sorted(self.closures[s], key=lambda c: (c not in kern, c)):
                out.append(f"    {self.item_str(core, self.closures[s][core])}")
            for t, a in sorted(self.action[s].items()):
                out.append(f"    {t:<12} {_act_str(a)}")
            for nt, tgt in sorted(self.goto[s].items()):
                if nt not in self.grammar.hidden:
                    out.append(f"    {nt:<12} goto {tgt}")
            out.append("")
        return "\n".join(out)

    def action_grid(self) -> str:
        terms = [t for t in self.grammar.terminals] + [END]
        nts = [n for n in self.grammar.nonterminals if n not in self.grammar.hidden]
        gotos_nts = [n for n in self.grammar.nonterminals if any(n in g for g in self.goto)]
        cols = terms + gotos_nts
        w = max(6, max(len(c) for c in cols) + 1)
        head = "state".ljust(6) + "".join(c.rjust(w) for c in cols)
        rows = [head, "-" * len(head)]
        for s in range(self.n_states):
            cells = []
            for c in terms:
                a = self.action[s].get(c)
                cells.append(_act_str(a, short=True) if a else "")
            for n in gotos_nts:
                cells.append(str(self.goto[s][n]) if n in self.goto[s] else "")
            rows.append(str(s).ljust(6) + "".join(x.rjust(w) for x in cells))
        return "\n".join(rows)

    def conflict_report(self) -> str:
        if not self.conflicts:
            note = f" ({len(self.resolved)} resolved by precedence)" if self.resolved else ""
            return f"{self.method.upper()}: no conflicts{note}"
        out = [f"{self.method.upper()}: {len(self.conflicts)} conflict(s)"]
        for c in self.conflicts:
            out.append(f"  {c.short()}")
            out.append(f"      after reading:  {c.example}")
            if c.shift_to is not None:
                for core, _ in self._items_shifting(c.state, c.terminal):
                    out.append(f"      shift  item:    {self.item_str(core)}")
            for r in c.reduces:
                out.append(f"      reduce item:    {self.prods[r].lhs} -> "
                           f"{' '.join(self.prods[r].rhs) or 'ε'} •")
            out.append(f"      default:        {c.resolved_as}")
        return "\n".join(out)

    def _items_shifting(self, state, term):
        for core in self.closures[state]:
            p = self.prods[core[0]]
            if core[1] < len(p.rhs) and p.rhs[core[1]] == term:
                yield core, p


def _act_str(a, short=False) -> str:
    if a[0] == "s": return f"s{a[1]}" if short else f"shift {a[1]}"
    if a[0] == "r": return f"r{a[1]}" if short else f"reduce {a[1]}"
    return "acc" if short else "accept"


# ===================================================================== construction

class _Builder:
    def __init__(self, g: Grammar, method: str, an: Optional[Analysis]):
        if method not in METHODS:
            raise ValueError(f"unknown LR method {method!r}; choose from {METHODS}")
        self.g, self.method = g, method
        self.an = an or Analysis(g)
        self.prods = [Production(0, ACCEPT, (g.start,))] + [
            Production(p.index + 1, p.lhs, p.rhs, p.prec) for p in g.productions]
        self.by_lhs: Dict[str, List[int]] = defaultdict(list)
        for p in self.prods:
            self.by_lhs[p.lhs].append(p.index)
        self._first_cache: Dict[Core, Tuple[Set[str], bool]] = {}
        self.terminals = set(g.terminals) | {END}

    def rhs_after(self, core: Core):
        p = self.prods[core[0]]
        return p.rhs[core[1]] if core[1] < len(p.rhs) else None

    def beta_first(self, core: Core):
        r = self._first_cache.get(core)
        if r is None:
            p = self.prods[core[0]]
            r = self.an.first_of(p.rhs[core[1] + 1:])
            self._first_cache[core] = r
        return r

    # -- closures
    def closure0(self, kernel) -> List[Core]:
        out, seen, work = [], set(), list(kernel)
        while work:
            c = work.pop()
            if c in seen: continue
            seen.add(c); out.append(c)
            x = self.rhs_after(c)
            if x is not None and x in self.by_lhs:
                work.extend((q, 0) for q in self.by_lhs[x])
        return out

    def closure1(self, items: Dict[Core, Set[str]]) -> Dict[Core, Set[str]]:
        res = {c: set(l) for c, l in items.items()}
        work = deque(res)
        while work:
            c = work.popleft()
            x = self.rhs_after(c)
            if x is None or x not in self.by_lhs:
                continue
            f, null = self.beta_first(c)
            la = set(f) | (res[c] if null else set())
            for q in self.by_lhs[x]:
                tgt = res.setdefault((q, 0), set())
                if not la <= tgt:
                    tgt |= la; work.append((q, 0))
        return res

    # -- automata
    def build_lr0(self):
        start = frozenset([(0, 0)])
        index = {start: 0}
        kernels, trans = [start], [{}]
        i = 0
        while i < len(kernels):
            groups: Dict[str, List[Core]] = defaultdict(list)
            for c in self.closure0(kernels[i]):
                x = self.rhs_after(c)
                if x is not None:
                    groups[x].append((c[0], c[1] + 1))
            for x, items in groups.items():
                k = frozenset(items)
                if k not in index:
                    index[k] = len(kernels); kernels.append(k); trans.append({})
                trans[i][x] = index[k]
            i += 1
        return [sorted(k) for k in kernels], trans

    def lalr_lookaheads(self, kernels, trans) -> List[Dict[Core, Set[str]]]:
        las = [{c: set() for c in k} for k in kernels]
        las[0][(0, 0)].add(END)
        prop: Dict[Tuple[int, Core], List[Tuple[int, Core]]] = defaultdict(list)
        for s, kernel in enumerate(kernels):
            for kc in kernel:
                for core, lset in self.closure1({kc: {DUMMY}}).items():
                    x = self.rhs_after(core)
                    if x is None: continue
                    t, tc = trans[s][x], (core[0], core[1] + 1)
                    for a in lset:
                        if a == DUMMY: prop[(s, kc)].append((t, tc))
                        else: las[t][tc].add(a)
        work = deque((s, c) for s in range(len(kernels)) for c in kernels[s])
        while work:
            s, c = work.popleft()
            for t, tc in prop.get((s, c), ()):
                if not las[s][c] <= las[t][tc]:
                    las[t][tc] |= las[s][c]; work.append((t, tc))
        return las

    def build_lr1(self):
        def key(items):
            return frozenset((c, frozenset(l)) for c, l in items.items())
        k0 = {(0, 0): {END}}
        index = {key(k0): 0}
        kernels, trans, closures = [k0], [{}], []
        i = 0
        while i < len(kernels):
            cl = self.closure1(kernels[i]); closures.append(cl)
            groups: Dict[str, Dict[Core, Set[str]]] = defaultdict(dict)
            for c, l in cl.items():
                x = self.rhs_after(c)
                if x is not None:
                    groups[x].setdefault((c[0], c[1] + 1), set()).update(l)
            for x, items in groups.items():
                k = key(items)
                if k not in index:
                    index[k] = len(kernels); kernels.append(items); trans.append({})
                trans[i][x] = index[k]
            i += 1
        return kernels, trans, closures

    # -- table
    def build(self) -> LRTable:
        if self.method == "lr1":
            kern_las, trans, closures = self.build_lr1()
            kernels = [sorted(k) for k in kern_las]
        else:
            kernels, trans = self.build_lr0()
            if self.method == "lalr":
                kla = self.lalr_lookaheads(kernels, trans)
                closures = [self.closure1(k) for k in kla]
            else:
                closures = [{c: set() for c in self.closure0(k)} for k in kernels]
        n = len(kernels)
        table = LRTable(self.method, self.g, self.prods, kernels, trans,
                        [dict() for _ in range(n)], [dict() for _ in range(n)], closures=closures)
        paths = self._access_paths(trans)
        shortest = self.an.shortest()
        for s in range(n):
            self._fill_state(table, s, paths, shortest)
        return table

    def _access_paths(self, trans) -> List[List[str]]:
        paths: List[Optional[List[str]]] = [None] * len(trans)
        paths[0] = []
        q = deque([0])
        while q:
            s = q.popleft()
            for x, t in trans[s].items():
                if paths[t] is None:
                    paths[t] = paths[s] + [x]; q.append(t)
        return paths

    def _disp(self, sym):
        return self.g.literals.get(sym, sym)

    def _example(self, s, paths, shortest, term) -> str:
        words = []
        for sym in paths[s]:
            words.extend(self._disp(x) for x in shortest.get(sym, [sym]))
        return " ".join(words + ["•", self._disp(term)]) if term != END else " ".join(words + ["•", "<end of input>"])

    def _fill_state(self, table: LRTable, s: int, paths, shortest):
        g, prods = self.g, self.prods
        acts: Dict[str, list] = defaultdict(list)
        for x, t in table.trans[s].items():
            if x in self.terminals:
                acts[x].append(("s", t))
            else:
                table.goto[s][x] = t
        for core, las in table.closures[s].items():
            p = prods[core[0]]
            if core[1] != len(p.rhs):
                continue
            if core[0] == 0:
                acts[END].append(("acc",)); continue
            if self.method == "lr0":
                look = self.terminals
            elif self.method == "slr":
                look = self.an.follow[p.lhs]
            else:
                look = las
            for a in look:
                acts[a].append(("r", core[0]))
        for t in sorted(acts):
            options = acts[t]
            shift = next((o for o in options if o[0] == "s"), None)
            reduces = [0 if o[0] == "acc" else o[1] for o in options if o[0] != "s"]
            tprec = g.precedence.get(t)
            unresolved, forced, nonassoc = [], [], False
            if shift:
                for r in reduces:
                    rprec = prods[r].prec
                    if rprec is None or tprec is None:
                        unresolved.append(r); continue
                    (rl, ra), (tl, _) = rprec, tprec
                    desc = f"state {s}: {prods[r].lhs} -> {' '.join(prods[r].rhs)} vs {t}: "
                    if rl > tl or (rl == tl and ra == "left"):
                        table.resolved.append(desc + "reduce"); forced.append(r)
                    elif rl < tl or (rl == tl and ra == "right"):
                        table.resolved.append(desc + "shift")
                    else:
                        table.resolved.append(desc + "error (nonassoc)"); nonassoc = True
                if nonassoc:
                    continue                      # explicit syntax error on this lookahead
                if forced:
                    shift = None
                if shift:
                    if unresolved:
                        table.conflicts.append(Conflict(
                            "shift/reduce", s, t, sorted(unresolved), shift[1],
                            f"shift to state {shift[1]}", self._example(s, paths, shortest, t)))
                    table.action[s][t] = shift
                    continue
                reduces = forced + unresolved
            if len(reduces) > 1:
                table.conflicts.append(Conflict(
                    "reduce/reduce", s, t, sorted(reduces), None,
                    f"reduce {min(reduces)} (earliest production)", self._example(s, paths, shortest, t)))
            if reduces:
                r = min(reduces)
                table.action[s][t] = ("acc",) if r == 0 else ("r", r)
            elif shift:
                table.action[s][t] = shift


def build_table(g: Grammar, method: str = "lalr", analysis: Optional[Analysis] = None) -> LRTable:
    return _Builder(g, method, analysis).build()


# ===================================================================== driver

@dataclass
class TraceRow:
    step: int
    stack: str
    lookahead: str
    action: str


class LRParser:
    def __init__(self, table: LRTable):
        self.table, self.g = table, table.grammar

    def parse(self, tokens: List[Token], trace: Optional[List[TraceRow]] = None) -> Node:
        tb, hidden = self.table, self.g.hidden
        states, values = [0], []
        pos, step = 0, 0
        while True:
            tok = tokens[pos]
            act = tb.action[states[-1]].get(tok.type)
            if act is None:
                exp = sorted(tb.action[states[-1]])
                raise ParseError(_syntax_msg(tok, exp), tok, exp)
            if trace is not None:
                step += 1
                trace.append(TraceRow(step, " ".join(["0"] + [f"{_sym(v)} {s}" for v, s in zip(values, states[1:])]),
                                      tok.type, _act_str(act) if act[0] != "r" else
                                      f"reduce {tb.prods[act[1]]}"))
            if act[0] == "s":
                states.append(act[1]); values.append(tok); pos += 1
            elif act[0] == "r":
                p = tb.prods[act[1]]
                k = len(p.rhs)
                kids = values[len(values) - k:] if k else []
                if k:
                    del values[-k:]; del states[-k:]
                kids = flatten_children(kids, hidden) if p.lhs not in hidden else kids
                values.append(Node(p.lhs, list(kids)))
                states.append(tb.goto[states[-1]][p.lhs])
            else:
                return values[0]


def _sym(v) -> str:
    return v.type if isinstance(v, Token) else v.name


def _syntax_msg(tok: Token, expected: List[str]) -> str:
    got = "end of input" if tok.type == END else f"{tok.text!r}"
    exp = ", ".join(e if e != END else "end of input" for e in expected)
    return f"syntax error at {tok.line}:{tok.col}: unexpected {got}; expected one of: {exp}"
