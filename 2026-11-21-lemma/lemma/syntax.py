"""Lexer, surface AST and parser.

Layout-free syntax.  Tactic scripts are Coq-style: each tactic ends with `.`, `{ … }` focuses.
"""
import re
from dataclasses import dataclass, field
from typing import Any, List, Optional, Tuple


class LemmaError(Exception):
    """A user-facing error with an optional source position."""
    def __init__(self, msg, pos=None, src=None):
        super().__init__(msg)
        self.msg = msg
        self.pos = pos
        self.src = src

    def render(self, filename="<input>", src=None):
        src = src or self.src
        if self.pos is None:
            return f"error: {self.msg}"
        line, col = self.pos
        out = [f"{filename}:{line}:{col}: error: {self.msg.splitlines()[0]}"]
        out += ["  " + l for l in self.msg.splitlines()[1:]]
        if src:
            lines = src.splitlines()
            if 1 <= line <= len(lines):
                out.append("  | " + lines[line - 1])
                out.append("  | " + " " * (col - 1) + "^")
        return "\n".join(out)


KEYWORDS = {"fun", "forall", "let", "in", "elim", "return", "with", "end", "Type", "as", "at", "by", "where"}
COMMANDS = {"inductive", "def", "theorem", "lemma", "axiom", "infixl", "infixr", "infix", "prefix",
            "#check", "#eval", "#print", "#reduce", "example"}
BASE_SYMBOLS = ["(", ")", "{", "}", "[", "]", ":=", "=>", "->", "→", "<-", "←", ":", ",", "|", ".", ";",
                "=", "λ", "∀"]


@dataclass
class Tok:
    kind: str          # ident num sym eof
    text: str
    line: int
    col: int

    @property
    def pos(self):
        return (self.line, self.col)


def prescan_symbols(src):
    return set(re.findall(r'(?:infixl|infixr|infix|prefix)\s+\d+\s+"([^"]+)"', src))


def lex(src, extra_symbols=()):
    syms = sorted(set(BASE_SYMBOLS) | set(extra_symbols), key=lambda s: -len(s))
    toks = []
    i, n, line, col = 0, len(src), 1, 1

    def adv(k):
        nonlocal i, line, col
        for _ in range(k):
            if src[i] == "\n":
                line += 1; col = 1
            else:
                col += 1
            i += 1

    def is_start(c):
        return c.isalpha() or c == "_" or (c not in BASE_SYMBOLS and ord(c) > 127 and c not in "λ∀" and not c.isspace()
                                           and not any(c == s for s in syms))

    while i < n:
        c = src[i]
        if c.isspace():
            adv(1); continue
        if src.startswith("--", i):
            while i < n and src[i] != "\n":
                adv(1)
            continue
        if src.startswith("/-", i):
            start = (line, col)
            depth = 0
            while i < n:
                if src.startswith("/-", i):
                    depth += 1; adv(2)
                elif src.startswith("-/", i):
                    depth -= 1; adv(2)
                    if depth == 0:
                        break
                else:
                    adv(1)
            else:
                raise LemmaError("unterminated block comment", start, src)
            continue
        if c == "#" and re.match(r"#[a-z]+", src[i:]):
            m = re.match(r"#[a-z]+", src[i:])
            toks.append(Tok("ident", m.group(0), line, col)); adv(len(m.group(0))); continue
        if c == '"':                       # string literal (notation commands only)
            j = src.find('"', i + 1)
            if j < 0:
                raise LemmaError("unterminated string", (line, col), src)
            toks.append(Tok("str", src[i + 1:j], line, col)); adv(j + 1 - i); continue
        if c.isdigit():
            m = re.match(r"\d+", src[i:])
            toks.append(Tok("num", m.group(0), line, col)); adv(len(m.group(0))); continue
        # symbols first when they cannot start an identifier (longest match)
        matched = None
        if c in "λ∀" or not (c.isalpha() or c == "_"):
            for s in syms:
                if src.startswith(s, i):
                    matched = s; break
        if matched:
            toks.append(Tok("sym", matched, line, col)); adv(len(matched)); continue
        if is_start(c):
            j = i + 1
            while j < n:
                d = src[j]
                if d.isalnum() or d == "_" or d == "'" or (ord(d) > 127 and d not in "λ∀→←" and not d.isspace()
                                                         and d not in "".join(syms)):
                    j += 1
                elif d == "." and j + 1 < n and (src[j + 1].isalpha() or src[j + 1] == "_"):
                    j += 1
                else:
                    break
            toks.append(Tok("ident", src[i:j], line, col)); adv(j - i); continue
        raise LemmaError(f"unexpected character {c!r}", (line, col), src)
    toks.append(Tok("eof", "", line, col))
    return toks


# ------------------------------------------------------------------ surface AST

@dataclass
class S:
    pos: Tuple[int, int] = field(default=(0, 0), compare=False, repr=False, kw_only=True)


@dataclass
class SVar(S):
    name: str

@dataclass
class SNum(S):
    n: int

@dataclass
class SSort(S):
    n: int

@dataclass
class SApp(S):
    f: Any
    a: Any

@dataclass
class SAnn(S):
    t: Any
    ty: Any

@dataclass
class SArrow(S):
    a: Any
    b: Any

@dataclass
class SLam(S):
    binders: List       # [(name, type-or-None)]
    body: Any

@dataclass
class SPi(S):
    binders: List       # [(name, type)]
    body: Any

@dataclass
class SLet(S):
    name: str
    ty: Any
    val: Any
    body: Any

@dataclass
class SEq(S):
    l: Any
    r: Any

@dataclass
class SElim(S):
    scrut: Any
    motive: Any
    branches: List      # [(ctor, [names], body, pos)]

@dataclass
class SBinderGroup(S):
    names: List
    ty: Any


# commands
@dataclass
class CInductive(S):
    name: str
    params: List
    arity: Any
    ctors: List         # [(name, type surface, pos)]

@dataclass
class CDef(S):
    kind: str           # def | theorem
    name: str
    binders: List
    ty: Any
    body: Any           # term or ByBlock

@dataclass
class CAxiom(S):
    name: str
    binders: List
    ty: Any

@dataclass
class CCheck(S):
    term: Any

@dataclass
class CEval(S):
    term: Any

@dataclass
class CPrint(S):
    name: str
    axioms: bool = False

@dataclass
class CNotation(S):
    kind: str
    prec: int
    tok: str
    target: str


@dataclass
class ByBlock(S):
    tactics: List


@dataclass
class Tac(S):
    name: str
    args: List = field(default_factory=list)
    text: str = ""


class Parser:
    def __init__(self, src, notation):
        self.src = src
        self.nota = notation
        self.toks = lex(src, notation.symbols() | prescan_symbols(src))
        self.p = 0

    # ---- token helpers
    @property
    def tok(self):
        return self.toks[self.p]

    def peek(self, k=1):
        return self.toks[min(self.p + k, len(self.toks) - 1)]

    def err(self, msg, tok=None):
        t = tok or self.tok
        raise LemmaError(msg, t.pos, self.src)

    def is_sym(self, s):
        return self.tok.kind == "sym" and self.tok.text == s

    def is_kw(self, s):
        return self.tok.kind == "ident" and self.tok.text == s

    def accept_sym(self, *ss):
        if self.tok.kind == "sym" and self.tok.text in ss:
            t = self.tok; self.p += 1; return t
        return None

    def expect_sym(self, s, ctx=""):
        if not self.is_sym(s):
            self.err(f"expected '{s}'{ctx}, found {self.describe()}")
        t = self.tok; self.p += 1; return t

    def expect_kw(self, s):
        if not self.is_kw(s):
            self.err(f"expected '{s}', found {self.describe()}")
        self.p += 1

    def describe(self):
        t = self.tok
        return "end of input" if t.kind == "eof" else f"'{t.text}'"

    def ident(self, what="identifier"):
        t = self.tok
        if t.kind != "ident" or t.text in KEYWORDS or t.text in COMMANDS:
            self.err(f"expected {what}, found {self.describe()}")
        self.p += 1
        return t.text

    # ---- terms
    def term(self):
        t = self.tok
        if t.kind == "sym" and t.text in ("λ",) or self.is_kw("fun"):
            return self.lam()
        if (t.kind == "sym" and t.text == "∀") or self.is_kw("forall"):
            return self.forall()
        if self.is_kw("let"):
            return self.let()
        if self.is_kw("elim"):
            return self.elim()
        return self.arrow()

    def binder_lookahead(self):
        """At '(' : is this `( ident+ : ...`?"""
        if not self.is_sym("("):
            return False
        k = 1
        while self.peek(k).kind == "ident" and self.peek(k).text not in KEYWORDS and self.peek(k).text not in COMMANDS:
            k += 1
        return k > 1 and self.peek(k).kind == "sym" and self.peek(k).text == ":"

    def binder_group(self):
        start = self.expect_sym("(")
        names = []
        while self.tok.kind == "ident" and not self.is_sym(":"):
            names.append(self.ident())
        self.expect_sym(":")
        ty = self.term()
        self.expect_sym(")")
        return SBinderGroup(names, ty, pos=start.pos)

    def arrow(self):
        start = self.tok
        if self.binder_lookahead():
            save = self.p
            groups = []
            while self.binder_lookahead():
                groups.append(self.binder_group())
            if self.accept_sym("->", "→"):
                body = self.term()
                bs = [(n, g.ty) for g in groups for n in g.names]
                return SPi(bs, body, pos=start.pos)
            self.p = save                           # it was an ascription `(t : T)`
        lhs = self.infix(0)
        if self.accept_sym("->", "→"):
            rhs = self.term()
            return SArrow(lhs, rhs, pos=start.pos)
        return lhs

    def infix(self, minprec):
        left = self.prefix_or_app()
        while True:
            t = self.tok
            if t.kind != "sym":
                break
            if t.text == "=":
                prec, assoc, target = 50, "n", "="
            elif t.text in self.nota.infix:
                prec, assoc, target = self.nota.infix[t.text]
            else:
                break
            if prec < minprec:
                break
            self.p += 1
            right = self.infix(prec if assoc == "r" else prec + 1)
            if target == "=":
                left = SEq(left, right, pos=t.pos)
            else:
                left = SApp(SApp(SVar(target, pos=t.pos), left, pos=t.pos), right, pos=t.pos)
            if assoc == "n" and self.tok.kind == "sym" and self.tok.text == t.text:
                self.err(f"'{t.text}' is non-associative; add parentheses")
        return left

    def prefix_or_app(self):
        t = self.tok
        if t.kind == "sym" and t.text in self.nota.prefix:
            prec, target = self.nota.prefix[t.text]
            self.p += 1
            operand = self.infix(prec)
            return SApp(SVar(target, pos=t.pos), operand, pos=t.pos)
        return self.app()

    def starts_atom(self):
        t = self.tok
        if t.kind == "num":
            return True
        if t.kind == "ident":
            return t.text not in KEYWORDS - {"Type"} and t.text not in COMMANDS
        return t.kind == "sym" and t.text == "("

    def app(self):
        f = self.atom()
        while self.starts_atom():
            a = self.atom()
            f = SApp(f, a, pos=f.pos)
        return f

    def atom(self):
        t = self.tok
        if t.kind == "num":
            self.p += 1
            return SNum(int(t.text), pos=t.pos)
        if t.kind == "ident":
            if t.text == "Type":
                self.p += 1
                n = 0
                if self.tok.kind == "num":
                    n = int(self.tok.text); self.p += 1
                return SSort(n, pos=t.pos)
            if t.text in KEYWORDS or t.text in COMMANDS:
                self.err(f"unexpected keyword '{t.text}'")
            self.p += 1
            return SVar(t.text, pos=t.pos)
        if t.kind == "sym" and t.text == "(":
            self.p += 1
            e = self.term()
            if self.accept_sym(":"):
                ty = self.term()
                self.expect_sym(")")
                return SAnn(e, ty, pos=t.pos)
            self.expect_sym(")", " to close the parenthesis opened here" if False else "")
            return e
        self.err(f"expected a term, found {self.describe()}")

    def binders(self, typed_required=False):
        """Sequence of `x`, `(x y : A)` groups -> [(name, type|None)]"""
        out = []
        while True:
            if self.binder_lookahead():
                g = self.binder_group()
                out += [(n, g.ty) for n in g.names]
            elif self.tok.kind == "ident" and self.tok.text not in KEYWORDS and self.tok.text not in COMMANDS:
                out.append((self.ident(), None))
            elif self.is_sym("(") and self.peek().kind == "sym" and self.peek().text == ")":
                self.err("empty binder")
            else:
                break
        return out

    def lam(self):
        start = self.tok; self.p += 1
        bs = self.binders()
        if not bs:
            self.err("expected at least one binder after 'fun'")
        self.expect_sym("=>")
        return SLam(bs, self.term(), pos=start.pos)

    def forall(self):
        start = self.tok; self.p += 1
        bs = []
        while True:
            if self.binder_lookahead():
                g = self.binder_group()
                bs += [(n, g.ty) for n in g.names]
            elif self.tok.kind == "ident" and self.tok.text not in KEYWORDS:
                names = []
                while self.tok.kind == "ident" and self.tok.text not in KEYWORDS:
                    names.append(self.ident())
                self.expect_sym(":", " (every ∀-bound variable needs a type)")
                ty = self.term()
                bs += [(n, ty) for n in names]
            else:
                break
        if not bs:
            self.err("expected a binder after 'forall'")
        self.expect_sym(",")
        return SPi(bs, self.term(), pos=start.pos)

    def let(self):
        start = self.tok; self.p += 1
        name = self.ident()
        ty = None
        if self.accept_sym(":"):
            ty = self.term()
        self.expect_sym(":=")
        val = self.term()
        self.expect_kw("in")
        return SLet(name, ty, val, self.term(), pos=start.pos)

    def elim(self):
        start = self.tok; self.p += 1
        scrut = self.term_no_with()
        motive = None
        if self.is_kw("return"):
            self.p += 1
            motive = self.term_no_with()
        self.expect_kw("with")
        branches = []
        while self.accept_sym("|"):
            cpos = self.tok.pos
            cname = self.ident("constructor name")
            names = []
            while self.tok.kind == "ident" and self.tok.text not in KEYWORDS:
                names.append(self.ident())
            self.expect_sym("=>")
            body = self.term()
            branches.append((cname, names, body, cpos))
        self.expect_kw("end")
        return SElim(scrut, motive, branches, pos=start.pos)

    def term_no_with(self):
        return self.term()

    # ---- tactics
    def by_block(self):
        start = self.tok
        self.expect_kw("by")
        return ByBlock(self.tactic_seq(top=True), pos=start.pos)

    def tactic_seq(self, top=False):
        out = []
        while True:
            t = self.tok
            if t.kind == "eof" or (t.kind == "ident" and t.text in COMMANDS) or self.is_sym("}"):
                break
            out.append(self.tactic())
        return out

    def tactic(self):
        p0 = self.p
        tac = self._tactic()
        tac.text = " ".join(("\"" + x.text + "\"") if x.kind == "str" else x.text
                            for x in self.toks[p0:self.p]).replace(" .", ".").replace("( ", "(").replace(" )", ")")
        return tac

    def _tactic(self):
        t = self.tok
        if self.is_sym("{"):
            self.p += 1
            inner = self.tactic_seq()
            self.expect_sym("}", " to close this tactic block")
            self.accept_sym(".")
            return Tac("block", [inner], pos=t.pos)
        if t.kind != "ident":
            self.err(f"expected a tactic, found {self.describe()}")
        name = t.text
        self.p += 1
        a = []
        if name in ("intro", "intros", "revert", "unfold"):
            while self.tok.kind == "ident" and self.tok.text not in COMMANDS:
                a.append(self.ident())
        elif name in ("exact", "apply", "show", "exists", "specialize_", "refine"):
            a.append(self.term())
            while self.is_sym(","):             # exists a, b
                self.p += 1
                a.append(self.term())
        elif name == "rewrite":
            while True:
                rev = bool(self.accept_sym("<-", "←"))
                a.append((rev, self.term()))
                if not self.accept_sym(","):
                    break
            at = None
            if self.is_kw("at"):
                self.p += 1
                at = self.ident()
            a = [a, at]
        elif name in ("simp", "simp_all"):
            lemmas = []
            if self.accept_sym("["):
                while not self.is_sym("]"):
                    rev = bool(self.accept_sym("<-", "←"))
                    lemmas.append((rev, self.term()))
                    if not self.accept_sym(","):
                        break
                self.expect_sym("]")
            at = None
            if self.is_kw("at"):
                self.p += 1
                at = self.ident()
            a = [lemmas, at]
        elif name in ("induction", "cases"):
            a.append(self.ident("a hypothesis name"))
            groups = []
            if self.is_kw("as"):
                self.p += 1
                while True:
                    c = self.ident("constructor name")
                    ns = []
                    while self.tok.kind == "ident" and self.tok.text not in COMMANDS:
                        ns.append(self.ident())
                    groups.append((c, ns))
                    if not self.accept_sym("|"):
                        break
            a.append(groups)
        elif name == "have":
            hn = self.ident()
            self.expect_sym(":")
            ty = self.term()
            val = None
            if self.accept_sym(":="):
                val = self.term()
            a = [hn, ty, val]
        elif name == "try":
            a.append(self.tactic())
            return Tac(name, a, pos=t.pos)
        elif name in ("assumption", "refl", "symm", "constructor", "left", "right", "split", "exfalso",
                      "contradiction", "norm", "trivial", "reflexivity", "congr"):
            pass
        else:
            raise LemmaError(f"unknown tactic '{name}'", t.pos, self.src)
        if not self.accept_sym("."):
            self.err(f"expected '.' to end the tactic '{name}', found {self.describe()}")
        return Tac(name, a, pos=t.pos)

    # ---- commands
    def program(self):
        cmds = []
        while self.tok.kind != "eof":
            cmds.append(self.command())
        return cmds

    def command(self):
        t = self.tok
        if t.kind != "ident" or t.text not in COMMANDS:
            self.err(f"expected a command (inductive, def, theorem, axiom, #check, …), found {self.describe()}")
        kw = t.text
        self.p += 1
        if kw == "inductive":
            return self.inductive(t)
        if kw in ("def", "theorem", "lemma"):
            name = self.ident("a name")
            bs = self.binders()
            self.expect_sym(":", " (a type annotation is required)")
            ty = self.term()
            self.expect_sym(":=")
            body = self.by_block() if self.is_kw("by") else self.term()
            return CDef("def" if kw == "def" else "theorem", name, bs, ty, body, pos=t.pos)
        if kw == "example":
            bs = self.binders()
            self.expect_sym(":")
            ty = self.term()
            self.expect_sym(":=")
            body = self.by_block() if self.is_kw("by") else self.term()
            return CDef("example", "_example", bs, ty, body, pos=t.pos)
        if kw == "axiom":
            name = self.ident("a name")
            bs = self.binders()
            self.expect_sym(":")
            return CAxiom(name, bs, self.term(), pos=t.pos)
        if kw in ("#check", "#eval", "#reduce"):
            e = self.term()
            return CCheck(e, pos=t.pos) if kw == "#check" else CEval(e, pos=t.pos)
        if kw == "#print":
            if self.is_kw("axioms") and self.peek().kind == "ident":
                self.p += 1
                return CPrint(self.ident("a name"), pos=t.pos, axioms=True)
            return CPrint(self.ident("a name"), pos=t.pos)
        if kw in ("infixl", "infixr", "infix", "prefix"):
            if self.tok.kind != "num":
                self.err("expected a precedence number")
            prec = int(self.tok.text); self.p += 1
            if self.tok.kind != "str":
                self.err('expected a quoted operator, e.g. "+"')
            tok = self.tok.text; self.p += 1
            self.expect_sym("=>")
            target = self.ident("a constant name")
            return CNotation(kw, prec, tok, target, pos=t.pos)
        self.err(f"unsupported command {kw}")

    def inductive(self, t):
        name = self.ident("an inductive type name")
        params = []
        while self.binder_lookahead():
            g = self.binder_group()
            params += [(n, g.ty) for n in g.names]
        self.expect_sym(":", " (inductive types need a type, e.g. ': Type')")
        arity = self.term()
        self.expect_kw("where") if self.is_kw("where") else self.err("expected 'where'")
        ctors = []
        while self.accept_sym("|"):
            cp = self.tok.pos
            cn = self.ident("a constructor name")
            self.expect_sym(":")
            ctors.append((cn, self.term(), cp))
        return CInductive(name, params, arity, ctors, pos=t.pos)
