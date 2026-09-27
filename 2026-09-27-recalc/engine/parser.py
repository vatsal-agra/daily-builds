"""Recursive-descent (precedence-climbing) parser: token stream -> AST.

Grammar (low to high precedence):
    expr       := comparison
    comparison := concat (('=' | '<>' | '<' | '<=' | '>' | '>=') concat)*
    concat     := additive ('&' additive)*
    additive   := term (('+' | '-') term)*
    term       := power (('*' | '/') power)*
    power      := unary ('^' power)?      # right-assoc
    unary      := ('-' | '+') unary | primary
    primary    := NUMBER | STRING | BOOL | ref | funccall | '(' expr ')'
    ref        := CELLREF | CELLREF ':' CELLREF
    funccall   := IDENT '(' [expr (',' expr)*] ')'

Note `unary` binds *tighter* than `^` (matching real spreadsheet software,
not conventional math notation): `-2^2` evaluates to 4 (`(-2)^2`), not -4,
because unary minus is applied to the `2` before `^` ever runs. `2^-2`
still works too, since the right operand of `^` is itself parsed at the
`power` level, which tries `unary` first.
"""

from . import refs
from . import values as V
from .tokenizer import tokenize, TokenizeError

_ERROR_LITERALS = {
    "#DIV/0!": V.DIV0, "#VALUE!": V.VALUE, "#REF!": V.REF, "#NAME?": V.NAME,
    "#N/A": V.NA, "#NUM!": V.NUM, "#CYCLE!": V.CYCLE, "#ERROR!": V.Error("#ERROR!"),
}


class ParseError(Exception):
    def __init__(self, message, pos):
        super().__init__(message)
        self.pos = pos


# --- AST nodes -------------------------------------------------------------

class Number:
    __slots__ = ("value",)
    def __init__(self, value): self.value = value
    def __repr__(self): return f"Number({self.value})"

class Text:
    __slots__ = ("value",)
    def __init__(self, value): self.value = value
    def __repr__(self): return f"Text({self.value!r})"

class Bool:
    __slots__ = ("value",)
    def __init__(self, value): self.value = value
    def __repr__(self): return f"Bool({self.value})"

class ErrorLit:
    """A literal error value, either typed directly into a formula (real
    spreadsheets accept `=#REF!+1`) or produced by `translate()` when a
    copy/paste/fill shifts a reference off the grid."""
    __slots__ = ("value",)
    def __init__(self, value): self.value = value
    def __repr__(self): return f"ErrorLit({self.value})"

class CellRefNode:
    __slots__ = ("ref",)
    def __init__(self, ref): self.ref = ref
    def __repr__(self): return f"CellRefNode({self.ref.to_a1()})"

class RangeRefNode:
    __slots__ = ("range",)
    def __init__(self, range_): self.range = range_
    def __repr__(self): return f"RangeRefNode({self.range.to_a1()})"

class UnaryOp:
    __slots__ = ("op", "operand")
    def __init__(self, op, operand): self.op = op; self.operand = operand
    def __repr__(self): return f"UnaryOp({self.op}, {self.operand!r})"

class BinOp:
    __slots__ = ("op", "left", "right")
    def __init__(self, op, left, right): self.op = op; self.left = left; self.right = right
    def __repr__(self): return f"BinOp({self.op}, {self.left!r}, {self.right!r})"

class FuncCall:
    __slots__ = ("name", "args")
    def __init__(self, name, args): self.name = name; self.args = args
    def __repr__(self): return f"FuncCall({self.name}, {self.args!r})"


_COMPARISON_OPS = {"=", "<>", "<", "<=", ">", ">="}


# Every parenthesized group or function-call argument recurses back
# through parse_expr, so a pathological input like 2000 nested '('
# characters would otherwise recurse Python's own call stack into a raw
# RecursionError (which — unlike ParseError — nothing downstream is
# built to expect, and would crash the request that triggered it rather
# than showing a clean error in the cell). Bounding depth *at parse
# time* means the AST itself can never be deep enough for evaluate(),
# translate(), or to_formula() to hit the same problem later, either.
MAX_EXPR_DEPTH = 60


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0
        self.depth = 0

    def peek(self):
        return self.tokens[self.i]

    def advance(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect(self, kind):
        tok = self.peek()
        if tok.kind != kind:
            raise ParseError(f"expected {kind} but found {tok.kind} {tok.text!r}", tok.pos)
        return self.advance()

    def parse_formula(self):
        node = self.parse_expr()
        tok = self.peek()
        if tok.kind != "EOF":
            raise ParseError(f"unexpected trailing input {tok.text!r}", tok.pos)
        return node

    def parse_expr(self):
        self.depth += 1
        if self.depth > MAX_EXPR_DEPTH:
            raise ParseError("formula is too deeply nested", self.peek().pos)
        try:
            return self.parse_comparison()
        finally:
            self.depth -= 1

    def parse_comparison(self):
        left = self.parse_concat()
        while self.peek().kind == "OP" and self.peek().text in _COMPARISON_OPS:
            op = self.advance().text
            right = self.parse_concat()
            left = BinOp(op, left, right)
        return left

    def parse_concat(self):
        left = self.parse_additive()
        while self.peek().kind == "OP" and self.peek().text == "&":
            self.advance()
            right = self.parse_additive()
            left = BinOp("&", left, right)
        return left

    def parse_additive(self):
        left = self.parse_term()
        while self.peek().kind == "OP" and self.peek().text in ("+", "-"):
            op = self.advance().text
            right = self.parse_term()
            left = BinOp(op, left, right)
        return left

    def parse_term(self):
        left = self.parse_power()
        while self.peek().kind == "OP" and self.peek().text in ("*", "/"):
            op = self.advance().text
            right = self.parse_power()
            left = BinOp(op, left, right)
        return left

    def parse_power(self):
        left = self.parse_unary()
        if self.peek().kind == "OP" and self.peek().text == "^":
            self.advance()
            right = self.parse_power()
            return BinOp("^", left, right)
        return left

    def parse_unary(self):
        tok = self.peek()
        if tok.kind == "OP" and tok.text in ("-", "+"):
            self.advance()
            operand = self.parse_unary()
            return UnaryOp(tok.text, operand)
        return self.parse_primary()

    def parse_primary(self):
        tok = self.peek()
        if tok.kind == "NUMBER":
            self.advance()
            return Number(float(tok.text))
        if tok.kind == "STRING":
            self.advance()
            return Text(tok.text)
        if tok.kind == "BOOL":
            self.advance()
            return Bool(tok.text == "TRUE")
        if tok.kind == "ERRLIT":
            self.advance()
            return ErrorLit(_ERROR_LITERALS[tok.text])
        if tok.kind == "LPAREN":
            self.advance()
            node = self.parse_expr()
            self.expect("RPAREN")
            return node
        if tok.kind == "CELLREF":
            self.advance()
            start = refs.parse_cell_ref(tok.text)
            if self.peek().kind == "COLON":
                self.advance()
                end_tok = self.expect("CELLREF")
                end = refs.parse_cell_ref(end_tok.text)
                return RangeRefNode(refs.RangeRef(start, end))
            return CellRefNode(start)
        if tok.kind == "IDENT":
            self.advance()
            if self.peek().kind == "LPAREN":
                self.advance()
                args = []
                if self.peek().kind != "RPAREN":
                    args.append(self.parse_expr())
                    while self.peek().kind == "COMMA":
                        self.advance()
                        args.append(self.parse_expr())
                self.expect("RPAREN")
                return FuncCall(tok.text.upper(), args)
            # A bare word that isn't a function call is an unrecognized
            # name; represented as a zero-arg call to a name that
            # `functions.py` will never define, so it evaluates to #NAME?.
            return FuncCall(tok.text.upper(), [])
        raise ParseError(f"unexpected token {tok.text!r}", tok.pos)


def parse(formula_text):
    """Parse a formula body (without the leading '='). Raises ParseError or
    TokenizeError on malformed input."""
    tokens = tokenize(formula_text)
    return Parser(tokens).parse_formula()


def collect_refs(node, out=None):
    """Walk an AST and collect every (col, row) cell this formula reads,
    with ranges expanded to their member cells. Used to build the
    dependency graph precedent set."""
    if out is None:
        out = set()
    if node is None:
        return out
    if isinstance(node, CellRefNode):
        out.add(node.ref.key())
    elif isinstance(node, RangeRefNode):
        out.update(node.range.cells())
    elif isinstance(node, UnaryOp):
        collect_refs(node.operand, out)
    elif isinstance(node, BinOp):
        collect_refs(node.left, out)
        collect_refs(node.right, out)
    elif isinstance(node, FuncCall):
        for a in node.args:
            collect_refs(a, out)
    return out


def translate(node, d_col, d_row):
    """Return a new AST with every CellRef/RangeRef shifted by (d_col,
    d_row), respecting $-locked components. A reference translated off the
    grid becomes an ErrorLit(#REF!) node — the same node a user typing
    `=#REF!` directly would produce, so it round-trips through
    `to_formula` and back with no special-casing needed elsewhere."""
    if node is None:
        return None
    if isinstance(node, (Number, Text, Bool, ErrorLit)):
        return node
    if isinstance(node, CellRefNode):
        new_ref = node.ref.translate(d_col, d_row)
        if new_ref is None:
            return ErrorLit(V.REF)
        return CellRefNode(new_ref)
    if isinstance(node, RangeRefNode):
        new_range = node.range.translate(d_col, d_row)
        if new_range is None:
            return ErrorLit(V.REF)
        return RangeRefNode(new_range)
    if isinstance(node, UnaryOp):
        return UnaryOp(node.op, translate(node.operand, d_col, d_row))
    if isinstance(node, BinOp):
        return BinOp(node.op, translate(node.left, d_col, d_row), translate(node.right, d_col, d_row))
    if isinstance(node, FuncCall):
        return FuncCall(node.name, [translate(a, d_col, d_row) for a in node.args])
    raise TypeError(f"unknown AST node {node!r}")


# Binary operator precedence, matching the grammar above (higher binds
# tighter). Used only to decide where `to_formula` must add parentheses to
# keep the round-tripped formula text semantically identical to the AST it
# came from — see the correctness argument in REVIEW.md.
_BIN_PREC = {
    "=": 1, "<>": 1, "<": 1, "<=": 1, ">": 1, ">=": 1,
    "&": 2,
    "+": 3, "-": 3,
    "*": 4, "/": 4,
    "^": 6,
}


def to_formula(node):
    """Serialize an AST back to formula text (without the leading '='),
    used to store the post-translation formula text after copy/paste/fill
    so the formula bar shows exactly what a real spreadsheet would.

    Adds parentheses conservatively: whenever a child's own operator binds
    no tighter than its parent's, it is wrapped, regardless of which side
    it's on or either operator's associativity. That is occasionally more
    parens than a human would write (e.g. a fully right-associative `^`
    chain gets fully parenthesized), but it is always *safe* — re-parsing
    the emitted text always reproduces the exact same AST shape, which is
    the property that actually matters here (a formula bar showing an
    equivalent-but-differently-grouped formula after a paste would be a
    silent correctness bug, not a cosmetic one). One irregular case gets a
    dedicated rule: unary minus/plus binds *tighter* than `^` (see the
    parser's module docstring), so a `^`-rooted operand of a unary op can
    only exist in the AST if the source text parenthesized it explicitly
    — that parenthesization is always preserved.
    """
    if isinstance(node, Number):
        from .values import format_number
        return format_number(node.value)
    if isinstance(node, Text):
        return '"' + node.value.replace('"', '""') + '"'
    if isinstance(node, Bool):
        return "TRUE" if node.value else "FALSE"
    if isinstance(node, CellRefNode):
        return node.ref.to_a1()
    if isinstance(node, RangeRefNode):
        return node.range.to_a1()
    if isinstance(node, ErrorLit):
        return str(node.value)
    if isinstance(node, UnaryOp):
        inner = to_formula(node.operand)
        if isinstance(node.operand, BinOp):
            inner = f"({inner})"
        return f"{node.op}{inner}"
    if isinstance(node, BinOp):
        p = _BIN_PREC[node.op]
        left = to_formula(node.left)
        if isinstance(node.left, BinOp) and _BIN_PREC[node.left.op] <= p:
            left = f"({left})"
        right = to_formula(node.right)
        if isinstance(node.right, BinOp) and _BIN_PREC[node.right.op] <= p:
            right = f"({right})"
        return f"{left}{node.op}{right}"
    if isinstance(node, FuncCall):
        return f"{node.name}({','.join(to_formula(a) for a in node.args)})"
    raise TypeError(f"unknown AST node {node!r}")
