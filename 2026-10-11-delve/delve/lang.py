"""DelveLang front end: lexer + parser -> AST.

Statements (tuples; last element is always the source line):
  ('let',   name, expr, line)            declare/assign a variable
  ('input', name, src, lo, hi, line)     name = input([lo, hi])   (src = source name used to label inputs)
  ('if',    cond, then[], else[], line)
  ('while', cond, body[], line, wid)
  ('assert',expr, line) ('assume', expr, line) ('print', expr, line) ('return', expr, line)
  ('call',  dest|None, fname, [exprs], line)
Expressions:
  ('num',v) ('var',name) ('un',op,e) ('bin',op,a,b) ('and',a,b) ('or',a,b) ('cond',c,a,b)
Calls inside expressions are hoisted into preceding ('call') statements.
"""
import re


class DelveError(Exception):
    def __init__(self, msg, line=None):
        super().__init__(msg if line is None else "line %d: %s" % (line, msg))
        self.line = line


TOKEN = re.compile(r"""\s+|//[^\n]*|/\*.*?\*/|(?P<num>0[xX][0-9a-fA-F_]+|0[bB][01_]+|\d[\d_]*)|(?P<id>[A-Za-z_]\w*)|(?P<op>>>>|<<|>>|<=|>=|==|!=|&&|\|\||[-+*/%&|^~!<>=(){};,?:])""", re.S)
KEYWORDS = {"let", "if", "else", "while", "assert", "assume", "print", "return", "fn", "input", "true", "false"}


def lex(src):
    toks, pos, line = [], 0, 1
    while pos < len(src):
        m = TOKEN.match(src, pos)
        if not m:
            raise DelveError("unexpected character %r" % src[pos], line)
        text = m.group(0)
        if m.group("num"):
            toks.append(("num", int(m.group("num").replace("_", ""), 0), line))
        elif m.group("id"):
            t = m.group("id")
            toks.append(("kw" if t in KEYWORDS else "id", t, line))
        elif m.group("op"):
            toks.append(("op", text, line))
        line += text.count("\n")
        pos = m.end()
    toks.append(("eof", None, line))
    return toks


BINPREC = [["||"], ["&&"], ["|"], ["^"], ["&"], ["==", "!="], ["<", "<=", ">", ">="], ["<<", ">>", ">>>"], ["+", "-"], ["*", "/", "%"]]


class Program:
    def __init__(self, funcs, main, source):
        self.funcs, self.main, self.source = funcs, main, source
        self.while_count = 0


class Parser:
    def __init__(self, src):
        self.src = src
        self.toks = lex(src)
        self.i = 0
        self.tmp = 0
        self.wid = 0
        self.uniq = 0
        self.funcs = {}
        self.scopes = []
        self.pending = []        # hoisted call statements for the current statement
        self.no_calls = None

    # token helpers
    def peek(self): return self.toks[self.i]

    def next(self):
        t = self.toks[self.i]
        self.i += 1
        return t

    def is_op(self, v): t = self.peek(); return t[0] == "op" and t[1] == v
    def is_kw(self, v): t = self.peek(); return t[0] == "kw" and t[1] == v

    def expect_op(self, v):
        t = self.next()
        if t[0] != "op" or t[1] != v:
            raise DelveError("expected %r but found %r" % (v, t[1] if t[0] != "eof" else "end of file"), t[2])
        return t

    def expect_id(self):
        t = self.next()
        if t[0] != "id":
            raise DelveError("expected an identifier but found %r" % (t[1],), t[2])
        return t

    # scopes
    def declare(self, name):
        self.uniq += 1
        taken = any(name in s for s in self.scopes)
        u = name if (not taken and not self.scopes[-1].get(name)) else "%s$%d" % (name, self.uniq)
        if name in self.scopes[-1]:
            return self.scopes[-1][name]       # re-let in same scope = reassignment
        self.scopes[-1][name] = u
        return u

    def lookup(self, name, line):
        for s in reversed(self.scopes):
            if name in s: return s[name]
        raise DelveError("undefined variable %r" % name, line)

    # program
    def parse(self):
        main = []
        self.scopes = [{}]
        while self.peek()[0] != "eof":
            if self.is_kw("fn"):
                self.parse_fn()
            else:
                main.extend(self.statement())
        p = Program(self.funcs, main, self.src)
        p.while_count = self.wid
        self.check_calls(p)
        return p

    def check_calls(self, p):
        def walk(stmts):
            for s in stmts:
                if s[0] == "call":
                    if s[2] not in p.funcs:
                        raise DelveError("call to undefined function %r" % s[2], s[-1])
                    if len(s[3]) != len(p.funcs[s[2]][0]):
                        raise DelveError("%s expects %d argument(s), got %d" % (s[2], len(p.funcs[s[2]][0]), len(s[3])), s[-1])
                elif s[0] == "if": walk(s[2]); walk(s[3])
                elif s[0] == "while": walk(s[2])
        walk(p.main)
        for params, body, _ in p.funcs.values(): walk(body)

    def parse_fn(self):
        line = self.next()[2]
        name = self.expect_id()[1]
        if name in self.funcs: raise DelveError("function %r defined twice" % name, line)
        self.expect_op("(")
        params = []
        saved, self.scopes = self.scopes, [{}]
        while not self.is_op(")"):
            pname = self.expect_id()[1]
            params.append(self.declare(pname))
            if not self.is_op(")"): self.expect_op(",")
        self.expect_op(")")
        self.funcs[name] = (params, [], line)     # allow recursion
        body = self.block()
        self.funcs[name] = (params, body, line)
        self.scopes = saved

    def block(self):
        self.expect_op("{")
        self.scopes.append({})
        out = []
        while not self.is_op("}"):
            if self.peek()[0] == "eof": raise DelveError("unclosed block", self.peek()[2])
            out.extend(self.statement())
        self.next()
        self.scopes.pop()
        return out

    def statement(self):
        t = self.peek()
        line = t[2]
        self.pending = []
        if t[0] == "kw":
            k = t[1]
            if k == "let":
                self.next()
                name = self.expect_id()[1]
                self.expect_op("=")
                return self.assignment(name, line, declare=True)
            if k == "if": return self.parse_if()
            if k == "while": return self.parse_while()
            if k in ("assert", "assume", "print"):
                self.next(); self.expect_op("(")
                e = self.expr(); self.expect_op(")"); self.expect_op(";")
                return self.pending + [(k, e, line)]
            if k == "return":
                self.next()
                e = ("num", 0) if self.is_op(";") else self.expr()
                self.expect_op(";")
                return self.pending + [("return", e, line)]
            raise DelveError("unexpected keyword %r" % k, line)
        if t[0] == "id":
            self.next()
            if self.is_op("="):
                self.next()
                return self.assignment(t[1], line, declare=False)
            if self.is_op("("):          # call statement
                self.i -= 1
                self.expr()
                self.expect_op(";")
                return self.pending
        if t[0] == "op" and t[1] == "{":
            return self.block()
        raise DelveError("unexpected %r" % (t[1],), line)

    def assignment(self, name, line, declare):
        if self.is_kw("input"):
            self.next(); self.expect_op("(")
            lo = hi = None
            if not self.is_op(")"):
                lo = self.expr(); self.expect_op(","); hi = self.expr()
            self.expect_op(")"); self.expect_op(";")
            if self.pending: raise DelveError("input bounds cannot contain calls", line)
            u = self.declare(name) if declare else self.lookup(name, line)
            return [("input", u, name, lo, hi, line)]
        e = self.expr()
        self.expect_op(";")
        u = self.declare(name) if declare else self.lookup(name, line)
        # a self-referential `let x = x + 1` reads the *outer* x: resolved before declare in expr()
        return self.pending + [("let", u, e, line)]

    def cond_expr(self):
        self.expect_op("(")
        e = self.expr()
        self.expect_op(")")
        return e

    def parse_if(self):
        line = self.next()[2]
        c = self.cond_expr()
        pre = self.pending
        then = self.block()
        els = []
        if self.is_kw("else"):
            self.next()
            els = self.parse_if() if self.is_kw("if") else self.block()
        return pre + [("if", c, then, els, line)]

    def parse_while(self):
        line = self.next()[2]
        self.no_calls = "while conditions"
        c = self.cond_expr()
        self.no_calls = None
        self.wid += 1
        wid = self.wid
        return [("while", c, self.block(), line, wid)]

    # expressions
    def expr(self):
        c = self.binary(0)
        if self.is_op("?"):
            self.next()
            a = self.expr(); self.expect_op(":"); b = self.expr()
            return ("cond", c, a, b)
        return c

    def binary(self, lvl):
        if lvl == len(BINPREC): return self.unary()
        left = self.binary(lvl + 1)
        while self.peek()[0] == "op" and self.peek()[1] in BINPREC[lvl]:
            op = self.next()[1]
            if op in ("&&", "||"):
                saved = self.no_calls
                self.no_calls = saved or "the right side of && / ||"
                right = self.binary(lvl + 1)
                self.no_calls = saved
                left = ("and" if op == "&&" else "or", left, right)
            else:
                left = ("bin", op, left, self.binary(lvl + 1))
        return left

    def unary(self):
        t = self.peek()
        if t[0] == "op" and t[1] in ("-", "~", "!"):
            self.next()
            e = self.unary()
            if t[1] == "-" and e[0] == "num": return ("num", -e[1])
            return ("un", t[1], e)
        return self.primary()

    def primary(self):
        t = self.next()
        if t[0] == "num": return ("num", t[1])
        if t[0] == "kw" and t[1] in ("true", "false"): return ("num", 1 if t[1] == "true" else 0)
        if t[0] == "op" and t[1] == "(":
            e = self.expr(); self.expect_op(")"); return e
        if t[0] == "kw" and t[1] == "input":
            raise DelveError("input() is only allowed as the whole right-hand side of `let x = input();`", t[2])
        if t[0] == "id":
            if self.is_op("("):
                if self.no_calls:
                    raise DelveError("function calls are not allowed in %s" % self.no_calls, t[2])
                self.next()
                args = []
                while not self.is_op(")"):
                    args.append(self.expr())
                    if not self.is_op(")"): self.expect_op(",")
                self.next()
                self.tmp += 1
                tmpname = "$t%d" % self.tmp
                self.pending.append(("call", tmpname, t[1], args, t[2]))
                return ("var", tmpname)
            return ("var", self.lookup(t[1], t[2]))
        raise DelveError("unexpected %r in expression" % (t[1] if t[0] != "eof" else "end of file",), t[2])


def parse(src):
    return Parser(src).parse()
