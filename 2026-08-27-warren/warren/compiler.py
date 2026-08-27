"""Compiles a (Head, Body) clause into real WAM instructions.

Simplifications from a textbook/production WAM, documented honestly:
  * First-argument clause indexing happens at call time (the machine
    filters candidate clauses using the caller's first argument) rather
    than via a statically compiled switch_on_term/constant/structure
    instruction trio. Net effect on backtracking behavior is the same
    (non-matching clauses never get a choice point); what differs is
    *when* the filtering decision is made.
  * Multi-clause predicate dispatch and (A;B) disjunction both use one
    dynamic choice-point mechanism (kind='clause' / kind='disj' in
    machine.py) instead of separate static try_me_else/retry_me_else/
    trust_me opcodes threaded through a single merged instruction array.
    Same semantics (one choice point per pending alternative,
    backtracking restores heap/trail/registers and advances to the next
    alternative), simpler bookkeeping.
  * No last-call optimization / environment reuse for tail calls: every
    body goal is a genuine `call` (with a real continuation pushed), so
    the machine's control state lives in `Python data (P/CP)`, not the
    Python call stack -- deep recursion works, it's just heap space, not
    Python recursion depth, that grows with clause depth.
"""
from .terms import Atom, Var, Num, Struct, deref, term_vars

NIL = Atom("[]")


def _flatten_slots(term, slots, counter):
    """Assign each 'leaf goal' a distinct slot id and record, for every
    variable, which slot ids it appears in. Recurses through ',', ';',
    '->', '*->', and '\\+' so a variable used across an internal call
    boundary *inside* a nested disjunction/if-then is still correctly
    flagged as needing to survive a call (safe over-approximation: a
    variable might get an extra distinct slot id it didn't strictly
    need, which can only make it *more* likely to be (correctly, just
    not maximally optimally) classified permanent, never less)."""
    t = deref(term)
    if isinstance(t, Struct) and t.arity == 2 and t.name in (",", ";", "->", "*->"):
        _flatten_slots(t.args[0], slots, counter)
        _flatten_slots(t.args[1], slots, counter)
        return
    if isinstance(t, Struct) and t.arity == 1 and t.name == "\\+":
        _flatten_slots(t.args[0], slots, counter)
        return
    slot_id = next(counter)
    for v in term_vars(t):
        slots.setdefault(id(v), set()).add(slot_id)


def analyze_permanent_vars(head, body):
    """Returns dict[id(Var)] -> Var for every variable that must live in
    the environment (Y registers) rather than a transient X register."""
    slots = {}
    counter = iter(range(10 ** 9))
    head_slot = next(counter)
    for v in term_vars(head):
        slots.setdefault(id(v), set()).add(head_slot)
    _flatten_slots(body, slots, counter)
    perm_ids = {vid for vid, s in slots.items() if len(s) >= 2}
    order = []
    seen = set()
    for v in term_vars(head):
        if id(v) in perm_ids and id(v) not in seen:
            seen.add(id(v))
            order.append(v)
    for v in term_vars(body):
        if id(v) in perm_ids and id(v) not in seen:
            seen.add(id(v))
            order.append(v)
    return {id(v): i for i, v in enumerate(order)}


def _body_needs_cut_barrier(t):
    t = deref(t)
    if isinstance(t, Atom) and t.name == "!":
        return True
    if isinstance(t, Struct) and t.arity == 2 and t.name in (",", ";", "->", "*->"):
        return _body_needs_cut_barrier(t.args[0]) or _body_needs_cut_barrier(t.args[1])
    return False


def _body_has_call(t):
    """True if body compiles to at least one real `call` instruction
    anywhere (including inside disjunction/if-then branches).

    This matters beyond permanent-variable bookkeeping: without last-call
    optimization (see module docstring), a clause with NO environment
    frame relies on self.CP being left completely untouched by its own
    body so its own final `proceed` still returns to whoever called it.
    But a `call` instruction always overwrites self.CP (to the address
    right after itself, for its OWN callee's eventual return) -- so ANY
    clause whose body issues a call needs an environment purely to save
    and restore CP/CE around it, even with zero permanent variables and
    no cut. Skipping the environment is only safe for bodies that never
    call anything at all (facts, and true/fail/! alone)."""
    t = deref(t)
    if isinstance(t, Atom) and t.name in ("true", "fail", "false", "!"):
        return False
    if isinstance(t, Struct) and t.arity == 2 and t.name in (",", ";", "->", "*->"):
        return _body_has_call(t.args[0]) or _body_has_call(t.args[1])
    return True


class ClauseCode:
    __slots__ = ("instrs", "arity", "head_functor", "first_arg_key")

    def __init__(self, instrs, arity, head_functor, first_arg_key):
        self.instrs = instrs
        self.arity = arity
        self.head_functor = head_functor
        self.first_arg_key = first_arg_key


def first_arg_key(head):
    """A hashable key describing the head's first argument, for runtime
    first-argument indexing -- None means 'matches anything' (a Var)."""
    head = deref(head)
    if not isinstance(head, Struct) or not head.args:
        return None
    a = deref(head.args[0])
    if isinstance(a, Var):
        return None
    if isinstance(a, Atom):
        return ("atom", a.name)
    if isinstance(a, Num):
        return ("num", a.value, isinstance(a.value, int))
    if isinstance(a, Struct):
        return ("struct", a.name, len(a.args))
    return None


class Ctx:
    def __init__(self, perm_map, base_temp):
        self.perm_map = perm_map
        self.temp_map = {}
        self.seen = set()
        self.next_temp = base_temp
        self.perm_counter = len(perm_map)
        self.instrs = []

    def new_temp(self):
        r = self.next_temp
        self.next_temp += 1
        return r

    def new_perm(self):
        r = self.perm_counter
        self.perm_counter += 1
        return r


def _max_arity(term, cur=0):
    """Max top-level call arity (head or any leaf body goal) appearing in
    a body, so temp-register allocation can start safely above every
    argument-register index actually used for a call in this clause."""
    t = deref(term)
    if isinstance(t, Struct) and t.arity == 2 and t.name in (",", ";", "->", "*->"):
        return max(_max_arity(t.args[0], cur), _max_arity(t.args[1], cur))
    if isinstance(t, Struct) and t.arity == 1 and t.name == "\\+":
        return _max_arity(t.args[0], cur)
    if isinstance(t, Struct):
        return max(cur, len(t.args))
    return cur


def compile_clause(head, body):
    head = deref(head)
    arity = len(head.args) if isinstance(head, Struct) else 0
    functor = head.name if isinstance(head, (Atom, Struct)) else None

    perm_map = analyze_permanent_vars(head, body)
    base = max(arity, _max_arity(body, 0)) + 1
    ctx = Ctx(perm_map, base)

    needs_env = bool(perm_map) or _body_needs_cut_barrier(body) or _body_has_call(body)
    alloc_idx = None
    if needs_env:
        alloc_idx = len(ctx.instrs)
        ctx.instrs.append(None)  # patched below once perm_counter is final

    # --- head ---
    if isinstance(head, Struct):
        for i, a in enumerate(head.args, start=1):
            _compile_get_arg(a, i, ctx)

    # --- body ---
    _compile_body(body, ctx)

    if needs_env:
        ctx.instrs[alloc_idx] = ("allocate", ctx.perm_counter)
        ctx.instrs.append(("deallocate",))
    ctx.instrs.append(("proceed",))

    return ClauseCode(ctx.instrs, arity, functor, first_arg_key(head))


def _compile_get_arg(t, reg, ctx):
    t = deref(t)
    if isinstance(t, Var):
        vid = id(t)
        if vid in ctx.perm_map:
            yi = ctx.perm_map[vid]
            if vid in ctx.seen:
                ctx.instrs.append(("get_val_y", yi, reg))
            else:
                ctx.seen.add(vid)
                ctx.instrs.append(("get_var_y", yi, reg))
        else:
            if vid in ctx.seen:
                home = ctx.temp_map[vid]
                ctx.instrs.append(("get_val_x", home, reg))
            else:
                ctx.seen.add(vid)
                ctx.temp_map[vid] = reg
        return
    if isinstance(t, (Atom, Num)):
        ctx.instrs.append(("get_const", t, reg))
        return
    if isinstance(t, Struct):
        ctx.instrs.append(("get_struct", t.name, len(t.args), reg))
        _compile_struct_args(t.args, ctx)
        return
    raise TypeError(f"bad term {t!r}")


def _compile_struct_args(args, ctx):
    pending = []
    for a in args:
        a = deref(a)
        if isinstance(a, Var):
            vid = id(a)
            if vid in ctx.perm_map:
                yi = ctx.perm_map[vid]
                if vid in ctx.seen:
                    ctx.instrs.append(("unify_val_y", yi))
                else:
                    ctx.seen.add(vid)
                    ctx.instrs.append(("unify_var_y", yi))
            else:
                if vid in ctx.seen:
                    reg = ctx.temp_map.get(vid)
                    if reg is None:
                        reg = ctx.new_temp()
                        ctx.temp_map[vid] = reg
                    ctx.instrs.append(("unify_val_x", reg))
                else:
                    reg = ctx.new_temp()
                    ctx.temp_map[vid] = reg
                    ctx.seen.add(vid)
                    ctx.instrs.append(("unify_var_x", reg))
        elif isinstance(a, (Atom, Num)):
            ctx.instrs.append(("unify_const", a))
        elif isinstance(a, Struct):
            reg = ctx.new_temp()
            ctx.instrs.append(("unify_var_x", reg))
            pending.append((a, reg))
        else:
            raise TypeError(f"bad term {a!r}")
    for subterm, reg in pending:
        _compile_get_arg(subterm, reg, ctx)


def _compile_put_arg(t, reg, ctx):
    t = deref(t)
    if isinstance(t, Var):
        vid = id(t)
        if vid in ctx.perm_map:
            yi = ctx.perm_map[vid]
            if vid in ctx.seen:
                ctx.instrs.append(("put_val_y", yi, reg))
            else:
                ctx.seen.add(vid)
                ctx.instrs.append(("put_var_y", yi, reg))
        else:
            if vid in ctx.seen:
                home = ctx.temp_map.get(vid)
                if home is None:
                    # variable's only prior occurrence was as a head arg
                    # reused directly as register `reg`? shouldn't happen
                    # here since get-side always registers temp_map.
                    home = reg
                ctx.instrs.append(("put_val_x", home, reg))
            else:
                tmp = ctx.new_temp()
                ctx.temp_map[vid] = tmp
                ctx.seen.add(vid)
                ctx.instrs.append(("put_var_x", tmp, reg))
        return
    if isinstance(t, (Atom, Num)):
        ctx.instrs.append(("put_const", t, reg))
        return
    if isinstance(t, Struct):
        ctx.instrs.append(("put_struct", t.name, len(t.args), reg))
        _compile_struct_args(t.args, ctx)
        return
    raise TypeError(f"bad term {t!r}")


def _compile_call(goal, ctx, indicator_override=None):
    goal = deref(goal)
    if isinstance(goal, Atom):
        name, args = goal.name, ()
    elif isinstance(goal, Struct):
        name, args = goal.name, goal.args
    else:
        raise TypeError(f"not callable: {goal!r}")
    for i, a in enumerate(args, start=1):
        _compile_put_arg(a, i, ctx)
    ind = indicator_override or (name, len(args))
    ctx.instrs.append(("call", ind))


def _compile_body(body, ctx):
    b = deref(body)

    if isinstance(b, Atom) and b.name == "true":
        return
    if isinstance(b, Atom) and b.name in ("fail", "false"):
        ctx.instrs.append(("fail",))
        return
    if isinstance(b, Atom) and b.name == "!":
        ctx.instrs.append(("cut",))
        return

    if isinstance(b, Struct) and b.name == "," and b.arity == 2:
        _compile_body(b.args[0], ctx)
        _compile_body(b.args[1], ctx)
        return

    if isinstance(b, Struct) and b.name == ";" and b.arity == 2:
        left = deref(b.args[0])
        if isinstance(left, Struct) and left.name == "->" and left.arity == 2:
            cond, then = left.args
            els = b.args[1]
            yreg = ctx.new_perm()
            ctx.instrs.append(("get_level", yreg))
            disj_idx = len(ctx.instrs)
            ctx.instrs.append(None)
            _compile_body(cond, ctx)
            ctx.instrs.append(("cut_to", yreg))
            _compile_body(then, ctx)
            jmp_idx = len(ctx.instrs)
            ctx.instrs.append(None)
            else_start = len(ctx.instrs)
            ctx.instrs[disj_idx] = ("push_disj", else_start)
            _compile_body(els, ctx)
            end = len(ctx.instrs)
            ctx.instrs[jmp_idx] = ("jump", end)
            return
        if isinstance(left, Struct) and left.name == "*->" and left.arity == 2:
            # Simplified soft-cut: compiled as a plain disjunction between
            # (Cond,Then) and Else (no cut_to), so Else only runs if the
            # WHOLE left branch is exhausted. This is a known deviation
            # from strict ISO *->, which suppresses Else as soon as Cond
            # succeeds even once, regardless of what Then does after that
            # -- documented in REVIEW.md; *-> is not in Warren's required
            # or stretch feature list.
            cond, then = left.args
            els = b.args[1]
            disj_idx = len(ctx.instrs)
            ctx.instrs.append(None)
            _compile_body(cond, ctx)
            _compile_body(then, ctx)
            jmp_idx = len(ctx.instrs)
            ctx.instrs.append(None)
            else_start = len(ctx.instrs)
            ctx.instrs[disj_idx] = ("push_disj", else_start)
            _compile_body(els, ctx)
            end = len(ctx.instrs)
            ctx.instrs[jmp_idx] = ("jump", end)
            return
        disj_idx = len(ctx.instrs)
        ctx.instrs.append(None)
        _compile_body(b.args[0], ctx)
        jmp_idx = len(ctx.instrs)
        ctx.instrs.append(None)
        b_start = len(ctx.instrs)
        ctx.instrs[disj_idx] = ("push_disj", b_start)
        _compile_body(b.args[1], ctx)
        end = len(ctx.instrs)
        ctx.instrs[jmp_idx] = ("jump", end)
        return

    if isinstance(b, Struct) and b.name == "->" and b.arity == 2:
        cond, then = b.args
        yreg = ctx.new_perm()
        ctx.instrs.append(("get_level", yreg))
        _compile_body(cond, ctx)
        ctx.instrs.append(("cut_to", yreg))
        _compile_body(then, ctx)
        return

    if isinstance(b, Struct) and b.name == "\\+" and b.arity == 1:
        _compile_put_arg(b.args[0], 1, ctx)
        ctx.instrs.append(("call", ("$naf", 1)))
        return

    if isinstance(b, Atom) and b.name == "not":
        ctx.instrs.append(("fail",))
        return
    if isinstance(b, Struct) and b.name == "not" and b.arity == 1:
        _compile_put_arg(b.args[0], 1, ctx)
        ctx.instrs.append(("call", ("$naf", 1)))
        return

    if isinstance(b, (Atom, Struct)) and b.name == "call" and (isinstance(b, Struct)):
        _compile_call(b, ctx)
        return

    _compile_call(b, ctx)
