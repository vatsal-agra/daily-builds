"""Tokenizer + recursive-descent parser for ordinary math notation.

Grammar (precedence low -> high): sum (+ -), product (* / and implicit
multiplication), unary (+ -), power (^ or **, right-associative), primary
(number, identifier, function call, parenthesized expression).
"""

from __future__ import annotations

import re
from fractions import Fraction

from .expr import E, I, PI, Expr, FUNC_NAMES, Num, Symbol, add, func_, mul, pow_

_TOKEN_RE = re.compile(
    r"""
      (?P<NUMBER>\d+\.\d+|\d+)
    | (?P<IDENT>[A-Za-z_][A-Za-z_0-9]*)
    | (?P<POW>\*\*|\^)
    | (?P<OP>[+\-*/(),])
    | (?P<WS>\s+)
    """,
    re.VERBOSE,
)


class ParseError(Exception):
    pass


def tokenize(text: str):
    tokens = []
    pos = 0
    while pos < len(text):
        m = _TOKEN_RE.match(text, pos)
        if not m:
            raise ParseError(f"unexpected character {text[pos]!r} at position {pos}")
        pos = m.end()
        kind = m.lastgroup
        if kind == "WS":
            continue
        tokens.append((kind, m.group()))
    tokens.append(("EOF", ""))
    return tokens


_CONSTANTS = {"pi": PI, "e": E, "i": I}


class Parser:
    def __init__(self, text: str):
        self.tokens = tokenize(text)
        self.pos = 0
        self.text = text

    def peek(self):
        return self.tokens[self.pos]

    def advance(self):
        tok = self.tokens[self.pos]
        self.pos += 1
        return tok

    def expect(self, kind, value=None):
        k, v = self.peek()
        if k != kind or (value is not None and v != value):
            raise ParseError(f"expected {value or kind!r}, got {v or k!r} in {self.text!r}")
        return self.advance()

    def at_factor_start(self) -> bool:
        k, v = self.peek()
        if k in ("NUMBER", "IDENT"):
            return True
        if k == "OP" and v == "(":
            return True
        return False

    def parse(self) -> Expr:
        e = self.parse_sum()
        k, v = self.peek()
        if k != "EOF":
            raise ParseError(f"unexpected trailing input {v!r} in {self.text!r}")
        return e

    def parse_sum(self) -> Expr:
        left = self.parse_product()
        while True:
            k, v = self.peek()
            if k == "OP" and v == "+":
                self.advance()
                left = add(left, self.parse_product())
            elif k == "OP" and v == "-":
                self.advance()
                left = add(left, mul(Num(-1), self.parse_product()))
            else:
                break
        return left

    def parse_product(self) -> Expr:
        left = self.parse_unary()
        while True:
            k, v = self.peek()
            if k == "OP" and v == "*":
                self.advance()
                left = mul(left, self.parse_unary())
            elif k == "OP" and v == "/":
                self.advance()
                left = mul(left, pow_(self.parse_unary(), Num(-1)))
            elif self.at_factor_start():
                # implicit multiplication: "2x", "x(x+1)", "2 sin(x)"
                left = mul(left, self.parse_unary())
            else:
                break
        return left

    def parse_unary(self) -> Expr:
        k, v = self.peek()
        if k == "OP" and v == "-":
            self.advance()
            return mul(Num(-1), self.parse_unary())
        if k == "OP" and v == "+":
            self.advance()
            return self.parse_unary()
        return self.parse_power()

    def parse_power(self) -> Expr:
        base = self.parse_primary()
        k, v = self.peek()
        if k == "POW":
            self.advance()
            exponent = self.parse_unary()
            return pow_(base, exponent)
        return base

    def parse_primary(self) -> Expr:
        k, v = self.advance()
        if k == "NUMBER":
            return Num(Fraction(v))
        if k == "IDENT":
            if v in FUNC_NAMES:
                self.expect("OP", "(")
                arg = self.parse_sum()
                self.expect("OP", ")")
                return func_(v, arg)
            if v in _CONSTANTS:
                return _CONSTANTS[v]
            return Symbol(v)
        if k == "OP" and v == "(":
            e = self.parse_sum()
            self.expect("OP", ")")
            return e
        raise ParseError(f"unexpected token {v!r} in {self.text!r}")


def parse(text: str) -> Expr:
    return Parser(text).parse()


def parse_equation(text: str):
    """Split "lhs = rhs" and parse both sides. If there's no '=', treat the
    whole thing as "expr = 0"."""
    if "=" in text:
        lhs_s, rhs_s = text.split("=", 1)
        return parse(lhs_s), parse(rhs_s)
    return parse(text), Num(0)
