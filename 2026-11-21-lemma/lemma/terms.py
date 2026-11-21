"""Core terms.

Bound variables are de Bruijn indices (`Var`).  Two extra node kinds exist for the *untrusted*
layers (elaborator / tactics): `Fv` (a free variable carrying its own type, locally-nameless
style) and `Meta` (a tactic metavariable).  The kernel accepts `Fv` (it knows their types) but
never `Meta`; declarations added to the environment must be closed (no `Fv`, no `Meta`).
"""
from itertools import count

_ids = count(1)


class Term:
    __slots__ = ()

    def __eq__(self, other):
        return type(self) is type(other) and self._key() == other._key()

    def __hash__(self):
        return hash((type(self).__name__, self._key()))

    def __repr__(self):
        from .pretty import show
        return show(self)


class Var(Term):
    __slots__ = ("i",)
    def __init__(self, i): self.i = i
    def _key(self): return self.i


class Sort(Term):
    __slots__ = ("n",)
    def __init__(self, n): self.n = n
    def _key(self): return self.n


class Const(Term):
    __slots__ = ("name",)
    def __init__(self, name): self.name = name
    def _key(self): return self.name


class App(Term):
    __slots__ = ("f", "a")
    def __init__(self, f, a): self.f = f; self.a = a
    def _key(self): return (self.f, self.a)


class Pi(Term):
    __slots__ = ("name", "dom", "cod")
    def __init__(self, name, dom, cod): self.name = name; self.dom = dom; self.cod = cod
    def _key(self): return (self.dom, self.cod)          # binder names are irrelevant (α-equivalence)


class Lam(Term):
    __slots__ = ("name", "dom", "body")
    def __init__(self, name, dom, body): self.name = name; self.dom = dom; self.body = body
    def _key(self): return (self.dom, self.body)


class Fv(Term):
    """A free variable.  Identity is the unique `id`; `ty` is its type (a term)."""
    __slots__ = ("id", "name", "ty")
    def __init__(self, name, ty):
        self.id = next(_ids); self.name = name; self.ty = ty
    def _key(self): return self.id


class Meta(Term):
    __slots__ = ("id", "name", "ty")
    def __init__(self, name="?", ty=None):
        self.id = next(_ids); self.name = name; self.ty = ty
    def _key(self): return self.id


class BindF(Term):
    """Deferred binder over an Fv (tactic proof terms): abstracted when the proof is zonked."""
    __slots__ = ("kind", "fv", "body")
    def __init__(self, kind, fv, body): self.kind = kind; self.fv = fv; self.body = body
    def _key(self): return (self.kind, self.fv.id, self.body)


# ---------------------------------------------------------------- helpers

def apps(f, *args):
    for a in args:
        f = App(f, a)
    return f


def unapps(t):
    """t = f a1 .. an  ->  (f, [a1..an])"""
    args = []
    while isinstance(t, App):
        args.append(t.a)
        t = t.f
    args.reverse()
    return t, args


def children_map(t, fn, under):
    """Rebuild `t` applying fn(child, extra_depth) to each direct child."""
    if isinstance(t, App):
        return App(fn(t.f, 0), fn(t.a, 0))
    if isinstance(t, Pi):
        return Pi(t.name, fn(t.dom, 0), fn(t.cod, 1))
    if isinstance(t, Lam):
        return Lam(t.name, fn(t.dom, 0), fn(t.body, 1))
    if isinstance(t, BindF):
        return BindF(t.kind, t.fv, fn(t.body, 0))
    return t


def shift(t, d, cut=0):
    """Add d to every free de Bruijn index >= cut."""
    if d == 0:
        return t
    if isinstance(t, Var):
        return Var(t.i + d) if t.i >= cut else t
    if isinstance(t, (Sort, Const, Fv, Meta)):
        return t
    return children_map(t, lambda c, k: shift(c, d, cut + k), None)


def instantiate(body, arg, depth=0):
    """body[Var(depth) := arg], lowering the indices above it (β-contraction)."""
    if isinstance(body, Var):
        if body.i == depth:
            return shift(arg, depth)
        return Var(body.i - 1) if body.i > depth else body
    if isinstance(body, (Sort, Const, Fv, Meta)):
        return body
    return children_map(body, lambda c, k: instantiate(c, arg, depth + k), None)


def abstract(t, fv, depth=0):
    """Replace free variable `fv` by Var(depth) (closing it under one binder)."""
    if isinstance(t, Fv):
        return Var(depth) if t.id == fv.id else t
    if isinstance(t, (Var, Sort, Const, Meta)):
        return t
    if isinstance(t, BindF):
        return BindF(t.kind, t.fv, abstract(t.body, fv, depth))
    return children_map(t, lambda c, k: abstract(c, fv, depth + k), None)


def subst_fv(t, fv, repl):
    """Replace free variable fv by the term repl (repl must be closed over bound vars)."""
    if isinstance(t, Fv):
        return repl if t.id == fv.id else t
    if isinstance(t, (Var, Sort, Const, Meta)):
        return t
    if isinstance(t, BindF):
        return BindF(t.kind, t.fv, subst_fv(t.body, fv, repl))
    return children_map(t, lambda c, k: subst_fv(c, fv, repl), None)


def bind(kind, fvs, body):
    """Close `body` over the free variables fvs (outermost first) as Π or λ binders."""
    ctor = Pi if kind == "pi" else Lam
    for fv in reversed(fvs):
        body = ctor(fv.name, fv.ty, abstract(body, fv))
    return body


def pi_over(fvs, body):
    return bind("pi", fvs, body)


def lam_over(fvs, body):
    return bind("lam", fvs, body)


def free_fvs(t, acc=None):
    if acc is None:
        acc = {}
    if isinstance(t, Fv):
        if t.id not in acc:
            acc[t.id] = t
            free_fvs(t.ty, acc)
    elif isinstance(t, App):
        free_fvs(t.f, acc); free_fvs(t.a, acc)
    elif isinstance(t, Pi):
        free_fvs(t.dom, acc); free_fvs(t.cod, acc)
    elif isinstance(t, Lam):
        free_fvs(t.dom, acc); free_fvs(t.body, acc)
    elif isinstance(t, BindF):
        free_fvs(t.body, acc)
    return acc


def occurs_fv(t, fv):
    if isinstance(t, Fv):
        return t.id == fv.id
    if isinstance(t, App):
        return occurs_fv(t.f, fv) or occurs_fv(t.a, fv)
    if isinstance(t, Pi):
        return occurs_fv(t.dom, fv) or occurs_fv(t.cod, fv)
    if isinstance(t, Lam):
        return occurs_fv(t.dom, fv) or occurs_fv(t.body, fv)
    if isinstance(t, BindF):
        return occurs_fv(t.body, fv)
    return False


def occurs_const(t, name):
    if isinstance(t, Const):
        return t.name == name
    if isinstance(t, App):
        return occurs_const(t.f, name) or occurs_const(t.a, name)
    if isinstance(t, Pi):
        return occurs_const(t.dom, name) or occurs_const(t.cod, name)
    if isinstance(t, Lam):
        return occurs_const(t.dom, name) or occurs_const(t.body, name)
    return False


def has_meta(t):
    if isinstance(t, Meta):
        return True
    if isinstance(t, App):
        return has_meta(t.f) or has_meta(t.a)
    if isinstance(t, Pi):
        return has_meta(t.dom) or has_meta(t.cod)
    if isinstance(t, Lam):
        return has_meta(t.dom) or has_meta(t.body)
    if isinstance(t, BindF):
        return has_meta(t.body)
    return False


def is_closed(t, depth=0):
    """No loose de Bruijn index, no Fv, no Meta, no BindF."""
    if isinstance(t, Var):
        return t.i < depth
    if isinstance(t, (Fv, Meta, BindF)):
        return False
    if isinstance(t, (Sort, Const)):
        return True
    if isinstance(t, App):
        return is_closed(t.f, depth) and is_closed(t.a, depth)
    if isinstance(t, Pi):
        return is_closed(t.dom, depth) and is_closed(t.cod, depth + 1)
    if isinstance(t, Lam):
        return is_closed(t.dom, depth) and is_closed(t.body, depth + 1)
    return False


def size(t):
    if isinstance(t, App):
        return 1 + size(t.f) + size(t.a)
    if isinstance(t, Pi):
        return 1 + size(t.dom) + size(t.cod)
    if isinstance(t, Lam):
        return 1 + size(t.dom) + size(t.body)
    return 1


def beta(t):
    """Contract β-redexes `(λx. b) a` everywhere (no δ/ι)."""
    if isinstance(t, App):
        f, a = beta(t.f), beta(t.a)
        if isinstance(f, Lam):
            return beta(instantiate(f.body, a))
        return App(f, a)
    if isinstance(t, Pi):
        return Pi(t.name, beta(t.dom), beta(t.cod))
    if isinstance(t, Lam):
        return Lam(t.name, beta(t.dom), beta(t.body))
    return t
