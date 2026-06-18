"""Pratt (precedence-climbing) parser: tokens -> AST.

Grammar (informal):
  program     := declaration* EOF
  declaration := letDecl | fnDecl | statement
  statement   := exprStmt | printStmt | block | if | while | for
               | return | break | continue
  expression  := assignment
  assignment  := (call ".")? IDENT "=" assignment | logic_or
  ...standard precedence climbing below...
"""

from . import ast_nodes as A
from .errors import ParseError
from .lexer import T, tokenize


# Binary operator precedence levels (higher binds tighter).
# Used by the Pratt expression parser.
PRECEDENCE = {
    T.OR: 1,
    T.AND: 2,
    T.EQ_EQ: 3, T.BANG_EQ: 3,
    T.LT: 4, T.LE: 4, T.GT: 4, T.GE: 4,
    T.PLUS: 5, T.MINUS: 5,
    T.STAR: 6, T.SLASH: 6, T.PERCENT: 6,
}


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    # -- token helpers --
    def _peek(self, ahead=0):
        i = self.pos + ahead
        if i >= len(self.tokens):
            return self.tokens[-1]
        return self.tokens[i]

    def _advance(self):
        tok = self.tokens[self.pos]
        if tok.type != T.EOF:
            self.pos += 1
        return tok

    def _check(self, type_):
        return self._peek().type == type_

    def _match(self, *types):
        if self._peek().type in types:
            return self._advance()
        return None

    def _expect(self, type_, message):
        if self._check(type_):
            return self._advance()
        tok = self._peek()
        raise ParseError(message, tok.line, tok.col)

    # -- entry --
    def parse(self):
        stmts = []
        while not self._check(T.EOF):
            stmts.append(self._declaration())
        return stmts

    # -- declarations / statements --
    def _declaration(self):
        if self._check(T.LET):
            return self._let_decl()
        if self._check(T.FN) and self._peek(1).type == T.IDENT:
            return self._fn_decl()
        return self._statement()

    def _let_decl(self):
        kw = self._advance()
        name_tok = self._expect(T.IDENT, "expected variable name after 'let'")
        initializer = None
        if self._match(T.EQ):
            initializer = self._expression()
        self._expect(T.SEMICOLON, "expected ';' after let declaration")
        return A.LetStmt(name_tok.value, initializer, kw.line)

    def _fn_decl(self):
        kw = self._advance()  # 'fn'
        name_tok = self._expect(T.IDENT, "expected function name")
        params = self._params()
        self._expect(T.LBRACE, "expected '{' before function body")
        body = self._block_statements()
        return A.FnDecl(name_tok.value, params, body, kw.line)

    def _params(self):
        self._expect(T.LPAREN, "expected '(' after function name")
        params = []
        if not self._check(T.RPAREN):
            while True:
                p = self._expect(T.IDENT, "expected parameter name")
                if p.value in params:
                    raise ParseError(f"duplicate parameter '{p.value}'", p.line, p.col)
                params.append(p.value)
                if not self._match(T.COMMA):
                    break
        self._expect(T.RPAREN, "expected ')' after parameters")
        return params

    def _statement(self):
        tok = self._peek()
        if self._check(T.PRINT):
            return self._print_stmt()
        if self._check(T.LBRACE):
            self._advance()
            return A.Block(self._block_statements(), tok.line)
        if self._check(T.IF):
            return self._if_stmt()
        if self._check(T.WHILE):
            return self._while_stmt()
        if self._check(T.FOR):
            return self._for_stmt()
        if self._check(T.RETURN):
            return self._return_stmt()
        if self._check(T.BREAK):
            self._advance()
            self._expect(T.SEMICOLON, "expected ';' after 'break'")
            return A.BreakStmt(tok.line)
        if self._check(T.CONTINUE):
            self._advance()
            self._expect(T.SEMICOLON, "expected ';' after 'continue'")
            return A.ContinueStmt(tok.line)
        return self._expr_stmt()

    def _print_stmt(self):
        kw = self._advance()
        value = self._expression()
        self._expect(T.SEMICOLON, "expected ';' after print value")
        return A.PrintStmt(value, kw.line)

    def _block_statements(self):
        stmts = []
        while not self._check(T.RBRACE) and not self._check(T.EOF):
            stmts.append(self._declaration())
        self._expect(T.RBRACE, "expected '}' after block")
        return stmts

    def _if_stmt(self):
        kw = self._advance()
        self._expect(T.LPAREN, "expected '(' after 'if'")
        cond = self._expression()
        self._expect(T.RPAREN, "expected ')' after if condition")
        then_branch = self._statement()
        else_branch = None
        if self._match(T.ELSE):
            else_branch = self._statement()
        return A.IfStmt(cond, then_branch, else_branch, kw.line)

    def _while_stmt(self):
        kw = self._advance()
        self._expect(T.LPAREN, "expected '(' after 'while'")
        cond = self._expression()
        self._expect(T.RPAREN, "expected ')' after while condition")
        body = self._statement()
        return A.WhileStmt(cond, body, kw.line)

    def _for_stmt(self):
        kw = self._advance()
        self._expect(T.LPAREN, "expected '(' after 'for'")
        # initializer
        if self._match(T.SEMICOLON):
            initializer = None
        elif self._check(T.LET):
            initializer = self._let_decl()
        else:
            initializer = self._expr_stmt()
        # condition
        condition = None
        if not self._check(T.SEMICOLON):
            condition = self._expression()
        self._expect(T.SEMICOLON, "expected ';' after for condition")
        # increment
        increment = None
        if not self._check(T.RPAREN):
            increment = self._expression()
        self._expect(T.RPAREN, "expected ')' after for clauses")
        body = self._statement()
        return A.ForStmt(initializer, condition, increment, body, kw.line)

    def _return_stmt(self):
        kw = self._advance()
        value = None
        if not self._check(T.SEMICOLON):
            value = self._expression()
        self._expect(T.SEMICOLON, "expected ';' after return value")
        return A.ReturnStmt(value, kw.line)

    def _expr_stmt(self):
        expr = self._expression()
        self._expect(T.SEMICOLON, "expected ';' after expression")
        return A.ExprStmt(expr, expr.line)

    # -- expressions (Pratt) --
    def _expression(self):
        return self._assignment()

    def _assignment(self):
        expr = self._binary(0)
        if self._check(T.EQ):
            eq = self._advance()
            value = self._assignment()
            if isinstance(expr, A.Variable):
                return A.Assign(expr.name, value, eq.line)
            if isinstance(expr, A.IndexGet):
                return A.IndexSet(expr.obj, expr.index, value, eq.line)
            raise ParseError("invalid assignment target", eq.line, eq.col)
        return expr

    def _binary(self, min_prec):
        left = self._unary()
        while True:
            tok = self._peek()
            prec = PRECEDENCE.get(tok.type)
            if prec is None or prec < min_prec:
                break
            self._advance()
            # left-associative: parse right side with higher min precedence
            right = self._binary(prec + 1)
            if tok.type in (T.AND, T.OR):
                left = A.Logical(tok.value, left, right, tok.line)
            else:
                left = A.Binary(tok.value, left, right, tok.line)
        return left

    def _unary(self):
        tok = self._peek()
        if tok.type in (T.MINUS, T.BANG, T.NOT):
            self._advance()
            operand = self._unary()
            op = "!" if tok.type in (T.BANG, T.NOT) else "-"
            return A.Unary(op, operand, tok.line)
        return self._call()

    def _call(self):
        expr = self._primary()
        while True:
            if self._check(T.LPAREN):
                expr = self._finish_call(expr)
            elif self._check(T.LBRACKET):
                lb = self._advance()
                index = self._expression()
                self._expect(T.RBRACKET, "expected ']' after index")
                expr = A.IndexGet(expr, index, lb.line)
            elif self._check(T.DOT):
                dot = self._advance()
                name = self._expect(T.IDENT, "expected property name after '.'")
                # sugar: a.b  ==  a["b"]
                expr = A.IndexGet(expr, A.Literal(name.value, dot.line), dot.line)
            else:
                break
        return expr

    def _finish_call(self, callee):
        lp = self._advance()
        args = []
        if not self._check(T.RPAREN):
            while True:
                args.append(self._expression())
                if not self._match(T.COMMA):
                    break
        self._expect(T.RPAREN, "expected ')' after arguments")
        return A.Call(callee, args, lp.line)

    def _primary(self):
        tok = self._peek()
        if tok.type == T.NUMBER:
            self._advance()
            return A.Literal(tok.value, tok.line)
        if tok.type == T.STRING:
            self._advance()
            return A.Literal(tok.value, tok.line)
        if tok.type == T.TRUE:
            self._advance()
            return A.Literal(True, tok.line)
        if tok.type == T.FALSE:
            self._advance()
            return A.Literal(False, tok.line)
        if tok.type == T.NIL:
            self._advance()
            return A.Literal(None, tok.line)
        if tok.type == T.IDENT:
            self._advance()
            return A.Variable(tok.value, tok.line)
        if tok.type == T.LPAREN:
            self._advance()
            expr = self._expression()
            self._expect(T.RPAREN, "expected ')' after expression")
            return expr
        if tok.type == T.LBRACKET:
            return self._list_literal()
        if tok.type == T.LBRACE:
            return self._map_literal()
        if tok.type == T.FN:
            return self._fn_expr()
        raise ParseError(f"unexpected token {self._tok_desc(tok)}", tok.line, tok.col)

    def _list_literal(self):
        lb = self._advance()
        elements = []
        if not self._check(T.RBRACKET):
            while True:
                elements.append(self._expression())
                if not self._match(T.COMMA):
                    break
        self._expect(T.RBRACKET, "expected ']' after list elements")
        return A.ListLit(elements, lb.line)

    def _map_literal(self):
        lb = self._advance()
        pairs = []
        if not self._check(T.RBRACE):
            while True:
                # key: an identifier (treated as string) or an expression
                if self._check(T.IDENT) and self._peek(1).type == T.COLON:
                    name = self._advance()
                    key = A.Literal(name.value, name.line)
                else:
                    key = self._expression()
                self._expect(T.COLON, "expected ':' in map entry")
                value = self._expression()
                pairs.append((key, value))
                if not self._match(T.COMMA):
                    break
        self._expect(T.RBRACE, "expected '}' after map entries")
        return A.MapLit(pairs, lb.line)

    def _fn_expr(self):
        kw = self._advance()
        name = None
        if self._check(T.IDENT):
            name = self._advance().value
        params = self._params()
        self._expect(T.LBRACE, "expected '{' before function body")
        body = self._block_statements()
        return A.FnExpr(name, params, body, kw.line)

    def _tok_desc(self, tok):
        if tok.type == T.EOF:
            return "end of input"
        return repr(tok.value)


def parse(source):
    return Parser(tokenize(source)).parse()
