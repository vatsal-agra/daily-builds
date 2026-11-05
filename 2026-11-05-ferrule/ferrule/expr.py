"""Linear symbolic expressions: const + sum(coeff * symbol). Enough for assembler operands."""
import re
from .errors import FerruleError


class Expr:
    __slots__ = ("const", "terms", "mod")

    def __init__(self, const=0, terms=None, mod=None):
        self.const = const
        self.terms = {k: v for k, v in (terms or {}).items() if v}
        self.mod = mod            # relocation modifier: 'PLT' | 'GOTPCREL' | None

    @property
    def is_const(self):
        return not self.terms

    def add(self, o, sign=1):
        t = dict(self.terms)
        for k, v in o.terms.items():
            t[k] = t.get(k, 0) + sign * v
        return Expr(self.const + sign * o.const, t, self.mod or o.mod)

    def scale(self, k):
        return Expr(self.const * k, {s: c * k for s, c in self.terms.items()}, self.mod)

    def __repr__(self):
        return f"Expr({self.const}, {self.terms})"


_TOK = re.compile(r"""\s*(?:
    (?P<num>0[xX][0-9a-fA-F]+|0[bB][01]+|[0-9]+)|
    (?P<chr>'(?:\\.|[^\\'])')|
    (?P<id>[A-Za-z_.$][A-Za-z0-9_.$]*(?:@[A-Za-z]+)?)|
    (?P<op><<|>>|[-+*/%&|^~()])
)""", re.X)

_ESC = {"n": 10, "t": 9, "r": 13, "0": 0, "\\": 92, "'": 39, '"': 34, "a": 7, "b": 8, "f": 12, "v": 11}


def tokenize(s):
    pos, out = 0, []
    s = s.rstrip()
    while pos < len(s):
        m = _TOK.match(s, pos)
        if not m or m.end() == pos:
            raise FerruleError(f"bad character {s[pos:].strip()[:1]!r} in expression {s!r}")
        pos = m.end()
        kind = m.lastgroup
        out.append((kind, m.group(kind)))
    return out


class Parser:
    """Precedence-climbing parser. `lookup(name)` returns an int for known constants else None."""

    def __init__(self, text, lookup=lambda n: None):
        self.toks = tokenize(text)
        self.i = 0
        self.lookup = lookup
        self.text = text

    def peek(self):
        return self.toks[self.i] if self.i < len(self.toks) else (None, None)

    def take(self):
        t = self.peek()
        self.i += 1
        return t

    def parse(self):
        if not self.toks:
            raise FerruleError("empty expression")
        e = self.binary(0)
        if self.i != len(self.toks):
            raise FerruleError(f"unexpected {self.peek()[1]!r} in expression {self.text!r}")
        return e

    PREC = {"|": 1, "^": 2, "&": 3, "<<": 4, ">>": 4, "+": 5, "-": 5, "*": 6, "/": 6, "%": 6}

    def binary(self, minp):
        lhs = self.unary()
        while True:
            kind, v = self.peek()
            if kind != "op" or v not in self.PREC or self.PREC[v] < minp:
                return lhs
            p = self.PREC[v]
            self.take()
            rhs = self.binary(p + 1)
            lhs = self.apply(v, lhs, rhs)

    def apply(self, op, a, b):
        if op == "+":
            return a.add(b)
        if op == "-":
            return a.add(b, -1)
        if op == "*":
            if a.is_const:
                return b.scale(a.const)
            if b.is_const:
                return a.scale(b.const)
            raise FerruleError("cannot multiply two symbolic values")
        if not (a.is_const and b.is_const):
            raise FerruleError(f"operator {op!r} needs constant operands")
        x, y = a.const, b.const
        if op in "/%" and y == 0:
            raise FerruleError("division by zero in expression")
        r = {"/": lambda: int(x / y) if abs(x) < 2**52 else x // y, "%": lambda: x - y * int(x / y),
             "&": lambda: x & y, "|": lambda: x | y, "^": lambda: x ^ y,
             "<<": lambda: x << y, ">>": lambda: x >> y}[op]()
        return Expr(r)

    def unary(self):
        kind, v = self.take()
        if kind == "num":
            return Expr(int(v, 0) if not v.lower().startswith("0b") else int(v[2:], 2))
        if kind == "chr":
            body = v[1:-1]
            return Expr(_ESC.get(body[1], ord(body[1])) if body[0] == "\\" else ord(body))
        if kind == "id":
            mod = None
            if "@" in v:
                v, mod = v.split("@")
                mod = mod.upper()
                if mod not in ("PLT", "GOTPCREL"):
                    raise FerruleError(f"unsupported relocation modifier @{mod}")
            c = self.lookup(v)
            if c is not None:
                return Expr(c)
            return Expr(0, {v: 1}, mod)
        if kind == "op":
            if v == "-":
                return self.unary().scale(-1)
            if v == "+":
                return self.unary()
            if v == "~":
                e = self.unary()
                if not e.is_const:
                    raise FerruleError("'~' needs a constant operand")
                return Expr(~e.const)
            if v == "(":
                e = self.binary(0)
                if self.take() != ("op", ")"):
                    raise FerruleError("missing ')' in expression")
                return e
        raise FerruleError(f"unexpected {'end of expression' if kind is None else repr(v)} in expression")


def parse_expr(text, lookup=lambda n: None):
    return Parser(text, lookup).parse()
