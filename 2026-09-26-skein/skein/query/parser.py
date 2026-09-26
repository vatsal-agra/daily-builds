"""Recursive-descent parser for SkeinQL: tokens -> Statement AST."""
from .lexer import tokenize
from .ast import (
    NodePattern, RelPattern, PathPattern, Literal, VarRef, PropAccess,
    UnaryOp, BinOp, FuncCall, ReturnItem, OrderItem, Statement,
)


class ParseError(Exception):
    pass


_COMPARE_OPS = {"=": "=", "NEQ": "<>", "<": "<", "LTE": "<=", ">": ">", "GTE": ">="}


class Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.i = 0

    def peek(self):
        return self.tokens[self.i]

    def check(self, kind):
        return self.tokens[self.i].kind == kind

    def check_any(self, *kinds):
        return self.tokens[self.i].kind in kinds

    def advance(self):
        tok = self.tokens[self.i]
        self.i += 1
        return tok

    def expect(self, kind):
        tok = self.tokens[self.i]
        if tok.kind != kind:
            raise ParseError(f"expected {kind} but got {tok.kind!r} at position {tok.pos}")
        self.i += 1
        return tok

    # ------------------------------------------------------------ pattern --

    def parse_node_pattern(self):
        self.expect("(")
        var = None
        if self.check("IDENT"):
            var = self.advance().value
        labels = []
        while self.check(":"):
            self.advance()
            labels.append(self.expect("IDENT").value)
        props = {}
        if self.check("{"):
            props = self.parse_prop_map()
        self.expect(")")
        return NodePattern(var, labels, props)

    def parse_rel_body(self):
        var, types, props = None, [], {}
        if self.check("["):
            self.advance()
            if self.check("IDENT"):
                var = self.advance().value
            if self.check(":"):
                self.advance()
                types.append(self.expect("IDENT").value)
                while self.check("|"):
                    self.advance()
                    types.append(self.expect("IDENT").value)
            if self.check("{"):
                props = self.parse_prop_map()
            self.expect("]")
        return var, types, props

    def parse_rel_pattern(self):
        if self.check("ARROW_L"):
            self.advance()
            var, types, props = self.parse_rel_body()
            self.expect("-")
            return RelPattern(var, types, props, "<-")
        if self.check("-"):
            self.advance()
            var, types, props = self.parse_rel_body()
            self.expect("ARROW_R")
            return RelPattern(var, types, props, "->")
        raise ParseError(f"expected a relationship arrow at position {self.peek().pos}")

    def parse_pattern(self):
        elements = [self.parse_node_pattern()]
        while self.check_any("-", "ARROW_L"):
            rel = self.parse_rel_pattern()
            node = self.parse_node_pattern()
            elements.append(rel)
            elements.append(node)
        return PathPattern(elements)

    def parse_prop_map(self):
        self.expect("{")
        props = {}
        if not self.check("}"):
            while True:
                key = self.expect("IDENT").value
                self.expect(":")
                props[key] = self.parse_literal_value()
                if self.check(","):
                    self.advance()
                    continue
                break
        self.expect("}")
        return props

    def parse_literal_value(self):
        if self.check("-"):
            self.advance()
            return -self.expect("NUMBER").value
        tok = self.advance()
        if tok.kind in ("NUMBER", "STRING"):
            return tok.value
        if tok.kind == "TRUE":
            return True
        if tok.kind == "FALSE":
            return False
        if tok.kind == "NULL":
            return None
        raise ParseError(f"expected a literal value, got {tok.kind!r} at position {tok.pos}")

    # --------------------------------------------------------- expressions --

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.check("OR"):
            self.advance()
            left = BinOp("OR", left, self.parse_and())
        return left

    def parse_and(self):
        left = self.parse_not()
        while self.check("AND"):
            self.advance()
            left = BinOp("AND", left, self.parse_not())
        return left

    def parse_not(self):
        if self.check("NOT"):
            self.advance()
            return UnaryOp("NOT", self.parse_not())
        return self.parse_comparison()

    def parse_comparison(self):
        left = self.parse_additive()
        if self.check_any("=", "NEQ", "<", "LTE", ">", "GTE"):
            op = _COMPARE_OPS[self.advance().kind]
            right = self.parse_additive()
            return BinOp(op, left, right)
        return left

    def parse_additive(self):
        left = self.parse_multiplicative()
        while self.check_any("+", "-"):
            op = self.advance().kind
            left = BinOp(op, left, self.parse_multiplicative())
        return left

    def parse_multiplicative(self):
        left = self.parse_unary()
        while self.check_any("*", "/"):
            op = self.advance().kind
            left = BinOp(op, left, self.parse_unary())
        return left

    def parse_unary(self):
        if self.check("-"):
            self.advance()
            return UnaryOp("-", self.parse_unary())
        return self.parse_primary()

    def parse_primary(self):
        tok = self.peek()
        if tok.kind == "NUMBER":
            self.advance()
            return Literal(tok.value)
        if tok.kind == "STRING":
            self.advance()
            return Literal(tok.value)
        if tok.kind == "TRUE":
            self.advance()
            return Literal(True)
        if tok.kind == "FALSE":
            self.advance()
            return Literal(False)
        if tok.kind == "NULL":
            self.advance()
            return Literal(None)
        if tok.kind == "(":
            self.advance()
            expr = self.parse_expr()
            self.expect(")")
            return expr
        if tok.kind == "IDENT":
            name = self.advance().value
            if self.check("("):
                self.advance()
                args = []
                if self.check("*"):
                    self.advance()
                    args.append(VarRef("*"))
                elif not self.check(")"):
                    args.append(self.parse_expr())
                    while self.check(","):
                        self.advance()
                        args.append(self.parse_expr())
                self.expect(")")
                return FuncCall(name, args)
            if self.check("."):
                self.advance()
                prop = self.expect("IDENT").value
                return PropAccess(name, prop)
            return VarRef(name)
        raise ParseError(f"unexpected token {tok.kind!r} at position {tok.pos}")

    # ---------------------------------------------------------- statement --

    def parse_set_items(self):
        items = []
        while True:
            var = self.expect("IDENT").value
            self.expect(".")
            prop = self.expect("IDENT").value
            self.expect("=")
            items.append((PropAccess(var, prop), self.parse_expr()))
            if self.check(","):
                self.advance()
                continue
            break
        return items

    def parse_ident_list(self):
        items = [self.expect("IDENT").value]
        while self.check(","):
            self.advance()
            items.append(self.expect("IDENT").value)
        return items

    def parse_return_items(self):
        items = []
        while True:
            expr = self.parse_expr()
            alias = None
            if self.check("AS"):
                self.advance()
                alias = self.expect("IDENT").value
            items.append(ReturnItem(expr, alias))
            if self.check(","):
                self.advance()
                continue
            break
        return items

    def parse_order_items(self):
        items = []
        while True:
            expr = self.parse_expr()
            desc = False
            if self.check("ASC"):
                self.advance()
            elif self.check("DESC"):
                self.advance()
                desc = True
            items.append(OrderItem(expr, desc))
            if self.check(","):
                self.advance()
                continue
            break
        return items

    def parse_statement(self):
        stmt = Statement()
        if self.check("MATCH"):
            self.advance()
            stmt.match = self.parse_pattern()
            if self.check("WHERE"):
                self.advance()
                stmt.where = self.parse_expr()

        saw_clause = False
        while True:
            if self.check("SET"):
                self.advance()
                stmt.set_items = self.parse_set_items()
                saw_clause = True
            elif self.check("CREATE"):
                self.advance()
                if stmt.create is None:
                    stmt.create = []
                stmt.create.append(self.parse_pattern())
                saw_clause = True
            elif self.check_any("DETACH", "DELETE"):
                detach = False
                if self.check("DETACH"):
                    self.advance()
                    detach = True
                self.expect("DELETE")
                stmt.detach = detach
                stmt.delete_vars = self.parse_ident_list()
                saw_clause = True
            elif self.check("RETURN"):
                self.advance()
                stmt.return_items = self.parse_return_items()
                if self.check("ORDER"):
                    self.advance()
                    self.expect("BY")
                    stmt.order_by = self.parse_order_items()
                if self.check("LIMIT"):
                    self.advance()
                    stmt.limit = int(self.expect("NUMBER").value)
                saw_clause = True
            else:
                break

        if not self.check("EOF"):
            tok = self.peek()
            raise ParseError(f"unexpected trailing token {tok.kind!r} at position {tok.pos}")
        if stmt.match is None and stmt.create is None:
            raise ParseError("a statement needs at least a MATCH or a CREATE clause")
        if stmt.match is not None and not saw_clause:
            raise ParseError("MATCH must be followed by RETURN, SET, CREATE, or DELETE")
        return stmt


def parse(text: str) -> Statement:
    return Parser(tokenize(text)).parse_statement()
