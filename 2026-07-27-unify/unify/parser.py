"""Recursive-descent parser: tokens -> AST.

Grammar (low to high precedence):

    expr    := "let" ["rec"] IDENT IDENT* "=" expr "in" expr
             | "if" expr "then" expr "else" expr
             | "fun" IDENT+ "->" expr
             | "match" expr "with" ["|"] pattern "->" expr ("|" pattern "->" expr)*
             | or
    or      := and ("||" and)*
    and     := cmp ("&&" cmp)*
    cmp     := cons (("=" | "<>" | "<" | ">" | "<=" | ">=") cons)*
    cons    := add ("::" cons)?                    -- right associative
    add     := mul (("+" | "-") mul)*
    mul     := unary (("*" | "/") unary)*
    unary   := "-" unary | app
    app     := atom atom*                            -- left-assoc application
    atom    := INT | STRING | "true" | "false" | "None"
             | "Some" atom
             | IDENT
             | "(" expr ("," expr)* ")"
             | "[" [expr ("," expr)*] "]"

    pattern      := pcons
    pcons        := patom ("::" pcons)?
    patom        := "_" | IDENT | INT | "true" | "false" | "None"
                  | "Some" patom
                  | "[" [pattern ("," pattern)*] "]"
                  | "(" pattern ("," pattern)* ")"
"""

from . import nodes as N
from .lexer import tokenize, LexError


class ParseError(Exception):
    def __init__(self, message, line, col):
        super().__init__(message)
        self.message = message
        self.line = line
        self.col = col


class Parser:
    def __init__(self, tokens, source):
        self.toks = tokens
        self.source = source
        self.i = 0

    def peek(self):
        return self.toks[self.i]

    def advance(self):
        tok = self.toks[self.i]
        self.i += 1
        return tok

    def at_keyword(self, kw):
        t = self.peek()
        return t.kind == "KEYWORD" and t.text == kw

    def at_symbol(self, sym):
        t = self.peek()
        return t.kind == "SYMBOL" and t.text == sym

    def expect_symbol(self, sym):
        if not self.at_symbol(sym):
            t = self.peek()
            raise ParseError(f"expected {sym!r}, found {t.text or t.kind!r}", t.line, t.col)
        return self.advance()

    def expect_keyword(self, kw):
        if not self.at_keyword(kw):
            t = self.peek()
            raise ParseError(f"expected {kw!r}, found {t.text or t.kind!r}", t.line, t.col)
        return self.advance()

    def expect_ident(self):
        t = self.peek()
        if t.kind != "IDENT":
            raise ParseError(f"expected identifier, found {t.text or t.kind!r}", t.line, t.col)
        return self.advance()

    # ---- expressions ----------------------------------------------------

    def parse_program(self):
        e = self.parse_expr()
        t = self.peek()
        if t.kind != "EOF":
            raise ParseError(f"unexpected trailing input {t.text or t.kind!r}", t.line, t.col)
        return e

    def parse_expr(self):
        if self.at_keyword("let"):
            return self.parse_let()
        if self.at_keyword("if"):
            return self.parse_if()
        if self.at_keyword("fun"):
            return self.parse_fun()
        if self.at_keyword("match"):
            return self.parse_match()
        return self.parse_or()

    def parse_let(self):
        start = self.advance().pos  # 'let'
        is_rec = False
        if self.at_keyword("rec"):
            self.advance()
            is_rec = True
        name_tok = self.expect_ident()
        params = []
        while self.peek().kind == "IDENT":
            params.append(self.advance().text)
        self.expect_symbol("=")
        value = self.parse_expr()
        for p in reversed(params):
            value = N.Fun(span=value.span, param=p, body=value)
        if is_rec and not isinstance(value, N.Fun):
            raise ParseError(
                "'let rec' right-hand side must be a function "
                "(write 'let rec f x = ...' or 'let rec f = fun x -> ...')",
                name_tok.line, name_tok.col,
            )
        self.expect_keyword("in")
        body = self.parse_expr()
        span = (start, body.span[1])
        cls = N.LetRec if is_rec else N.Let
        return cls(span=span, name=name_tok.text, value=value, body=body)

    def parse_if(self):
        start = self.advance().pos
        cond = self.parse_expr()
        self.expect_keyword("then")
        then_b = self.parse_expr()
        self.expect_keyword("else")
        else_b = self.parse_expr()
        return N.If(span=(start, else_b.span[1]), cond=cond, then_branch=then_b, else_branch=else_b)

    def parse_fun(self):
        start = self.advance().pos
        params = []
        while self.peek().kind == "IDENT":
            params.append(self.advance().text)
        if not params:
            t = self.peek()
            raise ParseError("expected at least one parameter after 'fun'", t.line, t.col)
        self.expect_symbol("->")
        body = self.parse_expr()
        end = body.span[1]
        for p in reversed(params):
            body = N.Fun(span=(start, end), param=p, body=body)
        return body

    def parse_match(self):
        start = self.advance().pos
        scrutinee = self.parse_expr()
        self.expect_keyword("with")
        if self.at_symbol("|"):
            self.advance()
        cases = []
        while True:
            pat = self.parse_pattern()
            self.expect_symbol("->")
            body = self.parse_expr()
            cases.append((pat, body))
            if self.at_symbol("|"):
                self.advance()
                continue
            break
        if not cases:
            t = self.peek()
            raise ParseError("match must have at least one case", t.line, t.col)
        end = cases[-1][1].span[1]
        return N.Match(span=(start, end), scrutinee=scrutinee, cases=cases)

    def _binop_chain(self, next_level, ops):
        left = next_level()
        while True:
            t = self.peek()
            if t.kind == "SYMBOL" and t.text in ops:
                op = self.advance().text
                right = next_level()
                left = N.BinOp(span=(left.span[0], right.span[1]), op=op, left=left, right=right)
            else:
                return left

    def parse_or(self):
        return self._binop_chain(self.parse_and, {"||"})

    def parse_and(self):
        return self._binop_chain(self.parse_cmp, {"&&"})

    def parse_cmp(self):
        return self._binop_chain(self.parse_cons, {"=", "<>", "<", ">", "<=", ">="})

    def parse_cons(self):
        left = self.parse_add()
        if self.at_symbol("::"):
            self.advance()
            right = self.parse_cons()  # right-associative
            return N.Cons(span=(left.span[0], right.span[1]), head=left, tail=right)
        return left

    def parse_add(self):
        return self._binop_chain(self.parse_mul, {"+", "-"})

    def parse_mul(self):
        return self._binop_chain(self.parse_unary, {"*", "/"})

    def parse_unary(self):
        if self.at_symbol("-"):
            start = self.advance().pos
            e = self.parse_unary()
            return N.UnaryNeg(span=(start, e.span[1]), expr=e)
        return self.parse_app()

    ATOM_STARTERS_SYMBOLS = {"(", "["}

    def _starts_atom(self):
        t = self.peek()
        if t.kind in ("INT", "STRING", "IDENT"):
            return True
        if t.kind == "KEYWORD" and t.text in ("true", "false", "None", "Some"):
            return True
        if t.kind == "SYMBOL" and t.text in self.ATOM_STARTERS_SYMBOLS:
            return True
        return False

    def parse_app(self):
        fn = self.parse_atom()
        while self._starts_atom():
            arg = self.parse_atom()
            fn = N.App(span=(fn.span[0], arg.span[1]), fn=fn, arg=arg)
        return fn

    def parse_atom(self):
        t = self.peek()

        if t.kind == "INT":
            self.advance()
            return N.Int(span=(t.pos, t.pos + len(t.text)), value=t.value)

        if t.kind == "STRING":
            self.advance()
            return N.Str(span=(t.pos, t.pos + len(t.text)), value=t.value)

        if t.kind == "IDENT":
            self.advance()
            return N.Var(span=(t.pos, t.pos + len(t.text)), name=t.text)

        if t.kind == "KEYWORD" and t.text == "true":
            self.advance()
            return N.Bool(span=(t.pos, t.pos + len(t.text)), value=True)

        if t.kind == "KEYWORD" and t.text == "false":
            self.advance()
            return N.Bool(span=(t.pos, t.pos + len(t.text)), value=False)

        if t.kind == "KEYWORD" and t.text == "None":
            self.advance()
            return N.NoneExpr(span=(t.pos, t.pos + len(t.text)))

        if t.kind == "KEYWORD" and t.text == "Some":
            self.advance()
            arg = self.parse_atom()
            return N.SomeExpr(span=(t.pos, arg.span[1]), value=arg)

        if t.kind == "SYMBOL" and t.text == "(":
            self.advance()
            items = [self.parse_expr()]
            while self.at_symbol(","):
                self.advance()
                items.append(self.parse_expr())
            close = self.expect_symbol(")")
            span = (t.pos, close.pos + 1)
            if len(items) == 1:
                return _reparent(items[0], span)
            return N.TupleExpr(span=span, items=items)

        if t.kind == "SYMBOL" and t.text == "[":
            self.advance()
            items = []
            if not self.at_symbol("]"):
                items.append(self.parse_expr())
                while self.at_symbol(","):
                    self.advance()
                    items.append(self.parse_expr())
            close = self.expect_symbol("]")
            span = (t.pos, close.pos + 1)
            node = N.Nil(span=span)
            for item in reversed(items):
                node = N.Cons(span=span, head=item, tail=node)
            return node

        raise ParseError(f"unexpected token {t.text or t.kind!r}", t.line, t.col)

    # ---- patterns ---------------------------------------------------------

    def parse_pattern(self):
        return self.parse_pattern_cons()

    def parse_pattern_cons(self):
        left = self.parse_pattern_atom()
        if self.at_symbol("::"):
            self.advance()
            right = self.parse_pattern_cons()
            return N.PCons(span=(left.span[0], right.span[1]), head=left, tail=right)
        return left

    def parse_pattern_atom(self):
        t = self.peek()

        if t.kind == "SYMBOL" and t.text == "_":
            self.advance()
            return N.PWild(span=(t.pos, t.pos + 1))

        if t.kind == "IDENT":
            self.advance()
            return N.PVar(span=(t.pos, t.pos + len(t.text)), name=t.text)

        if t.kind == "INT":
            self.advance()
            return N.PInt(span=(t.pos, t.pos + len(t.text)), value=t.value)

        if t.kind == "KEYWORD" and t.text == "true":
            self.advance()
            return N.PBool(span=(t.pos, t.pos + len(t.text)), value=True)

        if t.kind == "KEYWORD" and t.text == "false":
            self.advance()
            return N.PBool(span=(t.pos, t.pos + len(t.text)), value=False)

        if t.kind == "KEYWORD" and t.text == "None":
            self.advance()
            return N.PNone(span=(t.pos, t.pos + len(t.text)))

        if t.kind == "KEYWORD" and t.text == "Some":
            self.advance()
            inner = self.parse_pattern_atom()
            return N.PSome(span=(t.pos, inner.span[1]), pattern=inner)

        if t.kind == "SYMBOL" and t.text == "[":
            self.advance()
            items = []
            if not self.at_symbol("]"):
                items.append(self.parse_pattern())
                while self.at_symbol(","):
                    self.advance()
                    items.append(self.parse_pattern())
            close = self.expect_symbol("]")
            span = (t.pos, close.pos + 1)
            node = N.PNil(span=span)
            for item in reversed(items):
                node = N.PCons(span=span, head=item, tail=node)
            return node

        if t.kind == "SYMBOL" and t.text == "(":
            self.advance()
            items = [self.parse_pattern()]
            while self.at_symbol(","):
                self.advance()
                items.append(self.parse_pattern())
            close = self.expect_symbol(")")
            span = (t.pos, close.pos + 1)
            if len(items) == 1:
                return items[0]
            return N.PTuple(span=span, items=items)

        raise ParseError(f"unexpected token in pattern: {t.text or t.kind!r}", t.line, t.col)


def _reparent(node, span):
    """Return a copy of `node` with its span widened to include enclosing parens."""
    import dataclasses
    return dataclasses.replace(node, span=span)


def parse(source):
    tokens = tokenize(source)
    return Parser(tokens, source).parse_program()
