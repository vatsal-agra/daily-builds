"""Recursive-descent / precedence-climbing parser for Ember.

Grammar (lowest to highest precedence):

    program    := fn_def*
    fn_def     := 'fn' IDENT '(' (IDENT (',' IDENT)*)? ')' block
    block      := '{' stmt* '}'
    stmt       := let_stmt | assign_stmt | if_stmt | while_stmt
                | return_stmt | expr_stmt | block
    let_stmt   := 'let' IDENT '=' expr ';'
    assign_stmt:= IDENT '=' expr ';'
    if_stmt    := 'if' '(' expr ')' block ('else' (if_stmt | block))?
    while_stmt := 'while' '(' expr ')' block
    return_stmt:= 'return' expr? ';'
    expr_stmt  := expr ';'

    expr       := or_expr
    or_expr    := and_expr ('||' and_expr)*
    and_expr   := equality ('&&' equality)*
    equality   := relational (('==' | '!=') relational)*
    relational := additive (('<' | '<=' | '>' | '>=') additive)*
    additive   := term (('+' | '-') term)*
    term       := unary (('*' | '/' | '%') unary)*
    unary      := ('-' | '!') unary | primary
    primary    := INT | 'true' | 'false' | IDENT | IDENT '(' args? ')'
                | '(' expr ')'
    args       := expr (',' expr)*
"""

from .lexer import tokenize
from .ast_nodes import (
    Program, FnDef, Block,
    LetStmt, AssignStmt, IfStmt, WhileStmt, ReturnStmt, ExprStmt,
    IntLit, BoolLit, VarRef, UnaryOp, BinOp, Call,
)

MAX_PARAMS = 6  # System V AMD64 integer-argument registers: rdi/rsi/rdx/rcx/r8/r9


class ParseError(Exception):
    def __init__(self, message, line, col):
        super().__init__(f"line {line}, col {col}: {message}")
        self.message = message
        self.line = line
        self.col = col


class Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.i = 0

    def _cur(self):
        return self.toks[self.i]

    def _at_end(self):
        return self._cur().kind == "EOF"

    def _check(self, kind, text=None):
        tok = self._cur()
        if tok.kind != kind:
            return False
        return text is None or tok.text == text

    def _match(self, kind, text=None):
        if self._check(kind, text):
            return self._advance()
        return None

    def _advance(self):
        tok = self.toks[self.i]
        if self.i < len(self.toks) - 1:
            self.i += 1
        return tok

    def _expect(self, kind, text=None, what=None):
        tok = self._cur()
        if not self._check(kind, text):
            wanted = what or (text or kind)
            raise ParseError(
                f"expected {wanted!r} but found {tok.text or tok.kind!r}",
                tok.line, tok.col,
            )
        return self._advance()

    # ---- top level ----

    def parse_program(self):
        functions = []
        while not self._at_end():
            functions.append(self._parse_fn_def())
        return Program(functions)

    def _parse_fn_def(self):
        tok = self._expect("KW", "fn")
        name_tok = self._expect("IDENT", what="function name")
        self._expect("SYM", "(")
        params = []
        if not self._check("SYM", ")"):
            params.append(self._expect("IDENT", what="parameter name").text)
            while self._match("SYM", ","):
                params.append(self._expect("IDENT", what="parameter name").text)
        self._expect("SYM", ")")
        if len(params) > MAX_PARAMS:
            raise ParseError(
                f"function {name_tok.text!r} has {len(params)} parameters; "
                f"Ember supports at most {MAX_PARAMS} (System V register args)",
                name_tok.line, name_tok.col,
            )
        if len(set(params)) != len(params):
            raise ParseError(
                f"function {name_tok.text!r} has duplicate parameter names",
                name_tok.line, name_tok.col,
            )
        body = self._parse_block()
        return FnDef(name_tok.text, params, body, tok.line)

    def _parse_block(self):
        self._expect("SYM", "{")
        stmts = []
        while not self._check("SYM", "}"):
            if self._at_end():
                tok = self._cur()
                raise ParseError("unterminated block, expected '}'", tok.line, tok.col)
            stmts.append(self._parse_stmt())
        self._expect("SYM", "}")
        return Block(stmts)

    # ---- statements ----

    def _parse_stmt(self):
        tok = self._cur()
        if self._check("SYM", "{"):
            return self._parse_block()
        if self._check("KW", "let"):
            return self._parse_let()
        if self._check("KW", "if"):
            return self._parse_if()
        if self._check("KW", "while"):
            return self._parse_while()
        if self._check("KW", "return"):
            return self._parse_return()
        if self._check("IDENT") and self.toks[self.i + 1].kind == "SYM" and self.toks[self.i + 1].text == "=":
            return self._parse_assign()
        expr = self._parse_expr()
        self._expect("SYM", ";", what="';'")
        return ExprStmt(expr, tok.line)

    def _parse_let(self):
        tok = self._expect("KW", "let")
        name = self._expect("IDENT", what="variable name").text
        self._expect("SYM", "=")
        expr = self._parse_expr()
        self._expect("SYM", ";", what="';'")
        return LetStmt(name, expr, tok.line)

    def _parse_assign(self):
        name_tok = self._expect("IDENT")
        self._expect("SYM", "=")
        expr = self._parse_expr()
        self._expect("SYM", ";", what="';'")
        return AssignStmt(name_tok.text, expr, name_tok.line)

    def _parse_if(self):
        tok = self._expect("KW", "if")
        self._expect("SYM", "(")
        cond = self._parse_expr()
        self._expect("SYM", ")")
        then_block = self._parse_block()
        else_block = None
        if self._match("KW", "else"):
            if self._check("KW", "if"):
                # `else if` desugars to a single-statement block so the
                # AST stays uniform (IfStmt.else_block is always a Block).
                else_block = Block([self._parse_if()])
            else:
                else_block = self._parse_block()
        return IfStmt(cond, then_block, else_block, tok.line)

    def _parse_while(self):
        tok = self._expect("KW", "while")
        self._expect("SYM", "(")
        cond = self._parse_expr()
        self._expect("SYM", ")")
        body = self._parse_block()
        return WhileStmt(cond, body, tok.line)

    def _parse_return(self):
        tok = self._expect("KW", "return")
        expr = None
        if not self._check("SYM", ";"):
            expr = self._parse_expr()
        self._expect("SYM", ";", what="';'")
        return ReturnStmt(expr, tok.line)

    # ---- expressions (precedence climbing) ----

    def _parse_expr(self):
        return self._parse_or()

    def _parse_or(self):
        left = self._parse_and()
        while self._check("SYM", "||"):
            tok = self._advance()
            right = self._parse_and()
            left = BinOp("||", left, right, tok.line)
        return left

    def _parse_and(self):
        left = self._parse_equality()
        while self._check("SYM", "&&"):
            tok = self._advance()
            right = self._parse_equality()
            left = BinOp("&&", left, right, tok.line)
        return left

    def _parse_equality(self):
        left = self._parse_relational()
        while self._check("SYM", "==") or self._check("SYM", "!="):
            tok = self._advance()
            right = self._parse_relational()
            left = BinOp(tok.text, left, right, tok.line)
        return left

    def _parse_relational(self):
        left = self._parse_additive()
        while self._cur().kind == "SYM" and self._cur().text in ("<", "<=", ">", ">="):
            tok = self._advance()
            right = self._parse_additive()
            left = BinOp(tok.text, left, right, tok.line)
        return left

    def _parse_additive(self):
        left = self._parse_term()
        while self._cur().kind == "SYM" and self._cur().text in ("+", "-"):
            tok = self._advance()
            right = self._parse_term()
            left = BinOp(tok.text, left, right, tok.line)
        return left

    def _parse_term(self):
        left = self._parse_unary()
        while self._cur().kind == "SYM" and self._cur().text in ("*", "/", "%"):
            tok = self._advance()
            right = self._parse_unary()
            left = BinOp(tok.text, left, right, tok.line)
        return left

    def _parse_unary(self):
        if self._cur().kind == "SYM" and self._cur().text in ("-", "!"):
            tok = self._advance()
            operand = self._parse_unary()
            return UnaryOp(tok.text, operand, tok.line)
        return self._parse_primary()

    def _parse_primary(self):
        tok = self._cur()
        if tok.kind == "INT":
            self._advance()
            return IntLit(tok.value, tok.line)
        if tok.kind == "KW" and tok.text == "true":
            self._advance()
            return BoolLit(True, tok.line)
        if tok.kind == "KW" and tok.text == "false":
            self._advance()
            return BoolLit(False, tok.line)
        if tok.kind == "IDENT":
            self._advance()
            if self._match("SYM", "("):
                args = []
                if not self._check("SYM", ")"):
                    args.append(self._parse_expr())
                    while self._match("SYM", ","):
                        args.append(self._parse_expr())
                self._expect("SYM", ")")
                if len(args) > MAX_PARAMS:
                    raise ParseError(
                        f"call to {tok.text!r} has {len(args)} arguments; "
                        f"Ember supports at most {MAX_PARAMS}",
                        tok.line, tok.col,
                    )
                return Call(tok.text, args, tok.line)
            return VarRef(tok.text, tok.line)
        if tok.kind == "SYM" and tok.text == "(":
            self._advance()
            expr = self._parse_expr()
            self._expect("SYM", ")")
            return expr
        raise ParseError(f"unexpected token {tok.text or tok.kind!r}", tok.line, tok.col)


def parse(source: str) -> Program:
    tokens = tokenize(source)
    return Parser(tokens).parse_program()
