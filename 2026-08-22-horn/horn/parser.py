"""Operator-precedence (Pratt) parser: tokens -> terms -> a loaded program.

Argument lists and list-element positions are parsed at max precedence 999
(strictly below comma's own precedence of 1000) -- exactly how real Prolog
tells "a comma as an argument separator" apart from "a comma as the
conjunction operator" without any extra bookkeeping: at 999, the parser
simply can't absorb a ',' as an operator, so it always falls out to the
argument-list loop instead.
"""

from .errors import HornError
from .lexer import tokenize
from .terms import Atom, Number, Var, Compound, NIL, make_list

INFIX = {
    ":-": (1200, "xfx"),
    ",": (1000, "xfy"),
    "=": (700, "xfx"),
    "\\=": (700, "xfx"),
    "==": (700, "xfx"),
    "\\==": (700, "xfx"),
    "is": (700, "xfx"),
    "<": (700, "xfx"),
    ">": (700, "xfx"),
    "=<": (700, "xfx"),
    ">=": (700, "xfx"),
    "=:=": (700, "xfx"),
    "=\\=": (700, "xfx"),
    "+": (500, "yfx"),
    "-": (500, "yfx"),
    "*": (400, "yfx"),
    "/": (400, "yfx"),
    "//": (400, "yfx"),
    "mod": (400, "yfx"),
    "rem": (400, "yfx"),
    "**": (200, "xfx"),
    "^": (200, "xfy"),
}

PREFIX = {
    ":-": (1200, "fx"),
    "\\+": (900, "fy"),
    "-": (200, "fy"),
    "+": (200, "fy"),
}

_STOP_TYPES = {")", "]", "|", ",", "END", "EOF"}


class Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.pos = 0
        self.varmap = {}

    # -- token helpers --------------------------------------------------
    def peek(self, ahead=0):
        i = self.pos + ahead
        return self.toks[i] if i < len(self.toks) else self.toks[-1]

    def advance(self):
        t = self.toks[self.pos]
        if self.pos < len(self.toks) - 1:
            self.pos += 1
        return t

    def expect(self, type_):
        t = self.advance()
        if t.type != type_:
            raise HornError(
                f"syntax_error: expected {type_!r} but got {t.type} {t.value!r} at position {t.pos}"
            )
        return t

    def _operator_name(self):
        tok = self.peek()
        if tok.type in ("NAME", "SYMOP", ","):
            return tok.value
        return None

    def _can_start_term(self, tok):
        return tok.type not in _STOP_TYPES

    # -- variable scope (fresh per clause) -------------------------------
    def get_var(self, name):
        if name == "_":
            return Var("_")
        if name not in self.varmap:
            self.varmap[name] = Var(name)
        return self.varmap[name]

    # -- expression parsing (precedence climbing) ------------------------
    def parse(self, max_prec):
        term, prec = self._parse_primary(max_prec)
        return self._parse_infix(term, prec, max_prec)

    def _parse_infix(self, left, lprec, max_prec):
        while True:
            name = self._operator_name()
            if name is None or name not in INFIX:
                return left, lprec
            prec, typ = INFIX[name]
            if prec > max_prec:
                return left, lprec
            if typ == "xfx":
                if lprec >= prec:
                    return left, lprec
                ra = prec - 1
            elif typ == "xfy":
                if lprec >= prec:
                    return left, lprec
                ra = prec
            else:  # yfx
                if lprec > prec:
                    return left, lprec
                ra = prec - 1
            self.advance()
            right, _ = self.parse(ra)
            left = Compound(name, [left, right])
            lprec = prec

    def _parse_primary(self, max_prec):
        tok = self.peek()
        if tok.type == "NUMBER":
            self.advance()
            return Number(tok.value), 0
        if tok.type == "VAR":
            self.advance()
            return self.get_var(tok.value), 0
        if tok.type == "STRING":
            self.advance()
            return Atom(tok.value), 0
        if tok.type == "(":
            self.advance()
            term, _ = self.parse(1200)
            self.expect(")")
            return term, 0
        if tok.type == "[":
            return self._parse_list(), 0
        if tok.type == "!":
            self.advance()
            return Atom("!"), 0
        if tok.type in ("NAME", "SYMOP"):
            name = tok.value
            if tok.type == "SYMOP" and name in PREFIX and self._can_start_term(self.peek(1)):
                prec, typ = PREFIX[name]
                if prec <= max_prec:
                    nxt = self.peek(1)
                    if name == "-" and nxt.type == "NUMBER" and nxt.pos == tok.pos + len(name):
                        self.advance()
                        self.advance()
                        return Number(-nxt.value), 0
                    self.advance()
                    max_r = prec if typ == "fy" else prec - 1
                    operand, _ = self.parse(max_r)
                    return Compound(name, [operand]), prec
            self.advance()
            if self.peek().type == "(":
                self.advance()
                args = self._parse_arglist()
                self.expect(")")
                return Compound(name, args), 0
            return Atom(name), 0
        raise HornError(f"syntax_error: unexpected token {tok.type} {tok.value!r} at position {tok.pos}")

    def _parse_arglist(self):
        if self.peek().type == ")":
            return []
        args = [self.parse(999)[0]]
        while self.peek().type == ",":
            self.advance()
            args.append(self.parse(999)[0])
        return args

    def _parse_list(self):
        self.expect("[")
        if self.peek().type == "]":
            self.advance()
            return NIL
        items = [self.parse(999)[0]]
        while self.peek().type == ",":
            self.advance()
            items.append(self.parse(999)[0])
        tail = None
        if self.peek().type == "|":
            self.advance()
            tail = self.parse(999)[0]
        self.expect("]")
        return make_list(items, tail)

    # -- top level: a sequence of '.'-terminated clauses/directives ------
    def parse_program(self):
        items = []
        while self.peek().type != "EOF":
            self.varmap = {}
            term, _ = self.parse(1200)
            self.expect("END")
            if isinstance(term, Compound) and term.functor == ":-" and term.arity == 2:
                items.append(("clause", term.args[0], term.args[1]))
            elif isinstance(term, Compound) and term.functor == ":-" and term.arity == 1:
                items.append(("directive", term.args[0], None))
            else:
                items.append(("clause", term, None))
        return items

    def parse_single_term(self):
        """Parse exactly one term (e.g. a REPL query) and require that it
        consumes the entire input (aside from one optional trailing '.').
        Without this check, stray trailing tokens (a typo, a second clause
        accidentally pasted onto the same line) would silently be dropped
        instead of raising a syntax error -- e.g. "consulted member(X, Y)."
        would otherwise quietly parse as just the atom 'consulted', discard
        everything after it, and go on to (wrongly) report "unknown
        procedure consulted/0" instead of a syntax error naming the real
        problem."""
        self.varmap = {}
        term, _ = self.parse(1200)
        if self.peek().type == "END":
            self.advance()
        if self.peek().type != "EOF":
            tok = self.peek()
            raise HornError(
                f"syntax_error: unexpected trailing input {tok.type} {tok.value!r} at position {tok.pos}"
            )
        return term


def parse_program(text):
    return Parser(tokenize(text)).parse_program()


def parse_term(text):
    return Parser(tokenize(text)).parse_single_term()
