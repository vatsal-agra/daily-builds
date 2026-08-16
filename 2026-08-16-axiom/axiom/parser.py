"""Tokenizer + recursive-descent/precedence-climbing parser for real math
notation: infix `+ - * /`, `^` for power (right-associative), unary minus,
*implicit* multiplication ("2x", "3(x+1)", "2 sin(x)"), function calls, and
parenthesized grouping. Produces an Axiom expression tree via the smart
constructors in `expr.py`, so the parsed result is already canonicalized.
"""

from fractions import Fraction

from .errors import ParseError
from .expr import ONE, FUNC_NAMES, Symbol, add, func, mul, num, power, sym

_CONST_NAMES = {"pi", "e"}


class Token:
    __slots__ = ("kind", "text", "pos")

    def __init__(self, kind, text, pos):
        self.kind = kind
        self.text = text
        self.pos = pos

    def __repr__(self):
        return f"Token({self.kind!r}, {self.text!r})"


_SINGLE = {"+": "PLUS", "-": "MINUS", "*": "STAR", "/": "SLASH",
           "^": "CARET", "(": "LPAREN", ")": "RPAREN", ",": "COMMA"}


def tokenize(text):
    tokens = []
    i, n = 0, len(text)
    while i < n:
        c = text[i]
        if c.isspace():
            i += 1
            continue
        if c.isdigit() or (c == "." and i + 1 < n and text[i + 1].isdigit()):
            j = i
            seen_dot = False
            while j < n and (text[j].isdigit() or (text[j] == "." and not seen_dot)):
                if text[j] == ".":
                    seen_dot = True
                j += 1
            tokens.append(Token("NUMBER", text[i:j], i))
            i = j
            continue
        if c.isalpha() or c == "_":
            j = i
            while j < n and (text[j].isalnum() or text[j] == "_"):
                j += 1
            tokens.append(Token("IDENT", text[i:j], i))
            i = j
            continue
        if text.startswith("**", i):
            tokens.append(Token("CARET", "**", i))
            i += 2
            continue
        if c in _SINGLE:
            tokens.append(Token(_SINGLE[c], c, i))
            i += 1
            continue
        raise ParseError(f"unexpected character {c!r}", text, i)
    tokens.append(Token("EOF", "", n))
    return tokens


class Parser:
    def __init__(self, text):
        self.text = text
        self.tokens = tokenize(text)
        self.i = 0

    def peek(self):
        return self.tokens[self.i]

    def advance(self):
        t = self.tokens[self.i]
        self.i += 1
        return t

    def expect(self, kind, what):
        t = self.peek()
        if t.kind != kind:
            found = repr(t.text) if t.text else "end of input"
            raise ParseError(f"expected {what}, found {found}", self.text, t.pos)
        return self.advance()

    def parse(self):
        e = self.parse_expr()
        if self.peek().kind != "EOF":
            t = self.peek()
            raise ParseError(f"unexpected {t.text!r}", self.text, t.pos)
        return e

    # expr := term (('+'|'-') term)*
    def parse_expr(self):
        left = self.parse_term()
        while self.peek().kind in ("PLUS", "MINUS"):
            op = self.advance()
            right = self.parse_term()
            left = add(left, right) if op.kind == "PLUS" else add(left, mul(num(-1), right))
        return left

    _ATOM_START = ("NUMBER", "IDENT", "LPAREN")

    # term := unary (('*'|'/') unary | <implicit-mul-start>)*
    def parse_term(self):
        left = self.parse_unary()
        while True:
            k = self.peek().kind
            if k in ("STAR", "SLASH"):
                op = self.advance()
                right = self.parse_unary()
                left = mul(left, right) if op.kind == "STAR" else mul(left, power(right, num(-1)))
            elif k in self._ATOM_START:
                right = self.parse_unary()
                left = mul(left, right)
            else:
                break
        return left

    # unary := ('-'|'+') unary | power
    def parse_unary(self):
        if self.peek().kind == "MINUS":
            self.advance()
            return mul(num(-1), self.parse_unary())
        if self.peek().kind == "PLUS":
            self.advance()
            return self.parse_unary()
        return self.parse_power()

    # power := postfix ('^' unary)?   (right-associative: 2^3^2 == 2^(3^2))
    def parse_power(self):
        base = self.parse_atom()
        if self.peek().kind == "CARET":
            self.advance()
            exp = self.parse_unary()
            return power(base, exp)
        return base

    def parse_atom(self):
        t = self.peek()
        if t.kind == "NUMBER":
            self.advance()
            return num(Fraction(t.text))
        if t.kind == "LPAREN":
            self.advance()
            e = self.parse_expr()
            self.expect("RPAREN", "')'")
            return e
        if t.kind == "IDENT":
            self.advance()
            name = t.text
            if self.peek().kind == "LPAREN":
                self.advance()
                if name not in FUNC_NAMES:
                    raise ParseError(f"unknown function '{name}'", self.text, t.pos)
                arg = self.parse_expr()
                self.expect("RPAREN", "')'")
                return func(name, arg)
            if name == "pi":
                return Symbol("pi")
            if name == "e":
                return Symbol("e")
            return sym(name)
        found = repr(t.text) if t.text else "end of input"
        raise ParseError(f"unexpected {found}", self.text, t.pos)


def parse(text):
    """Parse a math expression string into an Axiom `Expr`.

    >>> str(parse("2x + 3*(x - 1)^2"))
    '3*(x - 1)^2 + 2*x'
    """
    if not text or not text.strip():
        raise ParseError("empty expression", text or "", 0)
    return Parser(text).parse()
