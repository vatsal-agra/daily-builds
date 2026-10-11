"""Hash-consed bit-vector / boolean terms with constant folding and algebraic
simplification, plus the single source of truth for operator semantics
(`apply_op`) shared by folding, the concrete interpreter and model evaluation.

Sorts: width 0 = Bool, width w >= 1 = bit-vector of w bits (two's complement).
"""

BOOL = 0


class T:
    __slots__ = ("op", "args", "w", "val", "id", "_h")
    _table = {}
    _next = 0

    def __init__(self, op, args, w, val=None):
        self.op, self.args, self.w, self.val = op, args, w, val
        T._next += 1
        self.id = T._next

    def __repr__(self):
        return show(self)

    @property
    def is_const(self):
        return self.op == "const"


def _mk(op, args, w, val=None):
    key = (op, tuple(a.id for a in args), w, val)
    t = T._table.get(key)
    if t is None:
        t = T(op, tuple(args), w, val)
        T._table[key] = t
    return t


def mask(w):
    return (1 << w) - 1


def to_signed(v, w):
    return v - (1 << w) if v >> (w - 1) else v


# ---------------------------------------------------------------- semantics
def apply_op(op, vals, w, aw=None):
    """Concrete semantics. vals: unsigned ints (bools as 0/1). w: result width
    (0 = bool). aw: operand width for comparisons/extensions."""
    m = mask(w) if w else 1
    if op == "add": return (vals[0] + vals[1]) & m
    if op == "sub": return (vals[0] - vals[1]) & m
    if op == "mul": return (vals[0] * vals[1]) & m
    if op == "neg": return (-vals[0]) & m
    if op == "bnot": return (~vals[0]) & m
    if op == "and": return vals[0] & vals[1]
    if op == "or": return vals[0] | vals[1]
    if op == "xor": return vals[0] ^ vals[1]
    if op == "udiv": return m if vals[1] == 0 else vals[0] // vals[1]
    if op == "urem": return vals[0] if vals[1] == 0 else vals[0] % vals[1]
    if op in ("sdiv", "srem"):
        a, b = vals
        sa, sb = to_signed(a, w), to_signed(b, w)
        ua, ub = abs(sa), abs(sb)
        q = m if ub == 0 else ua // ub
        r = ua if ub == 0 else ua % ub
        if op == "sdiv":
            return ((-q) & m) if (sa < 0) != (sb < 0) else q & m
        return ((-r) & m) if sa < 0 else r & m
    if op == "shl": return (vals[0] << vals[1]) & m if vals[1] < w else 0
    if op == "lshr": return vals[0] >> vals[1] if vals[1] < w else 0
    if op == "ashr":
        s = to_signed(vals[0], w)
        return (s >> min(vals[1], w)) & m
    if op == "eq": return int(vals[0] == vals[1])
    if op == "ult": return int(vals[0] < vals[1])
    if op == "ule": return int(vals[0] <= vals[1])
    if op == "slt": return int(to_signed(vals[0], aw) < to_signed(vals[1], aw))
    if op == "sle": return int(to_signed(vals[0], aw) <= to_signed(vals[1], aw))
    if op == "band": return vals[0] & vals[1]
    if op == "bor": return vals[0] | vals[1]
    if op == "not": return 1 - vals[0]
    if op == "ite": return vals[1] if vals[0] else vals[2]
    if op == "zext": return vals[0]
    if op == "sext": return to_signed(vals[0], aw) & m
    if op == "trunc": return vals[0] & m
    if op == "bool2bv": return vals[0]
    raise ValueError(op)


# -------------------------------------------------------------- constructors
def const(v, w):
    return _mk("const", (), w, v & mask(w))


TRUE = _mk("const", (), BOOL, 1)
FALSE = _mk("const", (), BOOL, 0)


def var(name, w):
    return _mk("var", (), w, name)


def boolv(b):
    return TRUE if b else FALSE


def _fold(op, args, w, aw=None):
    return _mk("const", (), w, apply_op(op, [a.val for a in args], w, aw))


def _comm(a, b):
    return (a, b) if a.id <= b.id else (b, a)


def add(a, b):
    if a.is_const and b.is_const: return _fold("add", (a, b), a.w)
    if a.is_const and a.val == 0: return b
    if b.is_const and b.val == 0: return a
    a, b = _comm(a, b)
    return _mk("add", (a, b), a.w)


def sub(a, b):
    if a.is_const and b.is_const: return _fold("sub", (a, b), a.w)
    if b.is_const and b.val == 0: return a
    if a is b: return const(0, a.w)
    return _mk("sub", (a, b), a.w)


def mul(a, b):
    if a.is_const and b.is_const: return _fold("mul", (a, b), a.w)
    for x, y in ((a, b), (b, a)):
        if x.is_const:
            if x.val == 0: return x
            if x.val == 1: return y
    a, b = _comm(a, b)
    return _mk("mul", (a, b), a.w)


def neg(a):
    if a.is_const: return _fold("neg", (a,), a.w)
    if a.op == "neg": return a.args[0]
    return _mk("neg", (a,), a.w)


def bvnot(a):
    if a.is_const: return _fold("bnot", (a,), a.w)
    if a.op == "bnot": return a.args[0]
    return _mk("bnot", (a,), a.w)


def bvand(a, b):
    if a.is_const and b.is_const: return _fold("and", (a, b), a.w)
    for x, y in ((a, b), (b, a)):
        if x.is_const:
            if x.val == 0: return x
            if x.val == mask(x.w): return y
    if a is b: return a
    a, b = _comm(a, b)
    return _mk("and", (a, b), a.w)


def bvor(a, b):
    if a.is_const and b.is_const: return _fold("or", (a, b), a.w)
    for x, y in ((a, b), (b, a)):
        if x.is_const:
            if x.val == 0: return y
            if x.val == mask(x.w): return x
    if a is b: return a
    a, b = _comm(a, b)
    return _mk("or", (a, b), a.w)


def bvxor(a, b):
    if a.is_const and b.is_const: return _fold("xor", (a, b), a.w)
    for x, y in ((a, b), (b, a)):
        if x.is_const and x.val == 0: return y
    if a is b: return const(0, a.w)
    a, b = _comm(a, b)
    return _mk("xor", (a, b), a.w)


def binop(op, a, b):
    """udiv urem sdiv srem shl lshr ashr (non-commutative, width preserving)."""
    if a.is_const and b.is_const and not (op in ("udiv", "urem", "sdiv", "srem") and b.val == 0):
        return _fold(op, (a, b), a.w)
    if b.is_const and b.val == 0 and op in ("shl", "lshr", "ashr"): return a
    if b.is_const and b.val == 1 and op in ("udiv", "sdiv"): return a
    if a.is_const and a.val == 0 and op in ("shl", "lshr", "udiv", "urem"): return a
    return _mk(op, (a, b), a.w)


def eq(a, b):
    if a is b: return TRUE
    if a.is_const and b.is_const: return boolv(a.val == b.val)
    if a.w == BOOL:   # bool equality
        if a is TRUE: return b
        if b is TRUE: return a
        if a is FALSE: return lnot(b)
        if b is FALSE: return lnot(a)
    a, b = _comm(a, b)
    return _mk("eq", (a, b), BOOL)


def _cmp(op, a, b):
    if a.is_const and b.is_const: return boolv(apply_op(op, [a.val, b.val], BOOL, a.w))
    if a is b: return boolv(op in ("ule", "sle"))
    return _mk(op, (a, b), BOOL)


def ult(a, b):
    if b.is_const and b.val == 0: return FALSE
    return _cmp("ult", a, b)


def ule(a, b): return _cmp("ule", a, b)
def slt(a, b): return _cmp("slt", a, b)
def sle(a, b): return _cmp("sle", a, b)


def lnot(a):
    if a is TRUE: return FALSE
    if a is FALSE: return TRUE
    if a.op == "not": return a.args[0]
    return _mk("not", (a,), BOOL)


def land(a, b):
    if a is FALSE or b is FALSE: return FALSE
    if a is TRUE: return b
    if b is TRUE: return a
    if a is b: return a
    if lnot(a) is b: return FALSE
    a, b = _comm(a, b)
    return _mk("band", (a, b), BOOL)


def lor(a, b):
    if a is TRUE or b is TRUE: return TRUE
    if a is FALSE: return b
    if b is FALSE: return a
    if a is b: return a
    if lnot(a) is b: return TRUE
    a, b = _comm(a, b)
    return _mk("bor", (a, b), BOOL)


def land_all(xs):
    r = TRUE
    for x in xs: r = land(r, x)
    return r


def ite(c, a, b):
    if c is TRUE: return a
    if c is FALSE: return b
    if a is b: return a
    if a.w == BOOL:
        if a is TRUE and b is FALSE: return c
        if a is FALSE and b is TRUE: return lnot(c)
    return _mk("ite", (c, a, b), a.w)


def zext(a, w):
    if a.w == w: return a
    if a.is_const: return const(a.val, w)
    return _mk("zext", (a,), w)


def sext(a, w):
    if a.w == w: return a
    if a.is_const: return const(to_signed(a.val, a.w), w)
    return _mk("sext", (a,), w)


def trunc(a, w):
    if a.w == w: return a
    if a.is_const: return const(a.val, w)
    return _mk("trunc", (a,), w)


def bool2bv(b, w):
    if b.is_const: return const(b.val, w)
    return ite(b, const(1, w), const(0, w))


def bv2bool(a):
    if a.op == "ite" and a.args[1].is_const and a.args[2].is_const:
        x, y = a.args[1].val != 0, a.args[2].val != 0
        if x and not y: return a.args[0]
        if y and not x: return lnot(a.args[0])
    return lnot(eq(a, const(0, a.w)))


# --------------------------------------------------------------- inspection
def children_postorder(root):
    seen, order, stack = set(), [], [(root, False)]
    while stack:
        t, done = stack.pop()
        if done:
            order.append(t)
            continue
        if t.id in seen:
            continue
        seen.add(t.id)
        stack.append((t, True))
        for a in t.args:
            if a.id not in seen:
                stack.append((a, False))
    return order


def variables(root):
    return {t.val: t.w for t in children_postorder(root) if t.op == "var"}


def evaluate(root, env):
    """Evaluate a term given env {name: int}. Unlisted variables default to 0."""
    memo = {}
    for t in children_postorder(root):
        if t.op == "const": memo[t.id] = t.val
        elif t.op == "var": memo[t.id] = env.get(t.val, 0) & (mask(t.w) if t.w else 1)
        else:
            vals = [memo[a.id] for a in t.args]
            aw = t.args[0].w if t.args else None
            memo[t.id] = apply_op(t.op, vals, t.w, aw)
    return memo[root.id]


def size(root):
    return len(children_postorder(root))


def show(t, depth=6):
    if t.op == "const":
        if t.w == BOOL: return "true" if t.val else "false"
        return str(to_signed(t.val, t.w))
    if t.op == "var": return t.val
    if depth == 0: return "…"
    sym = {"add": "+", "sub": "-", "mul": "*", "and": "&", "or": "|", "xor": "^", "udiv": "/u", "urem": "%u",
           "sdiv": "/", "srem": "%", "shl": "<<", "lshr": ">>u", "ashr": ">>", "eq": "==", "ult": "<u",
           "ule": "<=u", "slt": "<", "sle": "<=", "band": "&&", "bor": "||"}
    if t.op in sym:
        return "(%s %s %s)" % (show(t.args[0], depth - 1), sym[t.op], show(t.args[1], depth - 1))
    return "%s(%s)" % (t.op, ", ".join(show(a, depth - 1) for a in t.args))
