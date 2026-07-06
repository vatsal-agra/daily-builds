"""Recursive-descent parser for the Formulate formula language.

Grammar (precedence low -> high), matching Excel's actual precedence order:

    comparison := concat ( ('='|'<>'|'<'|'<='|'>'|'>=') concat )*
    concat     := additive ( '&' additive )*
    additive   := term ( ('+'|'-') term )*
    term       := unary ( ('*'|'/') unary )*
    unary      := '-' unary | power
    power      := postfix ( '^' unary )*      -- right-assoc, binds unary minus tighter than itself
    postfix    := primary ( '%' )*
    primary    := NUMBER | STRING | BOOL | ref | '(' comparison ')' | funccall
    ref        := [NAME '!'] REF [':' REF]
    funccall   := NAME '(' (comparison (',' comparison)*)? ')'
"""

from . import lexer
from .ast_nodes import (
    Number, String, Bool, CellRef, RangeRef, FuncCall, UnaryOp, PostfixOp, BinOp,
    letters_to_col,
)


class ParseError(Exception):
    def __init__(self, message, pos):
        super().__init__(message)
        self.message = message
        self.pos = pos


def parse_formula(text):
    """Parse formula body (without leading '=') into an AST."""
    tokens = lexer.tokenize(text)
    p = _Parser(tokens)
    node = p.parse_comparison()
    p.expect(lexer.EOF)
    return node


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    def peek(self):
        return self.tokens[self.i]

    def advance(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect(self, kind):
        tok = self.peek()
        if tok.kind != kind:
            raise ParseError(f"expected {kind} but found {tok.kind} ({tok.value!r})", tok.pos)
        return self.advance()

    def parse_comparison(self):
        left = self.parse_concat()
        while self.peek().kind in (lexer.EQ, lexer.NE, lexer.LT, lexer.LE, lexer.GT, lexer.GE):
            op_tok = self.advance()
            right = self.parse_concat()
            left = BinOp(op_tok.value, left, right)
        return left

    def parse_concat(self):
        left = self.parse_additive()
        while self.peek().kind == lexer.AMP:
            self.advance()
            right = self.parse_additive()
            left = BinOp("&", left, right)
        return left

    def parse_additive(self):
        left = self.parse_term()
        while self.peek().kind in (lexer.PLUS, lexer.MINUS):
            op_tok = self.advance()
            right = self.parse_term()
            left = BinOp(op_tok.value, left, right)
        return left

    def parse_term(self):
        left = self.parse_unary()
        while self.peek().kind in (lexer.STAR, lexer.SLASH):
            op_tok = self.advance()
            right = self.parse_unary()
            left = BinOp(op_tok.value, left, right)
        return left

    def parse_unary(self):
        if self.peek().kind == lexer.MINUS:
            self.advance()
            operand = self.parse_unary()
            return UnaryOp("-", operand)
        return self.parse_power()

    def parse_power(self):
        left = self.parse_postfix()
        if self.peek().kind == lexer.CARET:
            self.advance()
            right = self.parse_unary()  # right-assoc; allows 2^-1
            return BinOp("^", left, right)
        return left

    def parse_postfix(self):
        node = self.parse_primary()
        while self.peek().kind == lexer.PERCENT:
            self.advance()
            node = PostfixOp("%", node)
        return node

    def parse_primary(self):
        tok = self.peek()
        if tok.kind == lexer.NUMBER:
            self.advance()
            return Number(tok.value)
        if tok.kind == lexer.STRING:
            self.advance()
            return String(tok.value)
        if tok.kind == lexer.BOOL:
            self.advance()
            return Bool(tok.value)
        if tok.kind == lexer.LPAREN:
            self.advance()
            node = self.parse_comparison()
            self.expect(lexer.RPAREN)
            return node
        if tok.kind == lexer.NAME:
            # Could be `NAME!REF...` (sheet-qualified ref) or `NAME(args)` (function call).
            name = self.advance().value
            if self.peek().kind == lexer.BANG:
                self.advance()
                return self._parse_ref(sheet=name)
            if self.peek().kind == lexer.LPAREN:
                return self._parse_funccall(name)
            raise ParseError(f"unexpected name {name!r} (not a function call or sheet ref)", tok.pos)
        if tok.kind == lexer.REF:
            return self._parse_ref(sheet=None)
        raise ParseError(f"unexpected token {tok.kind} ({tok.value!r})", tok.pos)

    def _parse_funccall(self, name):
        self.expect(lexer.LPAREN)
        args = []
        if self.peek().kind != lexer.RPAREN:
            args.append(self.parse_comparison())
            while self.peek().kind == lexer.COMMA:
                self.advance()
                args.append(self.parse_comparison())
        self.expect(lexer.RPAREN)
        return FuncCall(name, args)

    def _parse_ref(self, sheet):
        first = self._parse_cellref_token(sheet)
        if self.peek().kind == lexer.COLON:
            self.advance()
            second_tok = self.expect(lexer.REF)
            second = _cellref_from_text(sheet, second_tok.value)
            return RangeRef(sheet, first, second)
        return first

    def _parse_cellref_token(self, sheet):
        tok = self.expect(lexer.REF)
        return _cellref_from_text(sheet, tok.value)


def _cellref_from_text(sheet, text):
    i = 0
    col_abs = False
    if text[i] == "$":
        col_abs = True
        i += 1
    j = i
    while j < len(text) and text[j].isalpha():
        j += 1
    letters = text[i:j]
    i = j
    row_abs = False
    if i < len(text) and text[i] == "$":
        row_abs = True
        i += 1
    row_digits = text[i:]
    col = letters_to_col(letters)
    row = int(row_digits) - 1
    return CellRef(sheet, col, row, col_abs, row_abs)
