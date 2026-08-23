"""Recursive-descent parser for Runic, producing an AST (see ast_nodes.py)."""

from . import ast_nodes as A


class ParseError(Exception):
    def __init__(self, msg, line, col):
        super().__init__(f"parse error at {line}:{col}: {msg}")


class Parser:
    def __init__(self, tokens):
        self.toks = tokens
        self.pos = 0

    def peek(self, k=0):
        return self.toks[min(self.pos + k, len(self.toks) - 1)]

    def at(self, kind):
        return self.peek().kind == kind

    def advance(self):
        t = self.toks[self.pos]
        if self.pos < len(self.toks) - 1:
            self.pos += 1
        return t

    def expect(self, kind):
        t = self.peek()
        if t.kind != kind:
            raise ParseError(f"expected {kind!r}, got {t.kind!r} ({t.value!r})", t.line, t.col)
        return self.advance()

    # --- top level -----------------------------------------------------

    def parse_program(self):
        arrays = []
        funcs = []
        while not self.at("EOF"):
            if self.at("array"):
                arrays.append(self.parse_array_decl())
            elif self.at("fn"):
                funcs.append(self.parse_func_decl())
            else:
                t = self.peek()
                raise ParseError(f"expected 'fn' or 'array' at top level, got {t.kind!r}", t.line, t.col)
        return A.Program(arrays, funcs)

    def parse_array_decl(self):
        line = self.peek().line
        self.expect("array")
        name = self.expect("IDENT").value
        self.expect("[")
        size_tok = self.expect("INT")
        size = size_tok.value
        if size <= 0:
            raise ParseError("array size must be positive", size_tok.line, size_tok.col)
        self.expect("]")
        init = None
        if self.at("="):
            self.advance()
            self.expect("{")
            init = []
            if not self.at("}"):
                init.append(self.expect("INT").value)
                while self.at(","):
                    self.advance()
                    init.append(self.expect("INT").value)
            self.expect("}")
            if len(init) > size:
                raise ParseError(f"array {name!r} initializer has more elements than declared size", line, 0)
        self.expect(";")
        return A.ArrayDecl(name, size, init, line)

    def parse_func_decl(self):
        line = self.peek().line
        self.expect("fn")
        name = self.expect("IDENT").value
        self.expect("(")
        params = []
        if not self.at(")"):
            params.append(self.expect("IDENT").value)
            while self.at(","):
                self.advance()
                params.append(self.expect("IDENT").value)
        self.expect(")")
        body = self.parse_block()
        return A.FuncDecl(name, params, body, line)

    # --- statements ------------------------------------------------------

    def parse_block(self):
        line = self.peek().line
        self.expect("{")
        stmts = []
        while not self.at("}"):
            stmts.append(self.parse_stmt())
        self.expect("}")
        return A.Block(stmts, line)

    def parse_stmt(self):
        t = self.peek()
        if t.kind == "let":
            return self.parse_let()
        if t.kind == "if":
            return self.parse_if()
        if t.kind == "while":
            return self.parse_while()
        if t.kind == "return":
            return self.parse_return()
        if t.kind == "assert":
            return self.parse_assert()
        if t.kind == "{":
            return self.parse_block()
        return self.parse_assign_or_expr_stmt()

    def parse_assert(self):
        line = self.peek().line
        self.expect("assert")
        self.expect("(")
        expr = self.parse_expr()
        self.expect(")")
        self.expect(";")
        return A.AssertStmt(expr, line)

    def parse_let(self):
        line = self.peek().line
        self.expect("let")
        name = self.expect("IDENT").value
        self.expect("=")
        expr = self.parse_expr()
        self.expect(";")
        return A.LetStmt(name, expr, line)

    def parse_if(self):
        line = self.peek().line
        self.expect("if")
        self.expect("(")
        cond = self.parse_expr()
        self.expect(")")
        then_block = self.parse_block()
        else_block = None
        if self.at("else"):
            self.advance()
            if self.at("if"):
                # else-if chains: wrap the nested if in a synthetic block
                nested = self.parse_if()
                else_block = A.Block([nested], nested.line)
            else:
                else_block = self.parse_block()
        return A.IfStmt(cond, then_block, else_block, line)

    def parse_while(self):
        line = self.peek().line
        self.expect("while")
        self.expect("(")
        cond = self.parse_expr()
        self.expect(")")
        body = self.parse_block()
        return A.WhileStmt(cond, body, line)

    def parse_return(self):
        line = self.peek().line
        self.expect("return")
        expr = self.parse_expr()
        self.expect(";")
        return A.ReturnStmt(expr, line)

    def parse_assign_or_expr_stmt(self):
        line = self.peek().line
        expr = self.parse_expr()
        if self.at("="):
            if not isinstance(expr, (A.Ident, A.Index)):
                raise ParseError("left-hand side of assignment must be a variable or array element", line, 0)
            self.advance()
            rhs = self.parse_expr()
            self.expect(";")
            return A.AssignStmt(expr, rhs, line)
        self.expect(";")
        return A.ExprStmt(expr, line)

    # --- expressions (precedence climbing) --------------------------------

    def parse_expr(self):
        return self.parse_or()

    def parse_or(self):
        left = self.parse_and()
        while self.at("||"):
            line = self.advance().line
            right = self.parse_and()
            left = A.BinOp("||", left, right, line)
        return left

    def parse_and(self):
        left = self.parse_eq()
        while self.at("&&"):
            line = self.advance().line
            right = self.parse_eq()
            left = A.BinOp("&&", left, right, line)
        return left

    def parse_eq(self):
        left = self.parse_rel()
        while self.peek().kind in ("==", "!="):
            op = self.advance()
            right = self.parse_rel()
            left = A.BinOp(op.kind, left, right, op.line)
        return left

    def parse_rel(self):
        left = self.parse_add()
        while self.peek().kind in ("<", "<=", ">", ">="):
            op = self.advance()
            right = self.parse_add()
            left = A.BinOp(op.kind, left, right, op.line)
        return left

    def parse_add(self):
        left = self.parse_mul()
        while self.peek().kind in ("+", "-"):
            op = self.advance()
            right = self.parse_mul()
            left = A.BinOp(op.kind, left, right, op.line)
        return left

    def parse_mul(self):
        left = self.parse_unary()
        while self.peek().kind in ("*", "/", "%"):
            op = self.advance()
            right = self.parse_unary()
            left = A.BinOp(op.kind, left, right, op.line)
        return left

    def parse_unary(self):
        if self.peek().kind in ("-", "!"):
            op = self.advance()
            operand = self.parse_unary()
            return A.UnaryOp(op.kind, operand, op.line)
        return self.parse_postfix()

    def parse_postfix(self):
        expr = self.parse_primary()
        if self.at("[") and isinstance(expr, A.Ident):
            line = self.advance().line
            idx = self.parse_expr()
            self.expect("]")
            expr = A.Index(expr.name, idx, line)
        return expr

    def parse_primary(self):
        t = self.peek()
        if t.kind == "INT":
            self.advance()
            return A.IntLit(t.value, t.line)
        if t.kind == "IDENT":
            self.advance()
            if self.at("("):
                self.advance()
                args = []
                if not self.at(")"):
                    args.append(self.parse_expr())
                    while self.at(","):
                        self.advance()
                        args.append(self.parse_expr())
                self.expect(")")
                return A.Call(t.value, args, t.line)
            return A.Ident(t.value, t.line)
        if t.kind == "(":
            self.advance()
            expr = self.parse_expr()
            self.expect(")")
            return expr
        if t.kind == "-":
            # handled in parse_unary, but keep primary robust just in case
            self.advance()
            operand = self.parse_unary()
            return A.UnaryOp("-", operand, t.line)
        raise ParseError(f"unexpected token {t.kind!r} in expression", t.line, t.col)


def parse(tokens):
    return Parser(tokens).parse_program()
