"""Concrete W-bit interpreter for DelveLang. It is the ground truth every symbolic
finding is replayed against."""
from . import terms as tm
from .lang import DelveError, check_literals

BINOPS = {"+": "add", "-": "sub", "*": "mul", "/": "sdiv", "%": "srem", "&": "and", "|": "or", "^": "xor",
          "<<": "shl", ">>": "ashr", ">>>": "lshr"}
CMPOPS = {"==": "eq", "<": "slt", "<=": "sle"}      # others derived: != > >=

KINDS = ("assertion failure", "division by zero", "signed overflow", "invalid shift")


class Trap(Exception):
    def __init__(self, kind, line):
        super().__init__("%s at line %d" % (kind, line))
        self.kind, self.line = kind, line


class Infeasible(Exception):
    """assume() failed or input outside its declared range: the run is not a valid execution."""


class Budget(Exception):
    pass


def input_label(counts, src):
    counts[src] = counts.get(src, 0) + 1
    return src if counts[src] == 1 else "%s#%d" % (src, counts[src])


class Result:
    def __init__(self):
        self.value = None
        self.outputs = []
        self.trap = None            # (kind, line) or None
        self.infeasible = False
        self.exhausted = False
        self.steps = 0
        self.lines = set()
        self.branches = set()       # (line, taken)
        self.input_names = []

    def __repr__(self):
        return "Result(value=%r, outputs=%r, trap=%r)" % (self.value, self.outputs, self.trap)


class Interp:
    def __init__(self, prog, width=8, max_steps=200000, max_depth=200):
        check_literals(prog, width)
        self.prog, self.w = prog, width
        self.m = tm.mask(width)
        self.max_steps, self.max_depth = max_steps, max_depth

    def run(self, inputs=None):
        self.inputs = inputs or {}
        self.counts = {}
        self.res = Result()
        try:
            self.exec_block(self.prog.main, {}, 0)
        except Trap as t:
            self.res.trap = (t.kind, t.line)
        except Infeasible:
            self.res.infeasible = True
        except Budget:
            self.res.exhausted = True
        except _Return as r:
            self.res.value = r.value
        return self.res

    # -- statements
    def exec_block(self, stmts, env, depth):
        for s in stmts:
            self.exec_stmt(s, env, depth)

    def tick(self, line):
        self.res.steps += 1
        self.res.lines.add(line)
        if self.res.steps > self.max_steps: raise Budget()

    def exec_stmt(self, s, env, depth):
        k = s[0]
        line = s[-1] if k != "while" else s[3]
        self.tick(line)
        if k == "let":
            env[s[1]] = self.ev(s[2], env, line)
        elif k == "input":
            label = input_label(self.counts, s[2])
            self.res.input_names.append(label)
            v = self.inputs.get(label, 0) & self.m
            if s[3] is not None:
                lo, hi = self.ev(s[3], env, line), self.ev(s[4], env, line)
                sv = tm.to_signed(v, self.w)
                if not (tm.to_signed(lo, self.w) <= sv <= tm.to_signed(hi, self.w)): raise Infeasible()
            env[s[1]] = v
        elif k == "if":
            c = self.ev(s[1], env, line) != 0
            self.res.branches.add((line, c))
            self.exec_block(s[2] if c else s[3], env, depth)
        elif k == "while":
            while True:
                self.tick(line)
                c = self.ev(s[1], env, line) != 0
                self.res.branches.add((line, c))
                if not c: break
                self.exec_block(s[2], env, depth)
        elif k == "assert":
            if self.ev(s[1], env, line) == 0: raise Trap("assertion failure", line)
        elif k == "assume":
            if self.ev(s[1], env, line) == 0: raise Infeasible()
        elif k == "print":
            self.res.outputs.append(tm.to_signed(self.ev(s[1], env, line), self.w))
        elif k == "return":
            raise _Return(self.ev(s[1], env, line))
        elif k == "call":
            if depth >= self.max_depth: raise Budget()
            params, body, _ = self.prog.funcs[s[2]]
            args = [self.ev(a, env, line) for a in s[3]]
            try:
                self.exec_block(body, dict(zip(params, args)), depth + 1)
                rv = 0
            except _Return as r:
                rv = r.value
            if s[1] is not None: env[s[1]] = rv
        else:
            raise DelveError("bad statement " + k)

    # -- expressions
    def ev(self, e, env, line):
        k, w, m = e[0], self.w, self.m
        if k == "num": return e[1] & m
        if k == "var": return env[e[1]]
        if k == "un":
            a = self.ev(e[2], env, line)
            if e[1] == "-":
                if a == 1 << (w - 1): raise Trap("signed overflow", line)
                return (-a) & m
            if e[1] == "~": return (~a) & m
            return int(a == 0)
        if k == "and":
            return int(self.ev(e[1], env, line) != 0 and self.ev(e[2], env, line) != 0)
        if k == "or":
            return int(self.ev(e[1], env, line) != 0 or self.ev(e[2], env, line) != 0)
        if k == "cond":
            return self.ev(e[2], env, line) if self.ev(e[1], env, line) != 0 else self.ev(e[3], env, line)
        op = e[1]
        a, b = self.ev(e[2], env, line), self.ev(e[3], env, line)
        if op in BINOPS:
            return binop_checked(op, a, b, w, line)
        sa, sb = tm.to_signed(a, w), tm.to_signed(b, w)
        if op == "==": return int(a == b)
        if op == "!=": return int(a != b)
        if op == "<": return int(sa < sb)
        if op == "<=": return int(sa <= sb)
        if op == ">": return int(sa > sb)
        if op == ">=": return int(sa >= sb)
        raise DelveError("bad operator " + op)


class _Return(Exception):
    def __init__(self, value):
        self.value = value


def binop_checked(op, a, b, w, line):
    """Concrete binary op with trap checks (mirrors the symbolic side exactly)."""
    sa, sb = tm.to_signed(a, w), tm.to_signed(b, w)
    lo, hi = -(1 << (w - 1)), (1 << (w - 1)) - 1
    if op in ("+", "-", "*"):
        exact = sa + sb if op == "+" else sa - sb if op == "-" else sa * sb
        if not lo <= exact <= hi: raise Trap("signed overflow", line)
    elif op in ("/", "%"):
        if b == 0: raise Trap("division by zero", line)
        if sa == lo and sb == -1: raise Trap("signed overflow", line)
    elif op in ("<<", ">>", ">>>"):
        if not 0 <= sb < w: raise Trap("invalid shift", line)
    return tm.apply_op(BINOPS[op], [a, b], w)
