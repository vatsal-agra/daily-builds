"""Grammar DSL: parsing, EBNF desugaring and the Grammar/Production model.

Syntax (comments start with ``#`` or ``//``)::

    %token NUM /[0-9]+/          named token with a regex
    %skip  /[ \\t\\n]+/            pattern discarded between tokens
    %left '+' '-'                lowest precedence first, one level per line
    %right '^'
    %nonassoc '<'
    %start expr
    expr : expr '+' expr  | NUM | '(' expr ')' | '-' expr %prec UMINUS ;

Rules whose names start with an underscore are *hidden*: their children are spliced into
the parent in parse trees (this is also how the EBNF helpers vanish).

The reserved name ``error`` may appear in rules (``stmt : error ';' ;``) to mark
resynchronisation points for ``parse --recover``.

EBNF suffixes ``* + ?`` and parenthesised groups ``( a | b )`` are desugared into hidden
helper nonterminals that are spliced away again when parse trees are built.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

END = "$end"
ACCEPT = "$accept"


class GrammarError(Exception):
    def __init__(self, msg: str, line: Optional[int] = None):
        self.line = line
        super().__init__(f"line {line}: {msg}" if line else msg)


@dataclass(frozen=True)
class Production:
    index: int
    lhs: str
    rhs: Tuple[str, ...]
    prec: Optional[Tuple[int, str]] = None  # (level, assoc) used for conflict resolution

    def __str__(self) -> str:
        return f"{self.lhs} -> {' '.join(self.rhs) if self.rhs else 'ε'}"


@dataclass
class Grammar:
    start: str
    productions: List[Production]
    terminals: List[str]                       # declaration order, excludes $end
    nonterminals: List[str]                    # first-seen order
    token_regex: Dict[str, str] = field(default_factory=dict)   # NAME -> regex source
    literals: Dict[str, str] = field(default_factory=dict)      # "'+'" -> "+"
    skips: List[str] = field(default_factory=list)
    precedence: Dict[str, Tuple[int, str]] = field(default_factory=dict)
    hidden: set = field(default_factory=set)   # helper nonterminals from EBNF sugar
    by_lhs: Dict[str, List[Production]] = field(default_factory=dict)
    prec_used: set = field(default_factory=set)  # names referenced by %prec

    def __post_init__(self):
        self.reindex()

    def reindex(self):
        self.by_lhs = {nt: [] for nt in self.nonterminals}
        for p in self.productions:
            self.by_lhs.setdefault(p.lhs, []).append(p)

    def is_terminal(self, s: str) -> bool:
        return s in self._tset()

    def _tset(self):
        t = getattr(self, "_tcache", None)
        if t is None or len(t) != len(self.terminals) + 1:
            t = set(self.terminals) | {END}
            self._tcache = t
        return t

    def copy_with(self, productions: List[Production], nonterminals: List[str], hidden=None) -> "Grammar":
        return Grammar(self.start, productions, list(self.terminals), nonterminals,
                       dict(self.token_regex), dict(self.literals), list(self.skips),
                       dict(self.precedence), set(self.hidden if hidden is None else hidden))

    def _fmt_sym(self, s: str) -> str:
        if s in self.literals:
            return "'" + self.literals[s].replace("\\", "\\\\").replace("'", "\\'").replace("\n", "\\n") + "'"
        return s

    def pretty(self, full: bool = False) -> str:
        """Render as DSL text. With ``full=True`` the token/skip/precedence declarations are
        included, so the output can be fed straight back into ``load_grammar``."""
        out = []
        if full:
            for name, rx in self.token_regex.items():
                out.append(f"%token {name} /{rx.replace('/', chr(92) + '/')}/")
            for rx in self.skips:
                out.append(f"%skip /{rx.replace('/', chr(92) + '/')}/")
            levels: Dict[int, Tuple[str, List[str]]] = {}
            for name, (lvl, assoc) in self.precedence.items():
                levels.setdefault(lvl, (assoc, []))[1].append(self._fmt_sym(name))
            for lvl in sorted(levels):
                out.append(f"%{levels[lvl][0]} {' '.join(levels[lvl][1])}")
            out.append(f"%start {self.start}")
        for nt in self.nonterminals:
            alts = []
            for p in self.by_lhs.get(nt, []):
                alt = " ".join(self._fmt_sym(x) for x in p.rhs) or "%empty"
                default = next((self.precedence[x] for x in reversed(p.rhs)
                                if x in self.precedence and x in self.terminals), None)
                if p.prec != default and p.prec is not None:     # explicit %prec must survive
                    name = next(n for n, v in self.precedence.items() if v == p.prec)
                    alt += f" %prec {self._fmt_sym(name)}"
                alts.append(alt)
            if alts:
                out.append(f"{nt} : " + "\n    | ".join(alts) + "\n    ;")
        return "\n".join(out)


# ---------------------------------------------------------------- DSL scanner

_IDENT = re.compile(r"[A-Za-z_][A-Za-z0-9_]*")


@dataclass
class _T:
    kind: str   # ident, str, regex, directive, punct, eof
    val: str
    line: int


def _scan(src: str) -> List[_T]:
    toks: List[_T] = []
    i, n, line = 0, len(src), 1
    while i < n:
        c = src[i]
        if c == "\n":
            line += 1; i += 1
        elif c in " \t\r":
            i += 1
        elif c == "#" or src.startswith("//", i):
            while i < n and src[i] != "\n":
                i += 1
        elif src.startswith("/*", i):
            j = src.find("*/", i + 2)
            if j < 0:
                raise GrammarError("unterminated /* comment", line)
            line += src.count("\n", i, j); i = j + 2
        elif c in "'\"":
            j, buf = i + 1, []
            while j < n and src[j] != c:
                if src[j] == "\\" and j + 1 < n:
                    esc = {"n": "\n", "t": "\t", "r": "\r"}.get(src[j + 1], src[j + 1])
                    buf.append(esc); j += 2
                elif src[j] == "\n":
                    raise GrammarError("unterminated string literal", line)
                else:
                    buf.append(src[j]); j += 1
            if j >= n:
                raise GrammarError("unterminated string literal", line)
            if not buf:
                raise GrammarError("empty string literal", line)
            toks.append(_T("str", "".join(buf), line)); i = j + 1
        elif c == "/" and toks and (
                (toks[-1].kind == "ident" and _regex_context(toks))
                or (toks[-1].kind == "directive" and toks[-1].val == "%skip")):
            j, buf, in_class = i + 1, [], False
            while j < n and (in_class or src[j] != "/"):
                ch = src[j]
                if ch == "\\" and j + 1 < n:
                    buf.append("/" if src[j + 1] == "/" else src[j:j + 2]); j += 2
                    continue
                if ch == "\n":
                    raise GrammarError("unterminated regex", line)
                if ch == "[" and not in_class:
                    in_class = True
                    buf.append(ch); j += 1
                    if j < n and src[j] == "^": buf.append("^"); j += 1
                    if j < n and src[j] == "]": buf.append("]"); j += 1   # literal ']' first in class
                    continue
                if ch == "]" and in_class:
                    in_class = False
                buf.append(ch); j += 1
            if j >= n:
                raise GrammarError("unterminated regex", line)
            toks.append(_T("regex", "".join(buf), line)); i = j + 1
        elif c == "%":
            m = _IDENT.match(src, i + 1)
            if not m:
                raise GrammarError("stray '%'", line)
            toks.append(_T("directive", "%" + m.group(), line)); i = m.end()
        elif c.isalpha() or c == "_":
            m = _IDENT.match(src, i)
            toks.append(_T("ident", m.group(), line)); i = m.end()
        elif c in ":|;*+?()":
            toks.append(_T("punct", c, line)); i += 1
        else:
            raise GrammarError(f"unexpected character {c!r}", line)
    toks.append(_T("eof", "", line))
    return toks


def _regex_context(toks: List[_T]) -> bool:
    """A '/' starts a regex only directly after `%token NAME`."""
    return len(toks) >= 2 and toks[-2].kind == "directive" and toks[-2].val == "%token"


# ---------------------------------------------------------------- DSL parser

class _Parser:
    def __init__(self, toks: List[_T], ebnf_style: str):
        self.toks, self.p = toks, 0
        self.style = ebnf_style
        self.token_regex: Dict[str, str] = {}
        self.literals: Dict[str, str] = {}
        self.skips: List[str] = []
        self.terminals: List[str] = []
        self.prec_levels: List[Tuple[str, List[str], int]] = []
        self.start: Optional[str] = None
        self.rules: List[Tuple[str, list, int]] = []  # (lhs, alternatives(raw), line)
        self.nonterminals: List[str] = []
        self.hidden: set = set()
        self.productions: List[Production] = []
        self.counter = 0
        self.prec_used: set = set()

    def peek(self) -> _T: return self.toks[self.p]
    def next(self) -> _T:
        t = self.toks[self.p]; self.p += 1; return t

    def expect(self, kind, val=None) -> _T:
        t = self.next()
        if t.kind != kind or (val is not None and t.val != val):
            raise GrammarError(f"expected {val or kind}, found {t.val or t.kind!r}", t.line)
        return t

    def add_terminal(self, name):
        if name not in self.terminals:
            self.terminals.append(name)

    # -- first pass: directives and raw rule bodies
    def parse(self):
        while self.peek().kind != "eof":
            t = self.peek()
            if t.kind == "directive":
                self.directive()
            elif t.kind == "ident":
                self.rule()
            else:
                raise GrammarError(f"unexpected {t.val!r}", t.line)
        return self

    def directive(self):
        d = self.next()
        if d.val == "%token":
            name = self.expect("ident").val
            rx = self.expect("regex").val
            if name in self.token_regex:
                raise GrammarError(f"token {name} declared twice", d.line)
            try:
                if re.compile(rx).match(""):
                    raise GrammarError(f"token {name} regex matches the empty string", d.line)
            except re.error as e:
                raise GrammarError(f"bad regex for {name}: {e}", d.line)
            self.token_regex[name] = rx
            self.add_terminal(name)
        elif d.val == "%skip":
            rx = self.expect("regex").val
            try:
                if re.compile(rx).match(""):
                    raise GrammarError("%skip regex matches the empty string", d.line)
            except re.error as e:
                raise GrammarError(f"bad %skip regex: {e}", d.line)
            self.skips.append(rx)
        elif d.val in ("%left", "%right", "%nonassoc"):
            names = []
            while self.peek().kind in ("ident", "str") and not (
                    self.peek().kind == "ident" and self.toks[self.p + 1].val == ":"):
                t = self.next()
                names.append(self.lit_name(t) if t.kind == "str" else t.val)
            if not names:
                raise GrammarError(f"{d.val} needs at least one token", d.line)
            self.prec_levels.append((d.val[1:], names, d.line))
        elif d.val == "%start":
            self.start = self.expect("ident").val
        else:
            raise GrammarError(f"unknown directive {d.val}", d.line)

    def lit_name(self, t: _T) -> str:
        name = "'" + t.val + "'"
        self.literals[name] = t.val
        self.add_terminal(name)
        return name

    def rule(self):
        name = self.next()
        self.expect("punct", ":")
        alts = self.alternatives(name.line)
        self.expect("punct", ";")
        if name.val in self.token_regex:
            raise GrammarError(f"{name.val} is declared both as token and rule", name.line)
        if name.val not in self.nonterminals:
            self.nonterminals.append(name.val)
        if name.val.startswith("_"):          # convention: _rules vanish from parse trees
            self.hidden.add(name.val)
        self.rules.append((name.val, alts, name.line))

    # raw structure: alternatives = list of (items, prec_name); item = ('sym', name, line) |
    #   ('group', alternatives) | ('rep', item, op)
    def alternatives(self, line):
        alts = [self.sequence()]
        while self.peek().kind == "punct" and self.peek().val == "|":
            self.next(); alts.append(self.sequence())
        return alts

    def sequence(self):
        items, prec = [], None
        while True:
            t = self.peek()
            if t.kind == "directive" and t.val == "%prec":
                self.next(); pt = self.next()
                if pt.kind == "str":
                    prec = self.lit_name(pt)
                elif pt.kind == "ident":
                    prec = pt.val
                else:
                    raise GrammarError("%prec needs a token name", pt.line)
            elif t.kind == "directive" and t.val == "%empty":
                self.next()
            elif t.kind in ("ident", "str") or (t.kind == "punct" and t.val == "("):
                items.append(self.postfix())
            else:
                break
        return items, prec

    def postfix(self):
        t = self.next()
        if t.kind == "ident":
            atom = ("sym", t.val, t.line)
        elif t.kind == "str":
            atom = ("sym", self.lit_name(t), t.line)
        else:
            alts = self.alternatives(t.line)
            self.expect("punct", ")")
            atom = ("group", alts, t.line)
        while self.peek().kind == "punct" and self.peek().val in "*+?":
            atom = ("rep", atom, self.next().val, t.line)
        return atom

    # -- second pass: resolve, desugar
    def fresh(self, hint):
        self.counter += 1
        while f"_{hint}{self.counter}" in self.nonterminals or f"_{hint}{self.counter}" in self.defined:
            self.counter += 1
        name = f"_{hint}{self.counter}"
        self.nonterminals.append(name); self.hidden.add(name)
        return name

    def sym_of(self, item) -> str:
        kind = item[0]
        if kind == "sym":
            name, line = item[1], item[2]
            if name in self.terminals or name in self.nonterminals or name in self.defined:
                return name
            if name == "error":      # yacc-style recovery pseudo-terminal; never produced by the lexer
                self.add_terminal("error")
                return name
            raise GrammarError(f"undefined symbol {name}", line)
        if kind == "group":
            alts = item[1]
            if len(alts) == 1 and len(alts[0][0]) == 1 and alts[0][1] is None:
                return self.sym_of(alts[0][0][0])
            nt = self.fresh("grp")
            for items, prec in alts:
                self.emit(nt, [self.sym_of(i) for i in items], prec, item[2])
            return nt
        _, inner, op, line = item
        x = self.sym_of(inner)
        if op == "*":
            nt = self.fresh("star")
            self.emit(nt, [], None, line)
            self.emit(nt, [nt, x] if self.style == "left" else [x, nt], None, line)
        elif op == "+":
            nt = self.fresh("plus")
            self.emit(nt, [x], None, line)
            self.emit(nt, [nt, x] if self.style == "left" else [x, nt], None, line)
        else:
            nt = self.fresh("opt")
            self.emit(nt, [], None, line); self.emit(nt, [x], None, line)
        return nt

    def emit(self, lhs, rhs, prec_name, line):
        prec = None
        if prec_name is not None:
            self.prec_used.add(prec_name)
            if prec_name not in self.precedence:
                raise GrammarError(f"%prec {prec_name} has no precedence declaration", line)
            prec = self.precedence[prec_name]
        else:  # yacc default: precedence of the last terminal carrying one
            for s in reversed(rhs):
                if s in self.precedence and s in self.terminals:
                    prec = self.precedence[s]; break
        self.productions.append(Production(len(self.productions), lhs, tuple(rhs), prec))

    def finish(self) -> Grammar:
        if not self.rules:
            raise GrammarError("grammar has no rules")
        self.precedence: Dict[str, Tuple[int, str]] = {}
        for lvl, (assoc, names, line) in enumerate(self.prec_levels, 1):
            for nm in names:
                if nm in self.precedence:
                    raise GrammarError(f"{nm} given precedence twice", line)
                self.precedence[nm] = (lvl, assoc)
        self.defined = {r[0] for r in self.rules}
        for lhs, alts, line in list(self.rules):
            for items, prec in alts:
                rhs = [self.sym_of(i) for i in items]
                self.emit(lhs, rhs, prec, line)
        start = self.start or self.rules[0][0]
        if start not in self.defined:
            raise GrammarError(f"start symbol {start} has no rules")
        # pseudo-tokens named only in %prec/%left (e.g. UMINUS) are not real terminals
        g = Grammar(start, self.productions, self.terminals, self.nonterminals,
                    self.token_regex, self.literals, self.skips,
                    {k: v for k, v in self.precedence.items()}, self.hidden)
        g.prec_used = self.prec_used
        return g


def load_grammar(src: str, ebnf_style: str = "left") -> Grammar:
    """Parse grammar text. ``ebnf_style`` is 'left' (LR-friendly) or 'right' (LL-friendly)."""
    toks = _scan(src)
    p = _Parser(toks, ebnf_style).parse()
    return p.finish()
