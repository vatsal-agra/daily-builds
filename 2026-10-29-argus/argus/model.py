"""Compile a parsed Argus program into an executable transition system.

Each process instance becomes a control-flow graph whose edges carry Python closures
(guard + action) generated from the source expressions.  A global state is a flat tuple:
`[globals..., channels..., (pc, locals...) per process instance]`.
"""
from types import SimpleNamespace

from .lang import ArgusError, fmt, parse


class ModelError(Exception):
    """Runtime error while executing a transition (OOB index, div by zero, range...)."""


class AssertFail(ModelError):
    pass


class StepError(Exception):
    """A transition raised while being fired from some state."""

    def __init__(self, pid, edge, msg, kind):
        super().__init__(msg)
        self.pid, self.edge, self.msg, self.kind = pid, edge, msg, kind


# -- runtime helpers available to generated code ------------------------------------------
def _ix(i, n, name):
    if 0 <= i < n:
        return i
    raise ModelError(f"index {i} out of bounds for {name}[{n}]")


def _div(a, b):
    if b == 0:
        raise ModelError("division by zero")
    q = abs(a) // abs(b)
    return q if (a < 0) == (b < 0) else -q


def _mod(a, b):
    if b == 0:
        raise ModelError("modulo by zero")
    return a - b * _div(a, b)


def _rng(v, lo, hi, name):
    if lo <= v <= hi:
        return v
    raise ModelError(f"value {v} out of range {lo}..{hi} for {name}")


def _head(q, k, name):
    if not q:
        raise ModelError(f"head of empty channel {name}")
    if not 0 <= k < len(q[0]):
        raise ModelError(f"head({name}, {k}): message has {len(q[0])} fields")
    return q[0][k]


RUNTIME = {"_ix": _ix, "_div": _div, "_mod": _mod, "_rng": _rng, "_head": _head,
           "ModelError": ModelError, "AssertFail": AssertFail}

INF = float("inf")


class Edge:
    __slots__ = ("id", "pid", "src", "dst", "guard", "act", "text", "line", "local", "kind")

    def __repr__(self):
        return f"<Edge {self.id} p{self.pid} {self.src}->{self.dst} {self.text}>"


class Proc:
    def __init__(self, name, pid, pc_slot):
        self.name, self.id, self.pc_slot = name, pid, pc_slot
        self.out = []          # node -> [Edge]
        self.node_name = []
        self.end_ok = []
        self.labels = {}
        self.locals = {}       # local name -> slot
        self.type = None


class Model:
    pass


def const_eval(e, env):
    k = e.kind
    if k == "num":
        return e.val
    if k == "name":
        if e.name in env:
            return env[e.name]
        raise ArgusError(f"'{e.name}' is not a compile-time constant here", e.line)
    if k == "un":
        a = const_eval(e.a, env)
        return {"-": -a, "!": 0 if a else 1, "~": ~a}[e.op]
    if k == "bin":
        a, b = const_eval(e.a, env), const_eval(e.b, env)
        op = e.op
        if op == "&&":
            return 1 if a and b else 0
        if op == "||":
            return 1 if a or b else 0
        if op in ("/", "%"):
            if b == 0:
                raise ArgusError("division by zero in constant expression", e.line)
            return _div(a, b) if op == "/" else _mod(a, b)
        return int(eval(f"a {op} b", {}, {"a": a, "b": b}))
    if k == "tern":
        return const_eval(e.a if const_eval(e.c, env) else e.b, env)
    raise ArgusError(f"'{fmt(e)}' is not a compile-time constant", e.line)


class Gen:
    """Expression/statement code generator for one context (an instance or a property)."""

    def __init__(self, m, locals_=None, insts=None, inst_name=None):
        self.m = m
        self.locals = locals_ or {}     # name -> (slot, lo, hi)
        self.insts = insts              # for properties: name -> Proc
        self.inst_name = inst_name
        self.shared = False
        self.props = insts is not None

    def ex(self, e):
        m, k = self.m, e.kind
        if k == "num":
            return f"({e.val})"
        if k == "name":
            n = e.name
            if n in self.locals:
                return f"s[{self.locals[n][0]}]"
            if n in m.vars:
                v = m.vars[n]
                if v.size is not None:
                    raise ArgusError(f"array '{n}' needs an index", e.line)
                self.shared = True
                return f"s[{v.base}]"
            if n in m.consts:
                return f"({m.consts[n]})"
            if n in m.chans:
                raise ArgusError(f"channel '{n}' cannot be used as a value (use len/empty/full/head)", e.line)
            raise ArgusError(f"undefined name '{n}'", e.line)
        if k == "idx":
            v = m.vars.get(e.name)
            if v is None or v.size is None:
                raise ArgusError(f"'{e.name}' is not a global array", e.line)
            self.shared = True
            return f"s[{v.base}+_ix({self.ex(e.index)},{v.size},{e.name!r})]"
        if k == "qual":
            if not self.props:
                raise ArgusError("qualified names (inst.var) are only allowed in invariants and ltl", e.line)
            p = self.insts.get(e.inst)
            if p is None:
                raise ArgusError(f"unknown process instance '{e.inst}'", e.line)
            if e.name not in p.locals:
                raise ArgusError(f"process {e.inst} has no local '{e.name}'", e.line)
            return f"s[{p.locals[e.name]}]"
        if k == "at":
            if not self.props:
                raise ArgusError("at(...) is only allowed in invariants and ltl", e.line)
            p = self.insts.get(e.inst)
            if p is None:
                raise ArgusError(f"unknown process instance '{e.inst}'", e.line)
            if e.label not in p.labels:
                raise ArgusError(f"process {e.inst} has no label '{e.label}'", e.line)
            return f"(1 if s[{p.pc_slot}]=={p.labels[e.label]} else 0)"
        if k == "un":
            a = self.ex(e.a)
            return {"!": f"(0 if {a} else 1)", "-": f"(-{a})", "~": f"(~{a})"}[e.op]
        if k == "bin":
            a, b, op = self.ex(e.a), self.ex(e.b), e.op
            if op == "&&":
                return f"(1 if ({a} and {b}) else 0)"
            if op == "||":
                return f"(1 if ({a} or {b}) else 0)"
            if op == "/":
                return f"_div({a},{b})"
            if op == "%":
                return f"_mod({a},{b})"
            if op in ("==", "!=", "<", "<=", ">", ">="):
                return f"(1 if {a} {op} {b} else 0)"
            return f"({a} {op} {b})"
        if k == "tern":
            return f"({self.ex(e.a)} if {self.ex(e.c)} else {self.ex(e.b)})"
        if k == "call":
            ch = m.chans.get(e.args[0])
            if ch is None:
                raise ArgusError(f"unknown channel '{e.args[0]}'", e.line)
            self.shared = True
            if e.fn == "len":
                return f"len(s[{ch.slot}])"
            if e.fn == "empty":
                return f"(0 if s[{ch.slot}] else 1)"
            if e.fn == "full":
                return f"(1 if len(s[{ch.slot}])>={ch.cap} else 0)"
            idx = self.ex(e.args[1]) if len(e.args) > 1 else "0"
            return f"_head(s[{ch.slot}],{idx},{ch.name!r})"
        raise AssertionError(k)

    def target(self, lv):
        """Returns (python lvalue source, name, lo, hi)."""
        m = self.m
        if lv.kind == "name":
            n = lv.name
            if n in self.locals:
                slot, lo, hi = self.locals[n]
                return f"s[{slot}]", n, lo, hi
            v = m.vars.get(n)
            if v is None:
                raise ArgusError(f"undefined variable '{n}'" if n not in m.consts else f"cannot assign to constant '{n}'", lv.line)
            if v.size is not None:
                raise ArgusError(f"array '{n}' needs an index", lv.line)
            self.shared = True
            return f"s[{v.base}]", n, v.lo, v.hi
        v = m.vars.get(lv.name)
        if v is None or v.size is None:
            raise ArgusError(f"'{lv.name}' is not a global array", lv.line)
        self.shared = True
        return f"s[{v.base}+_ix({self.ex(lv.index)},{v.size},{lv.name!r})]", f"{lv.name}[]", v.lo, v.hi

    def assign_line(self, lv, valsrc):
        tgt, name, lo, hi = self.target(lv)
        if lo != -INF or hi != INF:
            valsrc = f"_rng({valsrc},{lo},{hi},{name!r})"
        return f"{tgt} = {valsrc}"


def stmt_text(st, limit=60):
    k = st.kind
    if k == "assign":
        t = f"{fmt(st.lv)} = {fmt(st.expr)}"
    elif k == "skip":
        t = "skip"
    elif k == "break":
        t = "break"
    elif k == "assert":
        t = f"assert {fmt(st.expr)}"
    elif k == "await":
        t = f"await {fmt(st.expr)}"
    elif k == "send":
        t = f"send({', '.join([st.chan] + [fmt(a) for a in st.args])})"
    elif k == "recv":
        t = f"recv({', '.join([st.chan] + [fmt(a) for a in st.lvs])})"
    elif k == "if":
        t = f"if ({fmt(st.cond)}) {{...}}"
    elif k == "atomic":
        t = "atomic { " + "; ".join(stmt_text(s, 40) for s in st.body) + " }"
    else:
        t = k
    return t if len(t) <= limit else t[:limit - 1] + "…"


class Builder:
    """Builds one process instance's CFG and generated code."""

    def __init__(self, m, proc, params, ptype):
        self.m, self.proc, self.ptype = m, proc, ptype
        self.nodes = 0
        self.edges = []
        cx_locals = {}
        for name, (slot, lo, hi) in params.items():
            cx_locals[name] = (slot, lo, hi)
        self.locals = cx_locals
        proc.out = []
        self.new_node()   # node 0 = start

    def new_node(self):
        self.proc.out.append([])
        self.nodes += 1
        return self.nodes - 1

    def add(self, src, dst, gsrc, lines, text, line, shared, kind="plain"):
        e = Edge()
        e.id = len(self.m.edges)
        e.pid, e.src, e.dst, e.text, e.line = self.proc.id, src, dst, text, line
        e.kind = kind
        e.local = (not shared) and kind != "assert"
        self.m.edges.append(e)
        self.m.pending.append((e, gsrc, lines))
        self.proc.out[src].append(e)
        return e

    # -- statements ---------------------------------------------------------------------
    def seq(self, stmts, entry, exit_, brk):
        real = [i for i, s in enumerate(stmts) if s.kind != "label"]
        last_real = real[-1] if real else -1
        cur = entry
        for i, st in enumerate(stmts):
            if st.kind == "label":
                self.bind(st, exit_ if i > last_real else cur)
                continue
            nxt = exit_ if i == last_real else self.new_node()
            self.stmt(st, cur, nxt, brk)
            cur = nxt
        if not real:
            self.add(entry, exit_, None, ["pass"], "skip", stmts[0].line if stmts else 0, False)

    def bind(self, st, node):
        if st.name in self.proc.labels:
            raise ArgusError(f"duplicate label '{st.name}' in {self.proc.name}", st.line)
        self.proc.labels[st.name] = node

    def gen(self):
        g = Gen(self.m, self.locals)
        return g

    def stmt(self, st, entry, exit_, brk):
        k, L = st.kind, st.line
        if k == "if":
            g = self.gen()
            c = g.ex(st.cond)
            then_entry = self.new_node()
            self.add(entry, then_entry, c, None, f"if ({fmt(st.cond)})", L, g.shared)
            self.seq(st.then, then_entry, exit_, brk) if st.then else self.add(then_entry, exit_, None, ["pass"], "skip", L, False)
            if st.els:
                else_entry = self.new_node()
                self.add(entry, else_entry, f"not {c}", None, "else", L, g.shared)
                self.seq(st.els, else_entry, exit_, brk)
            else:
                self.add(entry, exit_, f"not {c}", None, "else", L, g.shared)
        elif k == "while":
            g = self.gen()
            c = g.ex(st.cond)
            body_entry = self.new_node()
            self.add(entry, body_entry, c, None, f"while ({fmt(st.cond)})", L, g.shared)
            self.add(entry, exit_, f"not {c}", None, f"while ({fmt(st.cond)}) exits", L, g.shared)
            if st.body:
                self.seq(st.body, body_entry, entry, exit_)
            else:
                self.add(body_entry, entry, None, ["pass"], "skip", L, False)
        elif k == "loop":
            self.seq(st.body or [type(st)(kind="skip", line=L)], entry, entry, exit_)
        elif k == "break":
            if brk is None:
                raise ArgusError("'break' outside of a loop", L)
            self.add(entry, brk, None, ["pass"], "break", L, False)
        elif k == "either":
            for br in st.branches:
                self.seq(br, entry, exit_, brk) if br else self.add(entry, exit_, None, ["pass"], "skip", L, False)
        elif k == "atomic":
            self.atomic(st, entry, exit_)
        elif k == "nondet":
            lo = const_eval(st.lo, self.m.param_env(self))
            hi = const_eval(st.hi, self.m.param_env(self))
            if hi < lo or hi - lo > 255:
                raise ArgusError(f"nondet range {lo}..{hi} is empty or too large (max 256 values)", L)
            for v in range(lo, hi + 1):
                g = self.gen()
                line = g.assign_line(st.lv, str(v))
                self.add(entry, exit_, None, [line], f"{fmt(st.lv)} = {v}  (nondet {lo}..{hi})", L, g.shared)
        else:
            g = self.gen()
            gs, lines, shared = self.simple(st, g, first=True)
            kind = "assert" if k == "assert" else "plain"
            self.add(entry, exit_, gs, lines, stmt_text(st), L, g.shared, kind)

    def simple(self, st, g, first):
        """Returns (guard_src|None, action lines). Blocking ops only allowed when `first`."""
        k, L = st.kind, st.line
        m = self.m
        if k == "skip":
            return None, ["pass"], g.shared
        if k == "assign":
            return None, [g.assign_line(st.lv, g.ex(st.expr))], g.shared
        if k == "assert":
            msg = st.msg or f"assertion failed: {fmt(st.expr)}"
            return None, [f"if not ({g.ex(st.expr)}): raise AssertFail({msg!r})"], g.shared
        if k == "await":
            if not first:
                raise ArgusError("'await' is only allowed as the first statement of an atomic block", L)
            return g.ex(st.expr), ["pass"], g.shared
        if k in ("send", "recv"):
            if not first:
                raise ArgusError(f"'{k}' is only allowed as the first statement of an atomic block", L)
            ch = m.chans.get(st.chan)
            if ch is None:
                raise ArgusError(f"unknown channel '{st.chan}'", L)
            g.shared = True
            if k == "send":
                if len(st.args) != ch.arity:
                    raise ArgusError(f"channel {ch.name} carries {ch.arity} field(s), send gives {len(st.args)}", L)
                msg = "(" + "".join(g.ex(a) + "," for a in st.args) + ")"
                return f"len(s[{ch.slot}]) < {ch.cap}", [f"s[{ch.slot}] = s[{ch.slot}] + ({msg},)"], True
            if len(st.lvs) != ch.arity:
                raise ArgusError(f"channel {ch.name} carries {ch.arity} field(s), recv names {len(st.lvs)}", L)
            lines = [f"_m = s[{ch.slot}][0]", f"s[{ch.slot}] = s[{ch.slot}][1:]"]
            for i, lv in enumerate(st.lvs):
                lines.append(g.assign_line(lv, f"_m[{i}]"))
            return f"len(s[{ch.slot}]) > 0", lines, True
        raise ArgusError(f"statement '{k}' is not allowed here", L)

    def inline(self, stmts, g, ind, first):
        """Atomic-block body → python lines (no blocking except a leading guard)."""
        pad = "    " * ind
        out = []
        for i, st in enumerate(stmts):
            k = st.kind
            if k == "if":
                out.append(f"{pad}if {g.ex(st.cond)}:")
                body = self.inline(st.then, g, ind + 1, False) if st.then else []
                out.extend(body or [pad + "    pass"])
                if st.els:
                    out.append(f"{pad}else:")
                    out.extend(self.inline(st.els, g, ind + 1, False) or [pad + "    pass"])
            elif k == "atomic":
                out.extend(self.inline(st.body, g, ind, first and i == 0))
            elif k in ("while", "loop", "either", "nondet", "break", "label"):
                raise ArgusError(f"'{k}' is not allowed inside atomic", st.line)
            else:
                _, lines, _ = self.simple(st, g, first=False)
                out.extend(pad + ln for ln in lines)
        return out

    def atomic(self, st, entry, exit_):
        g = self.gen()
        flat = self.flatten_atomic(st.body)
        guard, lines = None, []
        if flat and flat[0].kind in ("await", "send", "recv"):
            guard, lines, _ = self.simple(flat[0], g, first=True)
            flat = flat[1:]
        lines = lines + self.inline(flat, g, 0, False)
        self.add(entry, exit_, guard, lines or ["pass"], stmt_text(st, 70), st.line, g.shared)

    def flatten_atomic(self, body):
        out = []
        for st in body:
            if st.kind == "atomic":
                out.extend(self.flatten_atomic(st.body))
            else:
                out.append(st)
        return out


class Spec:
    pass


def build(src, defines=None, filename="<model>"):
    prog = parse(src)
    m = Model()
    m.source, m.filename = src, filename
    m.edges, m.pending = [], []
    defines = dict(defines or {})

    # constants
    m.consts = {}
    for c in prog.consts:
        if c.name in m.consts:
            raise ArgusError(f"duplicate constant '{c.name}'", c.line, None, src)
        m.consts[c.name] = defines.pop(c.name) if c.name in defines else const_eval(c.expr, m.consts)
    if defines:
        raise ArgusError(f"-D names not declared as const in the model: {', '.join(sorted(defines))}")

    init, names = [], []
    m.vars, m.chans = {}, {}
    taken = set(m.consts)

    def declare(name, line):
        if name in taken:
            raise ArgusError(f"name '{name}' declared twice", line, None, src)
        taken.add(name)

    for v in prog.vars:
        declare(v.name, v.line)
        lo, hi = (-INF, INF)
        if v.rng:
            lo, hi = const_eval(v.rng[0], m.consts), const_eval(v.rng[1], m.consts)
            if lo > hi:
                raise ArgusError(f"empty range {lo}..{hi} for '{v.name}'", v.line, None, src)
        size = const_eval(v.size, m.consts) if v.size is not None else None
        if size is not None and size < 1:
            raise ArgusError(f"array '{v.name}' must have size >= 1", v.line, None, src)
        n = size if size is not None else 1
        if v.init is None:
            vals = [0] * n
        elif isinstance(v.init, list):
            if size is None or len(v.init) != size:
                raise ArgusError(f"initializer list for '{v.name}' must match its array size", v.line, None, src)
            vals = [const_eval(e, m.consts) for e in v.init]
        else:
            vals = [const_eval(v.init, m.consts)] * n
        for x in vals:
            if not lo <= x <= hi:
                raise ArgusError(f"initial value {x} of '{v.name}' outside {lo}..{hi}", v.line, None, src)
        m.vars[v.name] = SimpleNamespace(name=v.name, base=len(init), size=size, lo=lo, hi=hi)
        for i, x in enumerate(vals):
            names.append(f"{v.name}[{i}]" if size is not None else v.name)
            init.append(x)
    for c in prog.chans:
        declare(c.name, c.line)
        cap, arity = const_eval(c.cap, m.consts), const_eval(c.arity, m.consts)
        if cap < 1 or arity < 1:
            raise ArgusError(f"channel '{c.name}' needs capacity >= 1 and arity >= 1", c.line, None, src)
        m.chans[c.name] = SimpleNamespace(name=c.name, slot=len(init), cap=cap, arity=arity)
        names.append(c.name)
        init.append(())

    ptypes = {}
    for p in prog.procs:
        if p.name in ptypes:
            raise ArgusError(f"duplicate process '{p.name}'", p.line, None, src)
        ptypes[p.name] = p

    # expand runs
    runs = []

    def expand(items, env):
        for r in items:
            if r.kind == "runfor":
                lo, hi = const_eval(r.lo, env), const_eval(r.hi, env)
                if hi - lo > 1000:
                    raise ArgusError("'for' range too large", r.line, None, src)
                for i in range(lo, hi + 1):
                    expand(r.body, {**env, r.var: i})
            else:
                runs.append((r, dict(env)))

    expand(prog.runs, dict(m.consts))
    if not runs:
        raise ArgusError("model has no 'run' statements (nothing to execute)")

    m.procs = []
    m.param_envs = {}
    per_type = {}
    names_used = set()
    for r, env in runs:
        pt = ptypes.get(r.proc)
        if pt is None:
            raise ArgusError(f"unknown process '{r.proc}'", r.line, None, src)
        if len(r.args) != len(pt.params):
            raise ArgusError(f"{r.proc} takes {len(pt.params)} argument(s), got {len(r.args)}", r.line, None, src)
        k = per_type.get(r.proc, 0)
        per_type[r.proc] = k + 1
        iname = r.alias or f"{r.proc}{k}"
        if iname in names_used or iname in taken:
            raise ArgusError(f"instance name '{iname}' is not unique", r.line, None, src)
        names_used.add(iname)
        pid = len(m.procs)
        proc = Proc(iname, pid, len(init))
        proc.type = pt
        init.append(0)
        names.append(f"{iname}.pc")
        locals_ = {}
        penv = dict(m.consts)
        for pn, a in zip(pt.params, r.args):
            val = const_eval(a, env)
            locals_[pn] = (len(init), -INF, INF)
            proc.locals[pn] = len(init)
            penv[pn] = val
            names.append(f"{iname}.{pn}")
            init.append(val)
        for d in pt.locals:
            if d.name in locals_ or d.name in m.vars or d.name in m.consts:
                raise ArgusError(f"local '{d.name}' shadows another name", d.line, None, src)
            lo, hi = (-INF, INF)
            if d.rng:
                lo, hi = const_eval(d.rng[0], penv), const_eval(d.rng[1], penv)
            val = const_eval(d.init, penv) if d.init is not None else 0
            if not lo <= val <= hi:
                raise ArgusError(f"initial value {val} of local '{d.name}' outside {lo}..{hi}", d.line, None, src)
            locals_[d.name] = (len(init), lo, hi)
            proc.locals[d.name] = len(init)
            penv[d.name] = val
            names.append(f"{iname}.{d.name}")
            init.append(val)
        m.param_envs[pid] = {**m.consts, **{pn: penv[pn] for pn in pt.params}}
        b = Builder(m, proc, locals_, pt)
        b.pid = pid
        end = b.new_node()
        b.seq(pt.body, 0, end, None) if pt.body else b.add(0, end, None, ["pass"], "skip", pt.line, False)
        proc.end_node = end
        n = b.nodes
        proc.end_ok = [False] * n
        proc.end_ok[end] = True
        for lab, node in proc.labels.items():
            if lab.startswith("end"):
                proc.end_ok[node] = True
        inv = {}
        for lab, node in proc.labels.items():
            inv.setdefault(node, lab)
        proc.node_name = []
        for i in range(n):
            if i in inv:
                proc.node_name.append(inv[i])
            elif i == end:
                proc.node_name.append("end")
            elif proc.out[i]:
                proc.node_name.append(f"L{proc.out[i][0].line}")
            else:
                proc.node_name.append(f"n{i}")
        # keep node names unique per process (two nodes may share a line)
        seen = {}
        for i, nm in enumerate(proc.node_name):
            if nm in seen:
                proc.node_name[i] = f"{nm}.{i}"
            seen[nm] = i
        m.procs.append(proc)

    m.init = tuple(init)
    m.slot_names = names
    m.pc_slots = {p.pc_slot: p for p in m.procs}
    m.chan_slots = {c.slot: c for c in m.chans.values()}
    m.nproc = len(m.procs)

    # exec generated code
    code = []
    for e, gsrc, lines in m.pending:
        if gsrc is not None:
            code.append(f"def g{e.id}(s):\n    return {gsrc}")
        if lines is not None and lines != ["pass"]:
            code.append(f"def a{e.id}(s):\n" + "\n".join("    " + ln for ln in lines))
    ns = dict(RUNTIME)
    exec(compile("\n".join(code), f"<argus:{filename}>", "exec"), ns)
    for e, gsrc, lines in m.pending:
        e.guard = ns.get(f"g{e.id}") if gsrc is not None else None
        e.act = ns.get(f"a{e.id}")
    del m.pending

    # properties
    insts = {p.name: p for p in m.procs}
    m.invariants = []
    seen_names = set()
    for iv in prog.invariants:
        if iv.name in seen_names:
            raise ArgusError(f"duplicate property name '{iv.name}'", iv.line, None, src)
        seen_names.add(iv.name)
        m.invariants.append(SimpleNamespace(name=iv.name, line=iv.line, text=fmt(iv.expr),
                                            fn=compile_prop(m, iv.expr, insts)))
    m.ltls = []
    for lt in prog.ltls:
        if lt.name in seen_names:
            raise ArgusError(f"duplicate property name '{lt.name}'", lt.line, None, src)
        seen_names.add(lt.name)
        atoms, index = [], {}

        def conv(f):
            if f[0] == "atom":
                text = fmt(f[1])
                if text not in index:
                    index[text] = len(atoms)
                    atoms.append((text, compile_prop(m, f[1], insts)))
                return ("ap", index[text])
            if f[0] in ("true", "false"):
                return f
            return (f[0],) + tuple(conv(x) for x in f[1:])

        m.ltls.append(SimpleNamespace(name=lt.name, line=lt.line, formula=conv(lt.formula), atoms=atoms))
    # which processes do properties observe?  (for partial-order reduction visibility)
    m.observed_all = bool(prog.ltls)
    m.observed = set()
    for iv in prog.invariants:
        _collect_insts(iv.expr, m.observed)
    return m


def _collect_insts(e, out):
    if e.kind in ("qual",):
        out.add(e.inst)
    elif e.kind == "at":
        out.add(e.inst)
    for f in ("a", "b", "c"):
        sub = getattr(e, f, None)
        if sub is not None and hasattr(sub, "kind"):
            _collect_insts(sub, out)
    if e.kind == "idx":
        _collect_insts(e.index, out)


def compile_prop(m, expr, insts):
    g = Gen(m, {}, insts)
    src = g.ex(expr)
    ns = dict(RUNTIME)
    exec(f"def _p(s):\n    return {src}", ns)
    return ns["_p"]


def param_env(self, builder):
    return self.param_envs[builder.pid]


Model.param_env = param_env


# ----------------------------------------------------------------------------------------
# execution
# ----------------------------------------------------------------------------------------
def successors(m, s):
    """All enabled transitions from s: [(pid, edge, next_state)].  May raise StepError."""
    out = []
    for p in m.procs:
        for e in p.out[s[p.pc_slot]]:
            try:
                if e.guard is not None and not e.guard(s):
                    continue
                t = list(s)
                t[p.pc_slot] = e.dst
                if e.act is not None:
                    e.act(t)
            except AssertFail as ex:
                raise StepError(p.id, e, str(ex), "assert")
            except ModelError as ex:
                raise StepError(p.id, e, f"runtime error: {ex}", "error")
            except (ValueError, OverflowError, MemoryError) as ex:
                raise StepError(p.id, e, f"runtime error: {ex}", "error")
            out.append((p.id, e, tuple(t)))
    return out


def is_end(m, s):
    return all(p.end_ok[s[p.pc_slot]] for p in m.procs)


def fmt_slot(m, slot, v):
    p = m.pc_slots.get(slot)
    if p is not None:
        return p.node_name[v]
    if slot in m.chan_slots:
        return "<" + ", ".join("(" + ",".join(map(str, msg)) + ")" if len(msg) > 1 else str(msg[0]) for msg in v) + ">"
    return str(v)


def state_str(m, s, procs=True):
    parts = []
    for name, v in m.vars.items():
        if v.size is None:
            parts.append(f"{name}={s[v.base]}")
        else:
            parts.append(f"{name}=[{','.join(map(str, s[v.base:v.base + v.size]))}]")
    for name, c in m.chans.items():
        parts.append(f"{name}={fmt_slot(m, c.slot, s[c.slot])}")
    out = " ".join(parts)
    if procs:
        locs = []
        for p in m.procs:
            loc = p.node_name[s[p.pc_slot]]
            lv = " ".join(f"{k}={s[sl]}" for k, sl in p.locals.items()) if p.locals else ""
            locs.append(f"{p.name}@{loc}" + (f"({lv})" if lv else ""))
        out += "  |  " + " ".join(locs)
    return out


def diff_str(m, a, b):
    ch = []
    for i, (x, y) in enumerate(zip(a, b)):
        if x != y:
            ch.append(f"{m.slot_names[i]}: {fmt_slot(m, i, x)} → {fmt_slot(m, i, y)}")
    return ch
