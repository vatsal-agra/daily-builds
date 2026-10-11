"""Bit-blaster: lowers terms.T formulas to CNF over the incremental CDCL solver,
and exposes a small SMT-style interface (`Smt.check`) with assumptions + caching."""
from . import terms as tm
from .sat import Solver


class Blaster:
    def __init__(self):
        self.sat = Solver()
        t = self.sat.new_var()
        self.sat.add_clause([t])
        self.T, self.F = t, -t
        self.cache = {}       # term id -> list of literals (LSB first)
        self.gates = {}
        self.divs = {}

    # ----------------------------------------------------------- gates
    def AND(self, a, b):
        if a == self.F or b == self.F or a == -b: return self.F
        if a == self.T: return b
        if b == self.T: return a
        if a == b: return a
        key = ("a",) + ((a, b) if a < b else (b, a))
        o = self.gates.get(key)
        if o is None:
            o = self.sat.new_var()
            self.sat.add_clause([-o, a]); self.sat.add_clause([-o, b]); self.sat.add_clause([o, -a, -b])
            self.gates[key] = o
        return o

    def OR(self, a, b):
        return -self.AND(-a, -b)

    def XOR(self, a, b):
        if a == self.F: return b
        if b == self.F: return a
        if a == self.T: return -b
        if b == self.T: return -a
        if a == b: return self.F
        if a == -b: return self.T
        key = ("x",) + ((a, b) if a < b else (b, a))
        o = self.gates.get(key)
        if o is None:
            o = self.sat.new_var()
            s = self.sat.add_clause
            s([-o, a, b]); s([-o, -a, -b]); s([o, -a, b]); s([o, a, -b])
            self.gates[key] = o
        return o

    def MUX(self, s, a, b):
        if s == self.T: return a
        if s == self.F: return b
        if a == b: return a
        if a == self.T: return self.OR(s, b)
        if a == self.F: return self.AND(-s, b)
        if b == self.T: return self.OR(-s, a)
        if b == self.F: return self.AND(s, a)
        key = ("m", s, a, b)
        o = self.gates.get(key)
        if o is None:
            o = self.sat.new_var()
            c = self.sat.add_clause
            c([-s, -a, o]); c([-s, a, -o]); c([s, -b, o]); c([s, b, -o])
            self.gates[key] = o
        return o

    def ANDN(self, xs):
        r = self.T
        for x in xs: r = self.AND(r, x)
        return r

    def ORN(self, xs):
        r = self.F
        for x in xs: r = self.OR(r, x)
        return r

    # ------------------------------------------------------ arithmetic
    def const_bits(self, v, w):
        return [self.T if (v >> i) & 1 else self.F for i in range(w)]

    def add_bits(self, a, b, cin=None):
        c = self.F if cin is None else cin
        out = []
        for x, y in zip(a, b):
            xy = self.XOR(x, y)
            out.append(self.XOR(xy, c))
            c = self.OR(self.AND(x, y), self.AND(c, xy))
        return out, c

    def neg_bits(self, a):
        return self.add_bits([-x for x in a], self.const_bits(0, len(a)), self.T)[0]

    def mul_bits(self, a, b, w):
        acc = self.const_bits(0, w)
        for i, bi in enumerate(b[:w]):
            if bi == self.F: continue
            row = [self.F] * i + [self.AND(x, bi) for x in a[: w - i]]
            row += [self.F] * (w - len(row))
            acc = self.add_bits(acc, row)[0]
        return acc

    def ult_bits(self, a, b):
        # a < b  iff borrow out of a - b
        lt = self.F
        for x, y in zip(a, b):   # LSB to MSB
            lt = self.MUX(self.XOR(x, y), y, lt)
        return lt

    def eq_bits(self, a, b):
        return self.ANDN([-self.XOR(x, y) for x, y in zip(a, b)])

    def mux_bits(self, s, a, b):
        return [self.MUX(s, x, y) for x, y in zip(a, b)]

    def udivrem(self, n, d):
        key = (tuple(n), tuple(d))
        hit = self.divs.get(key)
        if hit: return hit
        w = len(n)
        dz = self.eq_bits(d, self.const_bits(0, w))
        if all(x in (self.T, self.F) for x in n + d) and dz != self.T:
            pass
        q = [self.sat.new_var() for _ in range(w)]
        r = [self.sat.new_var() for _ in range(w)]
        prod = self.mul_bits(q + [self.F] * w, d + [self.F] * w, 2 * w)
        tot, carry = self.add_bits(prod, r + [self.F] * w)
        good = self.AND(self.eq_bits(tot, n + [self.F] * w), self.AND(-carry, self.ult_bits(r, d)))
        self.sat.add_clause([dz, good])
        ones = [self.T] * w
        res = (self.mux_bits(dz, ones, q), self.mux_bits(dz, n, r))
        self.divs[key] = res
        return res

    def abs_bits(self, a):
        s = a[-1]
        return self.mux_bits(s, self.neg_bits(a), a)

    def cond_neg(self, s, a):
        return self.mux_bits(s, self.neg_bits(a), a)

    def shift(self, op, a, b):
        w = len(a)
        fill = a[-1] if op == "ashr" else self.F
        cur = list(a)
        stages = max(1, (w - 1).bit_length())
        for i in range(min(stages, len(b))):
            k = 1 << i
            if op == "shl":
                sh = [self.F] * min(k, w) + cur[: max(0, w - k)]
            else:
                sh = cur[k:] + [fill] * min(k, w)
            cur = self.mux_bits(b[i], sh, cur)
        big = self.NOT_ULT(b, w)
        return self.mux_bits(big, [fill] * w, cur)

    def NOT_ULT(self, b, w):
        """b >= w (unsigned), b given as bits."""
        bw = len(b)
        if w >= (1 << bw): return self.F
        return -self.ult_bits(b, self.const_bits(w, bw))

    # ----------------------------------------------------------- blast
    def blast(self, root):
        for t in tm.children_postorder(root):
            if t.id in self.cache: continue
            self.cache[t.id] = self._blast1(t)
        return self.cache[root.id]

    def lit(self, t):
        assert t.w == tm.BOOL
        return self.blast(t)[0]

    def _blast1(self, t):
        op, A = t.op, [self.cache[a.id] for a in t.args]
        w = t.w
        if op == "const":
            return [self.T if t.val else self.F] if w == tm.BOOL else self.const_bits(t.val, w)
        if op == "var":
            return [self.sat.new_var() for _ in range(max(w, 1))]
        if op == "add": return self.add_bits(A[0], A[1])[0]
        if op == "sub": return self.add_bits(A[0], [-x for x in A[1]], self.T)[0]
        if op == "neg": return self.neg_bits(A[0])
        if op == "mul": return self.mul_bits(A[0], A[1], w)
        if op == "bnot": return [-x for x in A[0]]
        if op == "and": return [self.AND(x, y) for x, y in zip(*A)]
        if op == "or": return [self.OR(x, y) for x, y in zip(*A)]
        if op == "xor": return [self.XOR(x, y) for x, y in zip(*A)]
        if op == "udiv": return self.udivrem(A[0], A[1])[0]
        if op == "urem": return self.udivrem(A[0], A[1])[1]
        if op in ("sdiv", "srem"):
            n, d = A
            q, r = self.udivrem(self.abs_bits(n), self.abs_bits(d))
            if op == "sdiv": return self.cond_neg(self.XOR(n[-1], d[-1]), q)
            return self.cond_neg(n[-1], r)
        if op in ("shl", "lshr", "ashr"): return self.shift(op, A[0], A[1])
        if op == "eq": return [self.eq_bits(A[0], A[1]) if t.args[0].w else -self.XOR(A[0][0], A[1][0])]
        if op == "ult": return [self.ult_bits(A[0], A[1])]
        if op == "ule": return [-self.ult_bits(A[1], A[0])]
        if op in ("slt", "sle"):
            a, b = list(A[0]), list(A[1])
            a[-1], b[-1] = -a[-1], -b[-1]     # flip sign bits => unsigned order
            return [self.ult_bits(a, b)] if op == "slt" else [-self.ult_bits(b, a)]
        if op == "band": return [self.AND(A[0][0], A[1][0])]
        if op == "bor": return [self.OR(A[0][0], A[1][0])]
        if op == "not": return [-A[0][0]]
        if op == "ite":
            if w == tm.BOOL: return [self.MUX(A[0][0], A[1][0], A[2][0])]
            return self.mux_bits(A[0][0], A[1], A[2])
        if op == "zext": return A[0] + [self.F] * (w - len(A[0]))
        if op == "sext": return A[0] + [A[0][-1]] * (w - len(A[0]))
        if op == "trunc": return A[0][:w]
        raise ValueError("cannot blast " + op)

    def value(self, t):
        """Value of an already-blasted term in the last SAT model."""
        bits = self.cache[t.id]
        v = 0
        for i, l in enumerate(bits):
            if self.sat.lit_model(l): v |= 1 << i
        return v


class Unknown(Exception):
    """The SAT solver exhausted its conflict budget before deciding a query."""


class Smt:
    """Satisfiability queries over lists of boolean terms (conjunctions)."""

    def __init__(self, budget=100000):
        self.budget = budget
        self.b = Blaster()
        self.cache = {}
        self.vars = {}
        self.stats = {"queries": 0, "cache_hits": 0, "trivial": 0, "sat_calls": 0}

    def check(self, conds, want_model=True):
        """Return (True, model{name:int}) / (False, None). Conjunction of conds."""
        self.stats["queries"] += 1
        conds = [c for c in conds if c is not tm.TRUE]
        if any(c is tm.FALSE for c in conds):
            self.stats["trivial"] += 1
            return False, None
        if not conds:
            self.stats["trivial"] += 1
            return True, {}
        key = frozenset(c.id for c in conds)
        hit = self.cache.get(key)
        if hit is not None and (hit[0] is False or not want_model or hit[1] is not None):
            self.stats["cache_hits"] += 1
            return hit
        lits = []
        for c in conds:
            lits.append(self.b.lit(c))
            for n, w in tm.variables(c).items(): self.vars[n] = self.b_var(n, w)
        self.stats["sat_calls"] += 1
        sat = self.solve(lits)
        if not sat:
            self.cache[key] = (False, None)
            return False, None
        model = {n: self.b.value(v) for n, v in self.vars.items()}
        # inputs that only appear in other queries default to 0 (validated by caller)
        self.cache[key] = (True, model)
        return True, model

    def solve(self, lits):
        r = self.b.sat.solve(lits, conflict_budget=self.budget)
        if r is None:
            raise Unknown()
        return r

    def b_var(self, name, w):
        return tm.var(name, w)

    def valid(self, cond):
        """cond holds for all assignments?"""
        return not self.check([tm.lnot(cond)], want_model=False)[0]


def _minimize(self, conds, names):
    """Return a model of `conds` whose listed input variables are as close to zero as
    possible (non-negative preferred, then smallest bit pattern), chosen greedily bit by bit."""
    conds = [c for c in conds if c is not tm.TRUE]
    if any(c is tm.FALSE for c in conds): return None
    b = self.b
    base = [b.lit(c) for c in conds]
    present = {}
    for c in conds: present.update(tm.variables(c))
    for n, w in present.items(): self.vars[n] = tm.var(n, w)
    fixed = []
    for name in names:
        if name not in present: continue
        v = self.vars[name]
        bits = b.cache[v.id]
        w = len(bits)
        if not self.solve(base + fixed): return None
        order = []
        if w > 1:
            neg = not self.solve(base + fixed + [-bits[-1]])
            fixed.append(bits[-1] if neg else -bits[-1])
            want = (lambda l: l) if neg else (lambda l: -l)       # negative: prefer 1s; else prefer 0s
            order = range(w - 2, -1, -1)
        else:
            want, order = (lambda l: -l), range(0, -1, -1)
            order = [0]
        for i in order:
            trial = want(bits[i])
            fixed.append(trial if self.solve(base + fixed + [trial]) else -trial)
    self.stats["sat_calls"] += 1
    if not self.solve(base + fixed): return None
    return {n: b.value(self.vars[n]) for n in present}


Smt.minimize = _minimize
