"""Lexer and parser for the Argus modelling language.

Expressions are tuples-as-Nodes; statements are Nodes with a `kind`.  LTL formulas are
parsed here too (they embed ordinary expressions as atoms).
"""
import re
from types import SimpleNamespace


class ArgusError(Exception):
    """Any user-facing error (syntax, semantic, usage)."""

    def __init__(self, msg, line=None, col=None, src=None):
        super().__init__(msg)
        self.msg, self.line, self.col, self.src = msg, line, col, src

    def __str__(self):
        if self.line is None:
            return self.msg
        out = f"line {self.line}: {self.msg}"
        if self.src is not None:
            lines = self.src.splitlines()
            if 0 < self.line <= len(lines):
                out += "\n    " + lines[self.line - 1]
                if self.col:
                    out += "\n    " + " " * (self.col - 1) + "^"
        return out


KEYWORDS = {
    "const", "var", "chan", "proc", "run", "as", "for", "in", "of", "invariant", "ltl",
    "skip", "break", "label", "assert", "await", "if", "else", "while", "loop", "either",
    "or", "atomic", "nondet", "send", "recv", "true", "false", "at", "len", "empty", "full",
    "head",
}

TOKEN_RE = re.compile(
    r'''(?P<ws>\s+|//[^\n]*|/\*.*?\*/)
       |(?P<num>\d+)
       |(?P<str>"(?:[^"\\]|\\.)*")
       |(?P<id>[A-Za-z_][A-Za-z_0-9]*)
       |(?P<op><->|->|\[\]|<>|\.\.|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%<>=!&|^~?:;,.(){}\[\]])''',
    re.S | re.X)


class Tok:
    __slots__ = ("kind", "val", "line", "col")

    def __init__(self, kind, val, line, col):
        self.kind, self.val, self.line, self.col = kind, val, line, col

    def __repr__(self):
        return f"Tok({self.kind},{self.val!r}@{self.line})"


def lex(src):
    toks, pos, line, ls = [], 0, 1, 0
    while pos < len(src):
        m = TOKEN_RE.match(src, pos)
        if not m:
            raise ArgusError(f"unexpected character {src[pos]!r}", line, pos - ls + 1, src)
        kind = m.lastgroup
        text = m.group()
        if kind != "ws":
            toks.append(Tok(kind, int(text) if kind == "num" else text, line, pos - ls + 1))
        nl = text.count("\n")
        if nl:
            line += nl
            ls = pos + text.rindex("\n") + 1
        pos = m.end()
    toks.append(Tok("eof", None, line, pos - ls + 1))
    return toks


def N(kind, line, **kw):
    return SimpleNamespace(kind=kind, line=line, **kw)


# ----------------------------------------------------------------------------------------
# expression pretty printer (used for trace text and atom identity)
# ----------------------------------------------------------------------------------------
def fmt(e):
    k = e.kind
    if k == "num":
        return str(e.val)
    if k == "name":
        return e.name
    if k == "idx":
        return f"{e.name}[{fmt(e.index)}]"
    if k == "qual":
        return f"{e.inst}.{e.name}"
    if k == "un":
        return f"{e.op}{fmt(e.a)}" if e.a.kind in ("num", "name", "idx", "call", "at") else f"{e.op}({fmt(e.a)})"
    if k == "bin":
        return f"{_p(e.a)} {e.op} {_p(e.b)}"
    if k == "tern":
        return f"{_p(e.c)} ? {_p(e.a)} : {_p(e.b)}"
    if k == "call":
        return f"{e.fn}({', '.join(fmt(a) if not isinstance(a, str) else a for a in e.args)})"
    if k == "at":
        return f"at({e.inst}, {e.label})"
    raise AssertionError(k)


def _p(e):
    s = fmt(e)
    return f"({s})" if e.kind in ("bin", "tern") else s


class Parser:
    def __init__(self, src):
        self.src = src
        self.toks = lex(src)
        self.i = 0

    # -- token helpers ------------------------------------------------------------------
    @property
    def t(self):
        return self.toks[self.i]

    def err(self, msg, tok=None):
        tok = tok or self.t
        return ArgusError(msg, tok.line, tok.col, self.src)

    def is_op(self, v):
        return self.t.kind == "op" and self.t.val == v

    def is_kw(self, v):
        return self.t.kind == "id" and self.t.val == v

    def accept(self, v):
        if (self.t.kind in ("op", "id")) and self.t.val == v:
            self.i += 1
            return True
        return False

    def expect(self, v):
        if not self.accept(v):
            got = "end of file" if self.t.kind == "eof" else repr(self.t.val)
            raise self.err(f"expected {v!r}, found {got}")

    def ident(self, what="identifier"):
        t = self.t
        if t.kind != "id" or t.val in KEYWORDS:
            got = "end of file" if t.kind == "eof" else repr(t.val)
            raise self.err(f"expected {what}, found {got}")
        self.i += 1
        return t.val

    # -- program ------------------------------------------------------------------------
    def program(self):
        prog = SimpleNamespace(consts=[], vars=[], chans=[], procs=[], runs=[], invariants=[], ltls=[])
        while self.t.kind != "eof":
            t = self.t
            if self.accept("const"):
                name = self.ident()
                self.expect("=")
                prog.consts.append(N("const", t.line, name=name, expr=self.expr()))
                self.expect(";")
            elif self.accept("var"):
                prog.vars.append(self.vardecl(t.line))
            elif self.accept("chan"):
                name = self.ident()
                self.expect("[")
                cap = self.expr()
                self.expect("]")
                arity = self.expr() if self.accept("of") else N("num", t.line, val=1)
                self.expect(";")
                prog.chans.append(N("chan", t.line, name=name, cap=cap, arity=arity))
            elif self.accept("proc"):
                prog.procs.append(self.procdef(t.line))
            elif self.is_kw("run") or self.is_kw("for"):
                prog.runs.extend(self.runs())
            elif self.accept("invariant"):
                name = self.ident()
                self.expect(":")
                prog.invariants.append(N("invariant", t.line, name=name, expr=self.expr()))
                self.expect(";")
            elif self.accept("ltl"):
                name = self.ident()
                self.expect(":")
                f = self.ltl_top()
                self.expect(";")
                prog.ltls.append(N("ltl", t.line, name=name, formula=f))
            else:
                raise self.err(f"unexpected {t.val!r} at top level")
        return prog

    def vardecl(self, line):
        name = self.ident()
        size = None
        if self.accept("["):
            size = self.expr()
            self.expect("]")
        rng = None
        if self.accept(":"):
            lo = self.expr()
            self.expect("..")
            hi = self.expr()
            rng = (lo, hi)
        init = None
        if self.accept("="):
            if self.accept("{"):
                items = [self.expr()]
                while self.accept(","):
                    items.append(self.expr())
                self.expect("}")
                init = items
            else:
                init = self.expr()
        self.expect(";")
        return N("var", line, name=name, size=size, rng=rng, init=init)

    def procdef(self, line):
        name = self.ident("process name")
        self.expect("(")
        params = []
        if not self.is_op(")"):
            params.append(self.ident())
            while self.accept(","):
                params.append(self.ident())
        self.expect(")")
        if len(set(params)) != len(params):
            raise ArgusError(f"duplicate parameter name in process '{name}'", line, None, self.src)
        self.expect("{")
        locals_ = []
        while self.is_kw("var"):
            l = self.t.line
            self.i += 1
            d = self.vardecl(l)
            if d.size is not None:
                raise ArgusError("local arrays are not supported (declare a global array)", l, None, self.src)
            locals_.append(d)
        body = self.stmts_until("}")
        self.expect("}")
        return N("proc", line, name=name, params=params, locals=locals_, body=body)

    def runs(self):
        t = self.t
        if self.accept("for"):
            v = self.ident()
            self.expect("in")
            lo = self.expr()
            self.expect("..")
            hi = self.expr()
            self.expect("{")
            inner = []
            while not self.is_op("}"):
                if not self.is_kw("run"):
                    raise self.err("only 'run' statements are allowed inside a top-level 'for'")
                inner.extend(self.runs())
            self.expect("}")
            return [N("runfor", t.line, var=v, lo=lo, hi=hi, body=inner)]
        self.expect("run")
        pname = self.ident("process name")
        self.expect("(")
        args = []
        if not self.is_op(")"):
            args.append(self.expr())
            while self.accept(","):
                args.append(self.expr())
        self.expect(")")
        alias = self.ident("instance name") if self.accept("as") else None
        self.expect(";")
        return [N("run", t.line, proc=pname, args=args, alias=alias)]

    # -- statements ---------------------------------------------------------------------
    def stmts_until(self, closer):
        out = []
        while not self.is_op(closer):
            if self.t.kind == "eof":
                raise self.err(f"unexpected end of file, expected {closer!r}")
            out.extend(self.stmt())
        return out

    def block(self):
        self.expect("{")
        body = self.stmts_until("}")
        self.expect("}")
        return body

    def lvalue(self):
        t = self.t
        name = self.ident("variable name")
        if self.accept("["):
            idx = self.expr()
            self.expect("]")
            return N("idx", t.line, name=name, index=idx)
        return N("name", t.line, name=name)

    def stmt(self):
        """Returns a list of statements (a bare block flattens)."""
        t = self.t
        L = t.line
        if self.is_op("{"):
            return self.block()
        if t.kind == "id":
            v = t.val
            if v == "skip":
                self.i += 1
                self.expect(";")
                return [N("skip", L)]
            if v == "break":
                self.i += 1
                self.expect(";")
                return [N("break", L)]
            if v == "label":
                self.i += 1
                name = self.ident("label name")
                self.expect(":")
                return [N("label", L, name=name)]
            if v == "assert":
                self.i += 1
                e = self.expr()
                msg = None
                if self.accept(","):
                    if self.t.kind != "str":
                        raise self.err("expected a message string")
                    msg = self.t.val[1:-1]
                    self.i += 1
                self.expect(";")
                return [N("assert", L, expr=e, msg=msg)]
            if v == "await":
                self.i += 1
                e = self.expr()
                self.expect(";")
                return [N("await", L, expr=e)]
            if v == "if":
                return [self.ifstmt()]
            if v == "while":
                self.i += 1
                self.expect("(")
                c = self.expr()
                self.expect(")")
                return [N("while", L, cond=c, body=self.block())]
            if v == "loop":
                self.i += 1
                return [N("loop", L, body=self.block())]
            if v == "either":
                self.i += 1
                branches = [self.block()]
                while self.accept("or"):
                    branches.append(self.block())
                return [N("either", L, branches=branches)]
            if v == "atomic":
                self.i += 1
                return [N("atomic", L, body=self.block())]
            if v == "nondet":
                self.i += 1
                lv = self.lvalue()
                self.expect("in")
                lo = self.expr()
                self.expect("..")
                hi = self.expr()
                self.expect(";")
                return [N("nondet", L, lv=lv, lo=lo, hi=hi)]
            if v == "send":
                self.i += 1
                self.expect("(")
                ch = self.ident("channel name")
                args = []
                while self.accept(","):
                    args.append(self.expr())
                self.expect(")")
                self.expect(";")
                return [N("send", L, chan=ch, args=args)]
            if v == "recv":
                self.i += 1
                self.expect("(")
                ch = self.ident("channel name")
                lvs = []
                while self.accept(","):
                    lvs.append(self.lvalue())
                self.expect(")")
                self.expect(";")
                return [N("recv", L, chan=ch, lvs=lvs)]
            if v in KEYWORDS:
                raise self.err(f"unexpected keyword {v!r}")
            lv = self.lvalue()
            self.expect("=")
            e = self.expr()
            self.expect(";")
            return [N("assign", L, lv=lv, expr=e)]
        raise self.err(f"unexpected {t.val!r}" if t.kind != "eof" else "unexpected end of file")

    def ifstmt(self):
        L = self.t.line
        self.expect("if")
        self.expect("(")
        c = self.expr()
        self.expect(")")
        then = self.block()
        els = None
        if self.accept("else"):
            els = [self.ifstmt()] if self.is_kw("if") else self.block()
        return N("if", L, cond=c, then=then, els=els)

    # -- expressions --------------------------------------------------------------------
    def expr(self):
        c = self.binlevel(0)
        if self.is_op("?"):
            L = self.t.line
            self.i += 1
            a = self.expr()
            self.expect(":")
            b = self.expr()
            return N("tern", L, c=c, a=a, b=b)
        return c

    LEVELS = [["||"], ["&&"], ["|"], ["^"], ["&"], ["==", "!="], ["<", "<=", ">", ">="],
              ["<<", ">>"], ["+", "-"], ["*", "/", "%"]]

    def binlevel(self, lvl):
        if lvl == len(self.LEVELS):
            return self.unary()
        a = self.binlevel(lvl + 1)
        while self.t.kind == "op" and self.t.val in self.LEVELS[lvl]:
            op, L = self.t.val, self.t.line
            self.i += 1
            b = self.binlevel(lvl + 1)
            a = N("bin", L, op=op, a=a, b=b)
        return a

    def unary(self):
        t = self.t
        if t.kind == "op" and t.val in ("!", "-", "~"):
            self.i += 1
            return N("un", t.line, op=t.val, a=self.unary())
        return self.primary()

    def primary(self):
        t = self.t
        L = t.line
        if t.kind == "num":
            self.i += 1
            return N("num", L, val=t.val)
        if t.kind == "op" and t.val == "(":
            self.i += 1
            e = self.expr()
            self.expect(")")
            return e
        if t.kind == "id":
            v = t.val
            if v in ("true", "false"):
                self.i += 1
                return N("num", L, val=1 if v == "true" else 0)
            if v == "at":
                self.i += 1
                self.expect("(")
                inst = self.ident("instance name")
                self.expect(",")
                lab = self.ident("label name")
                self.expect(")")
                return N("at", L, inst=inst, label=lab)
            if v in ("len", "empty", "full", "head"):
                self.i += 1
                self.expect("(")
                ch = self.ident("channel name")
                args = [ch]
                if v == "head" and self.accept(","):
                    args.append(self.expr())
                self.expect(")")
                return N("call", L, fn=v, args=args)
            if v in KEYWORDS:
                raise self.err(f"unexpected keyword {v!r} in expression")
            self.i += 1
            if self.is_op(".") and self.toks[self.i + 1].kind == "id":
                self.i += 1
                name = self.ident("variable name")
                return N("qual", L, inst=v, name=name)
            if self.accept("["):
                idx = self.expr()
                self.expect("]")
                return N("idx", L, name=v, index=idx)
            return N("name", L, name=v)
        got = "end of file" if t.kind == "eof" else repr(t.val)
        raise self.err(f"unexpected {got} in expression")

    # -- LTL ----------------------------------------------------------------------------
    # surface forms: ('atom', exprNode) ('true',) ('false',) ('not',f) ('and',a,b) ('or',a,b)
    #   ('imp',a,b) ('iff',a,b) ('X',f) ('F',f) ('G',f) ('U',a,b) ('R',a,b) ('W',a,b)
    def ltl_top(self):
        f = self.ltl_imp()
        return f

    def ltl_imp(self):
        a = self.ltl_or()
        if self.accept("->"):
            return ("imp", a, self.ltl_imp())
        if self.accept("<->"):
            return ("iff", a, self.ltl_imp())
        return a

    def ltl_or(self):
        a = self.ltl_and()
        while self.is_op("||"):
            self.i += 1
            a = ("or", a, self.ltl_and())
        return a

    def ltl_and(self):
        a = self.ltl_bin()
        while self.is_op("&&"):
            self.i += 1
            a = ("and", a, self.ltl_bin())
        return a

    def ltl_bin(self):
        a = self.ltl_un()
        t = self.t
        if t.kind == "id" and t.val in ("U", "R", "W", "until", "release", "weak_until"):
            self.i += 1
            op = {"U": "U", "until": "U", "R": "R", "release": "R", "W": "W", "weak_until": "W"}[t.val]
            return (op, a, self.ltl_bin())
        return a

    def ltl_un(self):
        t = self.t
        if t.kind == "op" and t.val == "!":
            self.i += 1
            return ("not", self.ltl_un())
        if t.kind == "op" and t.val == "[]":
            self.i += 1
            return ("G", self.ltl_un())
        if t.kind == "op" and t.val == "<>":
            self.i += 1
            return ("F", self.ltl_un())
        if t.kind == "id" and t.val in ("X", "next", "always", "eventually"):
            self.i += 1
            return ({"X": "X", "next": "X", "always": "G", "eventually": "F"}[t.val], self.ltl_un())
        return self.ltl_atom()

    ARITH_FOLLOW = {"==", "!=", "<", "<=", ">", ">=", "+", "-", "*", "/", "%", "&", "|", "^", "<<", ">>", "?"}

    def ltl_atom(self):
        t = self.t
        if t.kind == "op" and t.val == "(":
            save = self.i
            try:
                self.i += 1
                f = self.ltl_imp()
                self.expect(")")
                nxt = self.t
                if not (nxt.kind == "op" and nxt.val in self.ARITH_FOLLOW):
                    return f
            except ArgusError:
                pass
            self.i = save
        if t.kind == "id" and t.val == "true" and not self._expr_follows(1):
            self.i += 1
            return ("true",)
        if t.kind == "id" and t.val == "false" and not self._expr_follows(1):
            self.i += 1
            return ("false",)
        return ("atom", self.binlevel(2))   # `|` level and tighter; && and || belong to LTL

    def _expr_follows(self, off):
        n = self.toks[self.i + off]
        return n.kind == "op" and n.val in self.ARITH_FOLLOW


def parse(src):
    return Parser(src).program()


def parse_ltl_text(text):
    p = Parser(text)
    f = p.ltl_top()
    if p.t.kind != "eof":
        raise p.err(f"unexpected {p.t.val!r} after formula")
    return f
