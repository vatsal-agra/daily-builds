"""Operator-precedence parser for Prolog terms, following the classic
ISO-style algorithm: primary term parsing (which special-cases prefix
operators) followed by a left-to-right scan absorbing infix/postfix
operators whose priority and associativity constraints are satisfied.
"""
from .terms import Atom, Var, Num, Struct, make_list
from .lexer import tokenize, Token

# name -> (priority, 'fy'|'fx')
PREFIX_OPS = {
    ":-": (1200, "fx"), "?-": (1200, "fx"),
    "\\+": (900, "fy"),
    "-": (200, "fy"), "+": (200, "fy"), "\\": (200, "fy"),
}
# name -> (priority, 'xfx'|'xfy'|'yfx')
INFIX_OPS = {
    ":-": (1200, "xfx"), "-->": (1200, "xfx"),
    ";": (1100, "xfy"), "|": (1100, "xfy"),
    "->": (1050, "xfy"), "*->": (1050, "xfy"),
    ",": (1000, "xfy"),
    "\\+": (900, "fy"),  # (also prefix; kept out of infix scan below)
    "=": (700, "xfx"), "\\=": (700, "xfx"),
    "==": (700, "xfx"), "\\==": (700, "xfx"),
    "@<": (700, "xfx"), "@>": (700, "xfx"), "@=<": (700, "xfx"), "@>=": (700, "xfx"),
    "is": (700, "xfx"),
    "=..": (700, "xfx"),
    "<": (700, "xfx"), ">": (700, "xfx"), "=<": (700, "xfx"), ">=": (700, "xfx"),
    "=:=": (700, "xfx"), "=\\=": (700, "xfx"),
    "+": (500, "yfx"), "-": (500, "yfx"), "/\\": (500, "yfx"), "\\/": (500, "yfx"), "xor": (500, "yfx"),
    "*": (400, "yfx"), "/": (400, "yfx"), "//": (400, "yfx"),
    "mod": (400, "yfx"), "rem": (400, "yfx"), "<<": (400, "yfx"), ">>": (400, "yfx"), "div": (400, "yfx"),
    "**": (200, "xfx"), "^": (200, "xfy"),
}
del INFIX_OPS["\\+"]


class ParseError(Exception):
    pass


class Parser:
    """Reads one clause (term ending in `.`) at a time from a token stream."""

    def __init__(self, text):
        self.tokens = tokenize(text)
        self.i = 0
        self.varmap = {}
        self.var_order = []

    def _peek(self):
        return self.tokens[self.i]

    def _advance(self):
        t = self.tokens[self.i]
        self.i += 1
        return t

    def at_eof(self):
        return self._peek().kind == "eof"

    def read_clause(self):
        """Parse and return the next top-level term, or None at EOF.
        Resets the per-clause variable map (each clause has its own
        variable scope)."""
        if self.at_eof():
            return None
        self.varmap = {}
        self.var_order = []
        term, _ = self._parse(1200)
        tok = self._advance()
        if tok.kind != "end":
            raise ParseError(f"expected '.' to end clause, got {tok} near pos {tok.pos}")
        return term

    # ---- core precedence-climbing parser -----------------------------
    def _parse(self, max_priority):
        left, left_pri = self._parse_primary(max_priority)
        return self._parse_infix(left, left_pri, max_priority)

    def _parse_infix(self, left, left_pri, max_priority):
        while True:
            tok = self._peek()
            name = None
            if tok.kind == "atom":
                name = tok.value
            elif tok.kind == "punct" and tok.value in (",", "|", ";"):
                name = tok.value
            if name is None or name not in INFIX_OPS:
                return left, left_pri
            pri, typ = INFIX_OPS[name]
            if pri > max_priority:
                return left, left_pri
            left_max = pri - 1 if typ[0] == "x" else pri
            if left_pri > left_max:
                return left, left_pri
            right_max = pri - 1 if typ[2] == "x" else pri
            # Don't consume an infix op if nothing valid could follow it
            # (e.g. trailing comma before ')').
            save = self.i
            self._advance()
            if not self._can_start_term():
                self.i = save
                return left, left_pri
            right, _ = self._parse(right_max)
            left = Struct(name, (left, right))
            left_pri = pri

    def _can_start_term(self):
        tok = self._peek()
        if tok.kind in ("var", "int", "float", "string", "atom"):
            return True
        if tok.kind == "punct" and tok.value in ("(", "[", "{", "!"):
            return True
        return False

    def _parse_primary(self, max_priority):
        tok = self._peek()

        if tok.kind == "int" or tok.kind == "float":
            self._advance()
            return Num(tok.value), 0

        if tok.kind == "var":
            self._advance()
            return self._var_for(tok.value), 0

        if tok.kind == "string":
            self._advance()
            return make_list([Num(ord(c)) for c in tok.value]), 0

        if tok.kind == "punct":
            if tok.value == "(":
                self._advance()
                term, _ = self._parse(1200)
                self._expect_punct(")")
                return term, 0
            if tok.value == "[":
                self._advance()
                return self._parse_list(), 0
            if tok.value == "{":
                self._advance()
                if self._peek().kind == "punct" and self._peek().value == "}":
                    self._advance()
                    return Atom("{}"), 0
                term, _ = self._parse(1200)
                self._expect_punct("}")
                return Struct("{}", (term,)), 0
            if tok.value == "!":
                self._advance()
                return Atom("!"), 0
            if tok.value == ",":
                # ',' used where a term is expected only happens for the
                # bare atom ',' — not supported as primary; treat as error.
                raise ParseError(f"unexpected ',' at pos {tok.pos}")
            raise ParseError(f"unexpected token {tok} at pos {tok.pos}")

        if tok.kind == "atom":
            name = tok.value
            nxt = self.tokens[self.i + 1]
            # negative number literal: '-' directly followed by a number
            if name == "-" and nxt.kind in ("int", "float") and not nxt.preceded_by_space:
                self._advance()
                numtok = self._advance()
                return Num(-numtok.value), 0
            # compound term: atom immediately followed by '(' (no space)
            if nxt.kind == "punct" and nxt.value == "(" and not nxt.preceded_by_space:
                self._advance()
                self._advance()
                args = self._parse_arglist()
                self._expect_punct(")")
                return Struct(name, args), 0
            # prefix operator
            if name in PREFIX_OPS:
                pri, typ = PREFIX_OPS[name]
                if pri <= max_priority and self._prefix_operand_follows():
                    self._advance()
                    arg_max = pri - 1 if typ == "fx" else pri
                    arg, _ = self._parse(arg_max)
                    return Struct(name, (arg,)), pri
            # plain atom (possibly also an infix/prefix operator used as
            # a 0-ary atom, e.g. `X = (-)`)
            self._advance()
            if name in INFIX_OPS or name in PREFIX_OPS:
                return Atom(name), 1201 if False else max(INFIX_OPS.get(name, (0,))[0],
                                                            PREFIX_OPS.get(name, (0,))[0])
            return Atom(name), 0

        raise ParseError(f"unexpected token {tok} at pos {tok.pos}")

    def _prefix_operand_follows(self):
        """Heuristic: a prefix operator only applies if a term can
        actually follow (otherwise treat the operator name as a plain
        atom, e.g. `X = -`)."""
        nxt = self.tokens[self.i + 1]
        if nxt.kind == "end" or nxt.kind == "eof":
            return False
        if nxt.kind == "punct" and nxt.value in (")", "]", "}", ",", "|"):
            return False
        if nxt.kind == "atom" and nxt.value in INFIX_OPS and nxt.value not in PREFIX_OPS:
            nxt2 = self.tokens[self.i + 2]
            if not (nxt2.kind == "punct" and nxt2.value == "(" and not nxt2.preceded_by_space):
                return False
        return True

    def _parse_arglist(self):
        args = []
        if self._peek().kind == "punct" and self._peek().value == ")":
            return args
        while True:
            term, _ = self._parse(999)
            args.append(term)
            tok = self._peek()
            if tok.kind == "punct" and tok.value == ",":
                self._advance()
                continue
            break
        return args

    def _parse_list(self):
        if self._peek().kind == "punct" and self._peek().value == "]":
            self._advance()
            return Atom("[]")
        items = []
        tail = Atom("[]")
        while True:
            term, _ = self._parse(999)
            items.append(term)
            tok = self._peek()
            if tok.kind == "punct" and tok.value == ",":
                self._advance()
                continue
            if tok.kind == "punct" and tok.value == "|":
                self._advance()
                tail, _ = self._parse(999)
                break
            break
        self._expect_punct("]")
        return make_list(items, tail)

    def _expect_punct(self, value):
        tok = self._advance()
        if not (tok.kind == "punct" and tok.value == value):
            raise ParseError(f"expected {value!r}, got {tok} at pos {tok.pos}")

    def _var_for(self, name):
        if name == "_":
            return Var("_")
        if name not in self.varmap:
            v = Var(name)
            self.varmap[name] = v
            self.var_order.append(name)
        return self.varmap[name]


def parse_program(text):
    """Parse all clauses in text, returning a list of terms."""
    p = Parser(text)
    clauses = []
    while True:
        c = p.read_clause()
        if c is None:
            break
        clauses.append(c)
    return clauses


def parse_term(text):
    """Parse a single term (with trailing '.') and return (term, varmap)."""
    p = Parser(text)
    t = p.read_clause()
    return t, p.varmap
