"""Recursive-descent parser for Pebble: tokens -> AST."""

from dataclasses import dataclass, field
from .lexer import tokenize, PebbleSyntaxError


@dataclass
class FuncDecl:
    name: str
    params: list
    body: list  # list of statements


@dataclass
class Let:
    name: str
    expr: object


@dataclass
class Assign:
    name: str
    expr: object


@dataclass
class If:
    cond: object
    then_body: list
    else_body: list  # possibly []


@dataclass
class While:
    cond: object
    body: list


@dataclass
class Return:
    expr: object


@dataclass
class Print:
    expr: object


@dataclass
class ExprStmt:
    expr: object


@dataclass
class IntLit:
    value: int


@dataclass
class Var:
    name: str


@dataclass
class BinOp:
    op: str
    left: object
    right: object


@dataclass
class UnaryOp:
    op: str
    expr: object


@dataclass
class Call:
    name: str
    args: list


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos]

    def at(self, kind, text=None):
        t = self.peek()
        return t.kind == kind and (text is None or t.text == text)

    def advance(self):
        t = self.tokens[self.pos]
        self.pos += 1
        return t

    def expect(self, kind, text=None):
        if not self.at(kind, text):
            t = self.peek()
            expected = text or kind
            raise PebbleSyntaxError(f"line {t.line}: expected {expected!r}, got {t.text!r}")
        return self.advance()

    def parse_program(self):
        funcs = []
        while not self.at("eof"):
            funcs.append(self.parse_funcdecl())
        return funcs

    def parse_funcdecl(self):
        self.expect("kw", "fn")
        name = self.expect("ident").text
        self.expect("sym", "(")
        params = []
        if not self.at("sym", ")"):
            params.append(self.expect("ident").text)
            while self.at("sym", ","):
                self.advance()
                params.append(self.expect("ident").text)
        self.expect("sym", ")")
        self.expect("sym", "->")
        self.expect("ident", "i32")
        body = self.parse_block()
        return FuncDecl(name, params, body)

    def parse_block(self):
        self.expect("sym", "{")
        stmts = []
        while not self.at("sym", "}"):
            stmts.append(self.parse_stmt())
        self.expect("sym", "}")
        return stmts

    def parse_stmt(self):
        if self.at("kw", "let"):
            self.advance()
            name = self.expect("ident").text
            self.expect("sym", "=")
            expr = self.parse_expr()
            self.expect("sym", ";")
            return Let(name, expr)
        if self.at("kw", "if"):
            self.advance()
            self.expect("sym", "(")
            cond = self.parse_expr()
            self.expect("sym", ")")
            then_body = self.parse_block()
            else_body = []
            if self.at("kw", "else"):
                self.advance()
                else_body = self.parse_block()
            return If(cond, then_body, else_body)
        if self.at("kw", "while"):
            self.advance()
            self.expect("sym", "(")
            cond = self.parse_expr()
            self.expect("sym", ")")
            body = self.parse_block()
            return While(cond, body)
        if self.at("kw", "return"):
            self.advance()
            expr = self.parse_expr()
            self.expect("sym", ";")
            return Return(expr)
        if self.at("kw", "print"):
            self.advance()
            self.expect("sym", "(")
            expr = self.parse_expr()
            self.expect("sym", ")")
            self.expect("sym", ";")
            return Print(expr)
        if self.at("ident") and self.tokens[self.pos + 1].kind == "sym" and self.tokens[self.pos + 1].text == "=":
            name = self.advance().text
            self.advance()  # '='
            expr = self.parse_expr()
            self.expect("sym", ";")
            return Assign(name, expr)
        expr = self.parse_expr()
        self.expect("sym", ";")
        return ExprStmt(expr)

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.at("sym", "||"):
            self.advance()
            left = BinOp("||", left, self.parse_and())
        return left

    def parse_and(self):
        left = self.parse_equality()
        while self.at("sym", "&&"):
            self.advance()
            left = BinOp("&&", left, self.parse_equality())
        return left

    def parse_equality(self):
        left = self.parse_comparison()
        while self.at("sym", "==") or self.at("sym", "!="):
            op = self.advance().text
            left = BinOp(op, left, self.parse_comparison())
        return left

    def parse_comparison(self):
        left = self.parse_term()
        while self.peek().kind == "sym" and self.peek().text in ("<", ">", "<=", ">="):
            op = self.advance().text
            left = BinOp(op, left, self.parse_term())
        return left

    def parse_term(self):
        left = self.parse_factor()
        while self.peek().kind == "sym" and self.peek().text in ("+", "-"):
            op = self.advance().text
            left = BinOp(op, left, self.parse_factor())
        return left

    def parse_factor(self):
        left = self.parse_unary()
        while self.peek().kind == "sym" and self.peek().text in ("*", "/", "%"):
            op = self.advance().text
            left = BinOp(op, left, self.parse_unary())
        return left

    def parse_unary(self):
        if self.at("sym", "-"):
            self.advance()
            return UnaryOp("-", self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        t = self.peek()
        if t.kind == "int":
            self.advance()
            return IntLit(int(t.text))
        if t.kind == "ident":
            self.advance()
            if self.at("sym", "("):
                self.advance()
                args = []
                if not self.at("sym", ")"):
                    args.append(self.parse_expr())
                    while self.at("sym", ","):
                        self.advance()
                        args.append(self.parse_expr())
                self.expect("sym", ")")
                return Call(t.text, args)
            return Var(t.text)
        if t.kind == "sym" and t.text == "(":
            self.advance()
            e = self.parse_expr()
            self.expect("sym", ")")
            return e
        raise PebbleSyntaxError(f"line {t.line}: unexpected token {t.text!r}")


def parse(src):
    return Parser(tokenize(src)).parse_program()
