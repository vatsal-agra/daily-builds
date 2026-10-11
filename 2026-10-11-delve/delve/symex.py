"""Symbolic executor: explores DelveLang paths over symbolic W-bit inputs, forks on
branches, prunes infeasible paths with the SMT layer, finds traps (assertion failure,
division by zero, signed overflow, invalid shift) with concrete witnesses, and generates
one concrete test per feasible path."""
import time
from . import terms as tm
from .bitblast import Smt, Unknown
from .interp import Interp, input_label, BINOPS
from .lang import DelveError, check_literals


class Dead(Exception):
    """Current path became infeasible."""


class State:
    __slots__ = ("env", "k", "pc", "frames", "inputs", "in_names", "counts", "loops", "outputs",
                 "lines", "branches", "model", "depth", "trace")

    def fork(self):
        s = State.__new__(State)
        s.env = dict(self.env)
        s.k = self.k
        s.pc = list(self.pc)
        s.frames = self.frames
        s.inputs = dict(self.inputs)
        s.in_names = list(self.in_names)
        s.counts = dict(self.counts)
        s.loops = dict(self.loops)
        s.outputs = list(self.outputs)
        s.lines = set(self.lines)
        s.branches = set(self.branches)
        s.model = self.model
        s.depth = self.depth
        s.trace = self.trace
        return s


class PathInfo:
    def __init__(self, pid, status, state, model, ret=None, trap=None):
        self.id, self.status, self.trap = pid, status, trap     # status: return | end | error
        self.pc = list(state.pc)
        self.inputs = {n: model.get(n, 0) for n in state.in_names}
        self.in_names = list(state.in_names)
        self.ret = ret                                          # term or None
        self.outputs = list(state.outputs)
        self.lines = set(state.lines)
        self.branches = set(state.branches)
        self.model = model
        self.verified = None
        self.expected_ret = None
        self.expected_out = None


class Bug:
    def __init__(self, kind, line, inputs, in_names):
        self.kind, self.line, self.inputs, self.in_names = kind, line, inputs, in_names
        self.confirmed = None
        self.hits = 1

    def __repr__(self):
        return "Bug(%s @%d %r)" % (self.kind, self.line, self.inputs)


def push_block(stmts, k):
    for s in reversed(stmts):
        k = (s, k)
    return k


class Explorer:
    def __init__(self, prog, width=8, loop_bound=8, max_paths=2000, max_depth=24, timeout=60.0,
                 check_overflow=True, minimize=True, smt=None, strategy="dfs", solver_budget=100000):
        check_literals(prog, width)
        self.prog, self.w = prog, width
        self.loop_bound, self.max_paths, self.max_depth = loop_bound, max_paths, max_depth
        self.timeout, self.check_overflow, self.minimize = timeout, check_overflow, minimize
        self.smt = smt or Smt(solver_budget)
        self.unknown = 0
        self.strategy = strategy
        self.paths, self.bugs = [], {}
        self.truncated = 0
        self.pruned = 0
        self.hit_limit = None
        self.all_lines = set()
        self.all_branches = set()
        self._index_program()

    # ------------------------------------------------------------ setup
    def _index_program(self):
        def walk(stmts):
            for s in stmts:
                k = s[0]
                line = s[3] if k == "while" else s[-1]
                self.all_lines.add(line)
                if k == "if":
                    self.all_branches |= {(line, True), (line, False)}
                    walk(s[2]); walk(s[3])
                elif k == "while":
                    self.all_branches |= {(line, True), (line, False)}
                    walk(s[2])
        walk(self.prog.main)
        for _, body, _ in self.prog.funcs.values(): walk(body)

    def const(self, v): return tm.const(v, self.w)

    # ---------------------------------------------------------- explore
    def explore(self):
        st = State()
        st.env, st.pc, st.frames, st.inputs, st.in_names = {}, [], None, {}, []
        st.counts, st.loops, st.outputs, st.lines, st.branches = {}, {}, [], set(), set()
        st.model, st.depth, st.trace = {}, 0, ()
        st.k = push_block(self.prog.main, None)
        work = [st]
        t0 = time.time()
        while work:
            if len(self.paths) >= self.max_paths:
                self.hit_limit = "path limit (%d)" % self.max_paths
                break
            if time.time() - t0 > self.timeout:
                self.hit_limit = "time limit (%.0fs)" % self.timeout
                break
            s = work.pop() if self.strategy == "dfs" else work.pop(0)
            try:
                work.extend(self.run(s))
            except Dead:
                self.pruned += 1
            except Unknown:
                self.unknown += 1
        self.stats = dict(self.smt.stats)
        self.stats.update({k: v for k, v in self.smt.b.sat.stats.items() if k in ("conflicts", "decisions")})
        return self

    def run(self, s):
        """Advance one state until it terminates or forks; return list of successor states."""
        while True:
            if s.k is None:
                self.finish(s, "end", None)
                return []
            item, s.k = s.k
            kind = item[0]
            if kind == "$endfn":
                self.do_return(s, self.const(0))
                continue
            line = item[3] if kind == "while" else item[-1]
            s.lines.add(line)
            try:
                if kind == "let":
                    s.env[item[1]] = self.eval(s, item[2], tm.TRUE, line)
                elif kind == "input":
                    self.do_input(s, item, line)
                elif kind == "assert":
                    c = tm.bv2bool(self.eval(s, item[1], tm.TRUE, line))
                    self.require(s, "assertion failure", line, c, tm.TRUE)
                elif kind == "assume":
                    self.constrain(s, tm.bv2bool(self.eval(s, item[1], tm.TRUE, line)))
                elif kind == "print":
                    s.outputs.append(self.eval(s, item[1], tm.TRUE, line))
                elif kind == "return":
                    v = self.eval(s, item[1], tm.TRUE, line)
                    if s.frames is None:
                        self.finish(s, "return", v)
                        return []
                    self.do_return(s, v)
                elif kind == "call":
                    if s.depth >= self.max_depth:
                        self.truncated += 1
                        return []
                    args = [self.eval(s, a, tm.TRUE, line) for a in item[3]]
                    params, body, _ = self.prog.funcs[item[2]]
                    s.frames = (item[1], s.env, s.k, s.frames)
                    s.env = dict(zip(params, args))
                    s.k = push_block(body, (("$endfn",), None))
                    s.depth += 1
                elif kind == "if":
                    return self.do_if(s, item, line)
                elif kind == "while":
                    return self.do_while(s, item, line)
                else:
                    raise DelveError("bad statement " + kind)
            except Dead:
                return []
            except Unknown:
                self.unknown += 1
                return []

    # ----------------------------------------------------- statements
    def do_return(self, s, v):
        dest, env, k, frames = s.frames
        s.env = dict(env)
        if dest is not None: s.env[dest] = v
        s.k, s.frames = k, frames
        s.depth -= 1

    def do_input(self, s, item, line):
        label = input_label(s.counts, item[2])
        v = tm.var(label, self.w)
        s.inputs[label] = v
        s.in_names.append(label)
        s.env[item[1]] = v
        if item[3] is not None:
            lo, hi = self.eval(s, item[3], tm.TRUE, line), self.eval(s, item[4], tm.TRUE, line)
            self.constrain(s, tm.land(tm.sle(lo, v), tm.sle(v, hi)))

    def branch(self, s, c, line):
        """Split on bool term c. Returns (state_if_true | None, state_if_false | None)."""
        if c is tm.TRUE: return s, None
        if c is tm.FALSE: return None, s
        known_true = tm.evaluate(c, s.model) == 1      # side already witnessed by s.model
        other = tm.lnot(c) if known_true else c
        ok, m = self.smt.check(s.pc + [other])
        if not ok:
            return (s, None) if known_true else (None, s)
        t, f = s, s.fork()
        if known_true:
            t.pc.append(c); f.pc.append(other); f.model = m
        else:
            f.pc.append(tm.lnot(c)); t.pc.append(other); t.model = m
        return t, f

    def do_if(self, s, item, line):
        c = tm.bv2bool(self.eval(s, item[1], tm.TRUE, line))
        t, f = self.branch(s, c, line)
        out = []
        for st, taken, blk in ((f, False, item[3]), (t, True, item[2])):     # DFS visits `then` first
            if st is None: continue
            st.branches.add((line, taken))
            st.k = push_block(blk, st.k)
            out.append(st)
        return out

    def do_while(self, s, item, line):
        c = tm.bv2bool(self.eval(s, item[1], tm.TRUE, line))
        t, f = self.branch(s, c, line)
        out = []
        if f is not None:
            f.branches.add((line, False))
            f.loops.pop(item[4], None)
            out.append(f)
        if t is not None:
            n = t.loops.get(item[4], 0)
            if n >= self.loop_bound:
                self.truncated += 1
            else:
                t.loops[item[4]] = n + 1
                t.branches.add((line, True))
                t.k = push_block(item[2], (item, t.k))
                out.append(t)
        return out

    # --------------------------------------------------------- solver glue
    def constrain(self, s, c):
        if c is tm.TRUE: return
        if c is tm.FALSE: raise Dead()
        if tm.evaluate(c, s.model) == 1:
            s.pc.append(c)
            return
        ok, m = self.smt.check(s.pc + [c])
        if not ok: raise Dead()
        s.pc.append(c)
        s.model = m

    def witness(self, s, extra):
        """Concrete inputs satisfying pc + extra (minimized for readability)."""
        conds = s.pc + extra
        m = None
        if self.minimize:
            try:
                m = self.smt.minimize(conds, list(s.in_names))
            except Unknown:
                m = None            # too hard to minimize: fall back to any model
        return m or self.smt.check(conds)[1] or {}

    def require(self, s, kind, line, ok, guard):
        """Check that `ok` holds whenever `guard` does. Records a bug (+ an error-path test)
        if the violation is feasible, then continues only on the non-violating paths."""
        if ok is tm.TRUE: return
        viol = tm.land(guard, tm.lnot(ok))
        sat, _ = self.smt.check(s.pc + [viol])
        if sat:
            m = self.witness(s, [viol])
            inputs = {n: m.get(n, 0) for n in s.in_names}
            key = (kind, line)
            if key in self.bugs:
                self.bugs[key].hits += 1
            else:
                self.bugs[key] = Bug(kind, line, inputs, list(s.in_names))
            if len(self.paths) < self.max_paths:
                err = s.fork()
                err.pc.append(viol)
                p = PathInfo(len(self.paths) + 1, "error", err, m, trap=(kind, line))
                self.paths.append(p)
        self.constrain(s, tm.lor(tm.lnot(guard), ok))

    def finish(self, s, status, ret):
        ok, m = self.smt.check(s.pc)
        if not ok: raise Dead()
        if self.minimize:
            try:
                mm = self.smt.minimize(s.pc, s.in_names)
            except Unknown:
                mm = None
            if mm is not None: m = mm
        p = PathInfo(len(self.paths) + 1, status, s, m, ret=ret)
        self.paths.append(p)

    # ---------------------------------------------------------- expressions
    def eval(self, s, e, guard, line):
        k, w = e[0], self.w
        if k == "num": return self.const(e[1])
        if k == "var": return s.env[e[1]]
        if k == "un":
            a = self.eval(s, e[2], guard, line)
            if e[1] == "-":
                if self.check_overflow:
                    self.require(s, "signed overflow", line, tm.lnot(tm.eq(a, self.const(1 << (w - 1)))), guard)
                return tm.neg(a)
            if e[1] == "~": return tm.bvnot(a)
            return tm.bool2bv(tm.eq(a, self.const(0)), w)
        if k == "and":
            l = tm.bv2bool(self.eval(s, e[1], guard, line))
            r = tm.bv2bool(self.eval(s, e[2], tm.land(guard, l), line))
            return tm.bool2bv(tm.land(l, r), w)
        if k == "or":
            l = tm.bv2bool(self.eval(s, e[1], guard, line))
            r = tm.bv2bool(self.eval(s, e[2], tm.land(guard, tm.lnot(l)), line))
            return tm.bool2bv(tm.lor(l, r), w)
        if k == "cond":
            c = tm.bv2bool(self.eval(s, e[1], guard, line))
            a = self.eval(s, e[2], tm.land(guard, c), line)
            b = self.eval(s, e[3], tm.land(guard, tm.lnot(c)), line)
            return tm.ite(c, a, b)
        op = e[1]
        a = self.eval(s, e[2], guard, line)
        b = self.eval(s, e[3], guard, line)
        c0 = self.const(0)
        if op in ("+", "-", "*"):
            f = {"+": tm.add, "-": tm.sub, "*": tm.mul}[op]
            r = f(a, b)
            if self.check_overflow and not (a.is_const and b.is_const and True and
                                            self._exact_ok(op, a.val, b.val)):
                ew = w + 1 if op != "*" else 2 * w
                wide = f(tm.sext(a, ew), tm.sext(b, ew))
                self.require(s, "signed overflow", line, tm.eq(wide, tm.sext(r, ew)), guard)
            return r
        if op in ("/", "%"):
            self.require(s, "division by zero", line, tm.lnot(tm.eq(b, c0)), guard)
            if self.check_overflow:
                bad = tm.land(tm.eq(a, self.const(1 << (w - 1))), tm.eq(b, self.const(-1)))
                self.require(s, "signed overflow", line, tm.lnot(bad), guard)
            return tm.binop("sdiv" if op == "/" else "srem", a, b)
        if op in ("<<", ">>", ">>>"):
            self.require(s, "invalid shift", line, tm.ult(b, self.const(w)), guard)
            return tm.binop(BINOPS[op], a, b)
        if op == "&": return tm.bvand(a, b)
        if op == "|": return tm.bvor(a, b)
        if op == "^": return tm.bvxor(a, b)
        cmp = {"==": lambda: tm.eq(a, b), "!=": lambda: tm.lnot(tm.eq(a, b)), "<": lambda: tm.slt(a, b),
               "<=": lambda: tm.sle(a, b), ">": lambda: tm.slt(b, a), ">=": lambda: tm.sle(b, a)}[op]()
        return tm.bool2bv(cmp, w)

    def _exact_ok(self, op, x, y):
        sx, sy = tm.to_signed(x, self.w), tm.to_signed(y, self.w)
        r = sx + sy if op == "+" else sx - sy if op == "-" else sx * sy
        return -(1 << (self.w - 1)) <= r < (1 << (self.w - 1))

    # ---------------------------------------------------------- verification
    def verify(self):
        """Replay every generated test and every bug witness on the concrete interpreter."""
        interp = Interp(self.prog, self.w)
        for p in self.paths:
            r = interp.run(p.inputs)
            if p.status == "error":
                p.verified = (r.trap == p.trap)
            else:
                exp_ret = tm.to_signed(tm.evaluate(p.ret, p.model), self.w) if p.ret is not None else None
                got_ret = tm.to_signed(r.value, self.w) if r.value is not None else None
                if p.ret is None: got_ret = None
                exp_out = [tm.to_signed(tm.evaluate(o, p.model), self.w) for o in p.outputs]
                p.expected_ret, p.expected_out = exp_ret, exp_out
                p.verified = (r.trap is None and not r.infeasible and not r.exhausted
                              and got_ret == exp_ret and r.outputs == exp_out)
        for b in self.bugs.values():
            r = interp.run(b.inputs)
            b.confirmed = (r.trap == (b.kind, b.line))
        return all(p.verified for p in self.paths) and all(b.confirmed for b in self.bugs.values())

    # ---------------------------------------------------------- summaries
    def coverage(self):
        lines = set().union(*[p.lines for p in self.paths]) if self.paths else set()
        br = set().union(*[p.branches for p in self.paths]) if self.paths else set()
        return {"lines": lines & self.all_lines, "all_lines": self.all_lines,
                "branches": br & self.all_branches, "all_branches": self.all_branches}
