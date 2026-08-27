"""The WAM's tagged heap: a term graph, not a value store.

Cells (each a small tuple, stored in a flat Python list = the heap):
  ('REF', i)        reference cell; unbound iff it points at its own index
  ('STR', i)        structure pointer -> a FUN cell at heap index i
  ('FUN', name, ar) functor header; the ar argument cells follow immediately
  ('CON', value)    an atomic constant (a terms.Atom or terms.Num object)

This is the classic WAM heap layout (Aït-Kaci's tutorial reconstruction):
a bound variable is a REF cell pointing *through* to its value, so
dereferencing is chasing REF chains, and a structure's arguments sit
contiguously in memory right after its functor cell.
"""
from .terms import Atom, Num, Var, Struct, deref as term_deref

REF, STR, FUN, CON = "REF", "STR", "FUN", "CON"


class Cell:
    __slots__ = ("tag", "a", "b")

    def __init__(self, tag, a, b=None):
        self.tag = tag
        self.a = a
        self.b = b

    def __repr__(self):
        return f"Cell({self.tag},{self.a},{self.b})"


def new_ref(heap):
    i = len(heap)
    heap.append(Cell(REF, i))
    return i


def heap_deref(heap, addr):
    while True:
        c = heap[addr]
        if c.tag == REF and c.a != addr:
            addr = c.a
            continue
        return addr


def heap_bind(heap, trail, addr, target_addr):
    """Bind the unbound REF cell at addr to point at target_addr."""
    heap[addr] = Cell(REF, target_addr)
    trail.append(addr)


def heap_unify(heap, trail, a1, a2):
    """Unify two heap addresses (already-created cells). Real WAM
    unification: dereference both sides, bind if either is an unbound
    variable, else compare structurally, recursing into arguments."""
    a1, a2 = heap_deref(heap, a1), heap_deref(heap, a2)
    if a1 == a2:
        return True
    c1, c2 = heap[a1], heap[a2]
    if c1.tag == REF:
        heap_bind(heap, trail, a1, a2)
        return True
    if c2.tag == REF:
        heap_bind(heap, trail, a2, a1)
        return True
    if c1.tag == CON and c2.tag == CON:
        v1, v2 = c1.a, c2.a
        if isinstance(v1, Num) and isinstance(v2, Num):
            return v1.value == v2.value and isinstance(v1.value, int) == isinstance(v2.value, int)
        if isinstance(v1, Atom) and isinstance(v2, Atom):
            return v1.name == v2.name
        return False
    if c1.tag == STR and c2.tag == STR:
        f1, f2 = heap[c1.a], heap[c2.a]
        if f1.a != f2.a or f1.b != f2.b:
            return False
        for k in range(f1.b):
            if not heap_unify(heap, trail, c1.a + 1 + k, c2.a + 1 + k):
                return False
        return True
    return False


def heap_undo_to(heap, trail, mark):
    while len(trail) > mark:
        addr = trail.pop()
        heap[addr] = Cell(REF, addr)


# ---- bridging: Term (parser/golden representation) <-> heap ----------

def push_term(heap, term, varmap):
    """Push a Term (Atom/Num/Struct/Var) onto the heap, returning its
    address. varmap: dict[id(Var)] -> heap address, so repeated
    occurrences of the same Var share one heap cell (as real compiled
    code would via register reuse, but this path is used for the
    simpler cases: loading query terms and rebinding builtin results)."""
    t = term_deref(term)
    if isinstance(t, Var):
        addr = varmap.get(id(t))
        if addr is None:
            addr = new_ref(heap)
            varmap[id(t)] = addr
        return addr
    if isinstance(t, (Atom, Num)):
        heap.append(Cell(CON, t))
        return len(heap) - 1
    if isinstance(t, Struct):
        return _push_struct_contig(heap, t, varmap)
    raise TypeError(f"unknown term type {t!r}")


def _push_struct_contig(heap, t, varmap):
    # Lay down FUN followed immediately by `arity` fresh REF slots (so
    # args sit contiguously in memory, as real WAM structures require),
    # then unify each slot with the (possibly newly pushed) real argument.
    fun_addr = len(heap)
    heap.append(Cell(FUN, t.name, len(t.args)))
    base = len(heap)
    for _ in t.args:
        heap.append(Cell(REF, 0))
    for k in range(len(t.args)):
        heap[base + k] = Cell(REF, base + k)
    str_addr = len(heap)
    heap.append(Cell(STR, fun_addr))
    trail = []
    for k, arg in enumerate(t.args):
        aaddr = push_term(heap, arg, varmap)
        heap_unify(heap, trail, base + k, aaddr)
    return str_addr


def reify(heap, addr, cache=None):
    """Walk a heap address back into a Term (Var/Atom/Num/Struct),
    preserving sharing of unbound variables encountered more than once
    in a single call via `cache` (dict[addr] -> Var)."""
    if cache is None:
        cache = {}
    addr = heap_deref(heap, addr)
    c = heap[addr]
    if c.tag == REF:
        v = cache.get(addr)
        if v is None:
            v = Var(f"_H{addr}")
            cache[addr] = v
        return v
    if c.tag == CON:
        return c.a
    if c.tag == STR:
        fun = heap[c.a]
        args = tuple(reify(heap, c.a + 1 + k, cache) for k in range(fun.b))
        return Struct(fun.a, args)
    raise TypeError(f"cannot reify cell {c!r}")


def unify_heap_with_term(heap, trail, addr, term, cache=None):
    """Unify heap[addr] against a Python Term (which may itself contain
    Vars, some possibly already bound from prior work in this call).
    Any *new* heap bindings are trailed on `trail` (the real WAM trail,
    so they're undoable via heap_undo_to). Vars appearing inside `term`
    that are still unbound after this just stay unbound (no constraint)."""
    if cache is None:
        cache = {}
    addr = heap_deref(heap, addr)
    t = term_deref(term)
    if isinstance(t, Var):
        key = id(t)
        if key in cache:
            return heap_unify(heap, trail, addr, cache[key])
        cache[key] = addr
        return True
    c = heap[addr]
    if c.tag == REF:
        new_addr = push_term_cached(heap, t, cache)
        heap_bind(heap, trail, addr, new_addr)
        return True
    if isinstance(t, (Atom, Num)):
        if c.tag != CON:
            return False
        v = c.a
        if isinstance(v, Num) and isinstance(t, Num):
            return v.value == t.value and isinstance(v.value, int) == isinstance(t.value, int)
        if isinstance(v, Atom) and isinstance(t, Atom):
            return v.name == t.name
        return False
    if isinstance(t, Struct):
        if c.tag != STR:
            return False
        fun = heap[c.a]
        if fun.a != t.name or fun.b != len(t.args):
            return False
        for k, arg in enumerate(t.args):
            if not unify_heap_with_term(heap, trail, c.a + 1 + k, arg, cache):
                return False
        return True
    return False


def push_term_cached(heap, term, cache):
    """Like push_term but cache maps id(Var) -> heap addr directly
    (shared with unify_heap_with_term's cache)."""
    t = term_deref(term)
    if isinstance(t, Var):
        key = id(t)
        addr = cache.get(key)
        if addr is None:
            addr = new_ref(heap)
            cache[key] = addr
        return addr
    if isinstance(t, (Atom, Num)):
        heap.append(Cell(CON, t))
        return len(heap) - 1
    fun_addr = len(heap)
    heap.append(Cell(FUN, t.name, len(t.args)))
    base = len(heap)
    for _ in t.args:
        heap.append(Cell(REF, 0))
    for k in range(len(t.args)):
        heap[base + k] = Cell(REF, base + k)
    str_addr = len(heap)
    heap.append(Cell(STR, fun_addr))
    trail_tmp = []
    for k, arg in enumerate(t.args):
        aaddr = push_term_cached(heap, arg, cache)
        heap_unify(heap, trail_tmp, base + k, aaddr)
    return str_addr
