"""Recursive-descent parser: formula text -> AST.

Precedence, loosest to tightest (a deliberate, documented deviation from
Excel's real quirk where unary minus binds *tighter* than `^`, i.e. Excel's
`-2^2` is 4 -- Trellis follows ordinary mathematical/programming-language
convention instead, so `-2^2` is -4, matching Python's `-2**2`):

    comparison   = <> < <= > >=
    concat       &
    additive     + -
    multiplicative * /
    unary        unary + -
    power        ^ (right-associative)
    postfix      % (percent, postfix)
    primary      literals, refs, function calls, ( expr )
"""

from .lexer import tokenize, LexError
from .ast_nodes import (
    NumberLit, StringLit, BoolLit, CellRef, RangeRef, UnaryOp, BinOp, FuncCall,
)
from .addr import parse_addr


class NameRef:
    """An identifier that isn't a recognized cell/range/function/boolean.
    Evaluates to #NAME? -- kept distinct from a parse failure so `=bogus`
    is valid *syntax* (as in real spreadsheets) that fails at evaluation."""

    __slots__ = ("text",)

    def __init__(self, text):
        self.text = text

    def __repr__(self):
        return f"NameRef({self.text!r})"


class ParseError(Exception):
    def __init__(self, message, pos):
        self.pos = pos
        super().__init__(f"{message} (at position {pos})")


_COMPARISON_OPS = {"EQ", "NE", "LT", "LE", "GT", "GE"}
_COMPARISON_SYM = {"EQ": "=", "NE": "<>", "LT": "<", "LE": "<=", "GT": ">", "GE": ">="}


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    def peek(self):
        return self.tokens[self.i]

    def advance(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect(self, type_):
        tok = self.peek()
        if tok.type != type_:
            raise ParseError(f"expected {type_} but got {tok.type} {tok.text!r}", tok.pos)
        return self.advance()

    def parse_formula(self):
        node = self.parse_comparison()
        tok = self.peek()
        if tok.type != "EOF":
            raise ParseError(f"unexpected trailing token {tok.text!r}", tok.pos)
        return node

    def parse_comparison(self):
        node = self.parse_concat()
        while self.peek().type in _COMPARISON_OPS:
            tok = self.advance()
            rhs = self.parse_concat()
            node = BinOp(_COMPARISON_SYM[tok.type], node, rhs)
        return node

    def parse_concat(self):
        node = self.parse_additive()
        while self.peek().type == "AMP":
            self.advance()
            rhs = self.parse_additive()
            node = BinOp("&", node, rhs)
        return node

    def parse_additive(self):
        node = self.parse_multiplicative()
        while self.peek().type in ("PLUS", "MINUS"):
            tok = self.advance()
            rhs = self.parse_multiplicative()
            node = BinOp("+" if tok.type == "PLUS" else "-", node, rhs)
        return node

    def parse_multiplicative(self):
        node = self.parse_unary()
        while self.peek().type in ("STAR", "SLASH"):
            tok = self.advance()
            rhs = self.parse_unary()
            node = BinOp("*" if tok.type == "STAR" else "/", node, rhs)
        return node

    def parse_unary(self):
        tok = self.peek()
        if tok.type in ("PLUS", "MINUS"):
            self.advance()
            operand = self.parse_unary()
            return UnaryOp("-" if tok.type == "MINUS" else "+", operand)
        return self.parse_power()

    def parse_power(self):
        node = self.parse_postfix()
        if self.peek().type == "CARET":
            self.advance()
            rhs = self.parse_unary()  # right-associative
            node = BinOp("^", node, rhs)
        return node

    def parse_postfix(self):
        node = self.parse_primary()
        while self.peek().type == "PERCENT":
            self.advance()
            node = UnaryOp("%", node)
        return node

    def parse_primary(self):
        tok = self.peek()
        if tok.type == "NUMBER":
            self.advance()
            text = tok.text
            value = float(text) if ("." in text or "e" in text or "E" in text) else int(text)
            return NumberLit(value)
        if tok.type == "STRING":
            self.advance()
            return StringLit(tok.text)
        if tok.type == "LPAREN":
            self.advance()
            node = self.parse_comparison()
            self.expect("RPAREN")
            return node
        if tok.type == "IDENT":
            return self.parse_ident_expr()
        raise ParseError(f"unexpected token {tok.type} {tok.text!r}", tok.pos)

    def parse_ident_expr(self):
        tok = self.advance()
        upper = tok.text.upper()
        if upper in ("TRUE", "FALSE"):
            return BoolLit(upper == "TRUE")

        nxt = self.peek()
        if nxt.type == "LPAREN":
            self.advance()
            args = []
            if self.peek().type != "RPAREN":
                args.append(self.parse_comparison())
                while self.peek().type == "COMMA":
                    self.advance()
                    args.append(self.parse_comparison())
            self.expect("RPAREN")
            return FuncCall(upper, args)

        if nxt.type == "BANG":
            self.advance()
            sheet_name = tok.text
            addr_tok = self.expect("IDENT")
            start = self._cellref_from_token(addr_tok, sheet_name)
            if self.peek().type == "COLON":
                self.advance()
                end_tok = self.expect("IDENT")
                end = self._cellref_from_token(end_tok, sheet_name)
                return RangeRef(sheet_name, start, end)
            return start

        start = self._try_cellref(tok, sheet=None)
        if start is not None:
            if self.peek().type == "COLON":
                save = self.i
                colon_tok = self.peek()
                self.advance()
                if self.peek().type != "IDENT":
                    self.i = save
                    return start
                end_tok = self.advance()
                end = self._try_cellref(end_tok, sheet=None)
                if end is None:
                    raise ParseError(
                        f"expected cell address after ':' but got {end_tok.text!r}",
                        end_tok.pos,
                    )
                return RangeRef(None, start, end)
            return start

        return NameRef(tok.text)

    @staticmethod
    def _cellref_from_token(tok, sheet):
        ref = Parser._try_cellref(tok, sheet)
        if ref is None:
            raise ParseError(f"expected a cell address but got {tok.text!r}", tok.pos)
        return ref

    @staticmethod
    def _try_cellref(tok, sheet):
        text = tok.text
        try:
            row, col = parse_addr(text)
        except ValueError:
            return None
        row_abs = text.count("$") >= 1 and text.startswith("$")
        col_abs = "$" in text
        return CellRef(sheet, row, col, row_abs=row_abs, col_abs=col_abs, text=text)


def parse(formula_text):
    """`formula_text` is the formula *without* the leading '='."""
    try:
        tokens = tokenize(formula_text)
    except LexError as e:
        raise ParseError(str(e), e.pos) from e
    return Parser(tokens).parse_formula()
