"""The trusted kernel.

Dependent type theory: Π, λ, `Sort n` (n = 0,1,2…, with `Type n` = `Sort n`; Sort n : Sort n+1,
cumulative, predicative), constants (definitions, theorems, axioms, inductive types,
constructors, recursors).  Definitional equality is βδιη, decided by normalisation-by-evaluation.

Soundness-relevant side conditions live here and nowhere else:
  * every declaration is checked (type is a type, value has that type, closed terms only);
  * inductive types: strict positivity, universe bound on constructor fields, parameters uniform;
  * recursors / ι-rules are *generated* from the declaration, never accepted from outside.
"""
from .terms import (Var, Sort, Const, App, Pi, Lam, Fv, Meta, BindF, apps, unapps, instantiate,
                    abstract, pi_over, lam_over, is_closed, occurs_const)

MAX_ELIM = 2            # recursors T.rec (into Type 0), T.rec_1 (Type 1), T.rec_2 (Type 2)


class KernelError(Exception):
    pass


# ------------------------------------------------------------------ values

class VSort:
    __slots__ = ("n",)
    def __init__(self, n): self.n = n


class VPi:
    __slots__ = ("name", "dom", "cod")
    def __init__(self, name, dom, cod): self.name = name; self.dom = dom; self.cod = cod


class VLam:
    __slots__ = ("name", "dom", "body")
    def __init__(self, name, dom, body): self.name = name; self.dom = dom; self.body = body


class VNe:
    """Neutral: head is ('var', level) | ('fv', Fv) | ('const', name) | ('def', name)."""
    __slots__ = ("head", "spine")
    def __init__(self, head, spine=()): self.head = head; self.spine = spine


class Clo:
    __slots__ = ("env", "term")
    def __init__(self, env, term): self.env = env; self.term = term


class Ctx:
    """Typing context for bound variables (the kernel's own binders)."""
    __slots__ = ("env", "types", "names")
    def __init__(self, env=(), types=(), names=()):
        self.env = list(env); self.types = list(types); self.names = list(names)

    @property
    def level(self): return len(self.env)

    def push(self, name, ty):
        v = VNe(("var", self.level))
        return Ctx(self.env + [v], self.types + [ty], self.names + [name]), v


# ------------------------------------------------------------------ declarations

class Decl:
    __slots__ = ("kind", "name", "ty", "val", "info", "_tv", "_vv")
    def __init__(self, kind, name, ty, val=None, info=None):
        self.kind = kind; self.name = name; self.ty = ty; self.val = val; self.info = info
        self._tv = None; self._vv = None


class IndInfo:
    def __init__(self, name, nparams, nindices, level, ctors):
        self.name = name; self.nparams = nparams; self.nindices = nindices
        self.level = level; self.ctors = ctors            # list of ctor names (in order)


class CtorInfo:
    def __init__(self, ind, index, nfields, rec_fields):
        self.ind = ind; self.index = index; self.nfields = nfields
        self.rec_fields = rec_fields                       # per field: bool recursive


class RecInfo:
    def __init__(self, ind, k, nparams, nminors, nindices, rules):
        self.ind = ind; self.k = k; self.nparams = nparams; self.nminors = nminors
        self.nindices = nindices; self.rules = rules       # ctor name -> (rule term, nfields)
        self.arity = nparams + 1 + nminors + nindices + 1


class Kernel:
    def __init__(self):
        self.decls = {}
        self.order = []                                    # declaration names, in order

    # ------------------------------------------------------------ evaluation
    def decl(self, name):
        d = self.decls.get(name)
        if d is None:
            raise KernelError(f"unknown constant '{name}'")
        return d

    def type_value(self, d):
        if d._tv is None:
            d._tv = self.eval([], d.ty)
        return d._tv

    def def_value(self, d):
        if d._vv is None:
            d._vv = self.eval([], d.val)
        return d._vv

    def eval(self, env, t):
        if isinstance(t, Var):
            return env[-1 - t.i]
        if isinstance(t, App):
            return self.vapp(self.eval(env, t.f), self.eval(env, t.a))
        if isinstance(t, Const):
            d = self.decl(t.name)
            if d.kind == "def":
                return self.try_def(("def", t.name), ())
            return VNe(("const", t.name))
        if isinstance(t, Lam):
            return VLam(t.name, self.eval(env, t.dom), Clo(env, t.body))
        if isinstance(t, Pi):
            return VPi(t.name, self.eval(env, t.dom), Clo(env, t.cod))
        if isinstance(t, Sort):
            return VSort(t.n)
        if isinstance(t, Fv):
            return VNe(("fv", t))
        raise KernelError(f"cannot evaluate {type(t).__name__} term (unsolved metavariable or deferred binder?)")

    def apply(self, clo, v):
        return self.eval(clo.env + [v], clo.term)

    def vapp(self, f, a):
        if isinstance(f, VLam):
            return self.apply(f.body, a)
        if isinstance(f, VNe):
            spine = f.spine + (a,)
            h = f.head
            if h[0] == "const":
                d = self.decls[h[1]]
                if d.kind == "rec" and len(spine) == d.info.arity:
                    r = self.iota(d, spine)
                    if r is not None:
                        return r
            elif h[0] == "def":
                return self.try_def(h, spine)
            return VNe(h, spine)
        raise KernelError("applying a non-function value")

    def iota(self, d, spine):
        info = d.info
        major = spine[-1]
        if not (isinstance(major, VNe) and major.head[0] == "const"):
            return None
        cd = self.decls[major.head[1]]
        if cd.kind != "ctor" or cd.info.ind != info.ind:
            return None
        rule, nf = info.rules[cd.name]
        np_ = info.nparams
        if len(major.spine) != np_ + nf:
            return None
        args = list(spine[:np_ + 1 + info.nminors]) + list(major.spine[np_:])
        v = self.rule_value(d, cd.name, rule)
        for a in args:
            v = self.vapp(v, a)
        return v

    def rule_value(self, d, cname, rule):
        cache = d.val
        if cname not in cache:
            cache[cname] = self.eval([], rule)
        return cache[cname]

    def try_def(self, head, spine):
        """Smart unfolding: a definition unfolds unless that would leave a stuck recursor
        (or a bare λ for a partial application) — keeps goals readable (`add k n` stays `add k n`)."""
        d = self.decls[head[1]]
        r = self.def_value(d)
        for a in spine:
            r = self.vapp(r, a)
        if isinstance(r, VLam):
            return VNe(head, spine)
        if isinstance(r, VNe):
            if r.head[0] == "const" and self.decls[r.head[1]].kind == "rec":
                return VNe(head, spine)
        return r

    def force(self, v):
        """Unfold a folded definition head all the way."""
        while isinstance(v, VNe) and v.head[0] == "def":
            d = self.decls[v.head[1]]
            r = self.def_value(d)
            for a in v.spine:
                r = self.vapp(r, a)
            if isinstance(r, VNe) and r.head == v.head and len(r.spine) == len(v.spine):
                return v
            v = r
        return v

    # ------------------------------------------------------------ quoting
    def quote(self, lvl, v):
        if isinstance(v, VNe):
            h = v.head
            if h[0] == "var":
                t = Var(lvl - 1 - h[1])
            elif h[0] == "fv":
                t = h[1]
            else:
                t = Const(h[1])
            for a in v.spine:
                t = App(t, self.quote(lvl, a))
            return t
        if isinstance(v, VSort):
            return Sort(v.n)
        fresh = VNe(("var", lvl))
        if isinstance(v, VPi):
            return Pi(v.name, self.quote(lvl, v.dom), self.quote(lvl + 1, self.apply(v.cod, fresh)))
        if isinstance(v, VLam):
            return Lam(v.name, self.quote(lvl, v.dom), self.quote(lvl + 1, self.apply(v.body, fresh)))
        raise KernelError("cannot quote value")

    # ------------------------------------------------------------ conversion
    def conv(self, lvl, a, b):
        if a is b:
            return True
        if isinstance(a, VSort) and isinstance(b, VSort):
            return a.n == b.n
        if isinstance(a, VPi) and isinstance(b, VPi):
            if not self.conv(lvl, a.dom, b.dom):
                return False
            f = VNe(("var", lvl))
            return self.conv(lvl + 1, self.apply(a.cod, f), self.apply(b.cod, f))
        if isinstance(a, VLam) and isinstance(b, VLam):
            f = VNe(("var", lvl))
            return self.conv(lvl + 1, self.apply(a.body, f), self.apply(b.body, f))
        if isinstance(a, VLam):                                   # η
            f = VNe(("var", lvl))
            return self.conv(lvl + 1, self.apply(a.body, f), self.vapp(b, f))
        if isinstance(b, VLam):
            f = VNe(("var", lvl))
            return self.conv(lvl + 1, self.vapp(a, f), self.apply(b.body, f))
        if isinstance(a, VNe) and isinstance(b, VNe):
            if a.head == b.head and len(a.spine) == len(b.spine) and all(
                    self.conv(lvl, x, y) for x, y in zip(a.spine, b.spine)):
                return True
            if a.head[0] == "def" or b.head[0] == "def":
                fa, fb = self.force(a), self.force(b)
                if fa is a and fb is b:
                    return False
                return self.conv(lvl, fa, fb)
            return False
        return False

    def subtype(self, lvl, a, b):
        if isinstance(a, VSort) and isinstance(b, VSort):
            return a.n <= b.n
        if isinstance(a, VPi) and isinstance(b, VPi):
            if not self.conv(lvl, a.dom, b.dom):
                return False
            f = VNe(("var", lvl))
            return self.subtype(lvl + 1, self.apply(a.cod, f), self.apply(b.cod, f))
        return self.conv(lvl, a, b)

    # ------------------------------------------------------------ type checking
    def infer(self, ctx, t):
        if isinstance(t, Var):
            if t.i >= ctx.level:
                raise KernelError("loose bound variable")
            return ctx.types[-1 - t.i]
        if isinstance(t, Sort):
            return VSort(t.n + 1)
        if isinstance(t, Const):
            return self.type_value(self.decl(t.name))
        if isinstance(t, Fv):
            return self.eval([], t.ty)
        if isinstance(t, Pi):
            s1 = self.sort_of(ctx, t.dom)
            dv = self.eval(ctx.env, t.dom)
            ctx2, _ = ctx.push(t.name, dv)
            s2 = self.sort_of(ctx2, t.cod)
            return VSort(max(s1, s2))
        if isinstance(t, Lam):
            self.sort_of(ctx, t.dom)
            dv = self.eval(ctx.env, t.dom)
            ctx2, _ = ctx.push(t.name, dv)
            bt = self.infer(ctx2, t.body)
            return VPi(t.name, dv, Clo(list(ctx.env), self.quote(ctx2.level, bt)))
        if isinstance(t, App):
            ft = self.infer(ctx, t.f)
            if not isinstance(ft, VPi):
                ft = self.force(ft)
            if not isinstance(ft, VPi):
                raise KernelError(f"cannot apply: '{self.show(ctx, t.f)}' has type "
                                  f"'{self.show_v(ctx, ft)}', which is not a function type")
            self.check(ctx, t.a, ft.dom, what=lambda: f"argument of '{self.show(ctx, t.f)}'")
            return self.apply(ft.cod, self.eval(ctx.env, t.a))
        raise KernelError(f"cannot type-check a {type(t).__name__} node")

    def check(self, ctx, t, ty, what=None):
        got = self.infer(ctx, t)
        if not self.subtype(ctx.level, got, ty):
            ctxt = f" ({what()})" if what else ""
            raise KernelError(f"type mismatch{ctxt}:\n  term     {self.show(ctx, t)}\n"
                              f"  has type {self.show_v(ctx, got)}\n  but expected {self.show_v(ctx, ty)}")

    def sort_of(self, ctx, t):
        ty = self.infer(ctx, t)
        if not isinstance(ty, VSort):
            ty = self.force(ty)
        if not isinstance(ty, VSort):
            raise KernelError(f"'{self.show(ctx, t)}' is not a type (it has type '{self.show_v(ctx, ty)}')")
        return ty.n

    def show(self, ctx, t):
        from .pretty import show
        return show(t, list(ctx.names), self)

    def show_v(self, ctx, v):
        return self.show(ctx, self.quote(ctx.level, v))

    # ------------------------------------------------------------ public term API (closed over Fvs)
    def infer_term(self, t):
        return self.quote(0, self.infer(Ctx(), t))

    def normalize(self, t):
        return self.quote(0, self.eval([], t))

    def whnf_term(self, t):
        return self.quote(0, self.force(self.eval([], t)))

    def def_eq(self, a, b):
        return self.conv(0, self.eval([], a), self.eval([], b))

    def sort_level(self, ty):
        """`ty` must be a type; return the n with ty : Sort n."""
        return self.sort_of(Ctx(), ty)

    def check_term(self, t, ty):
        self.check(Ctx(), t, self.eval([], ty))

    # ------------------------------------------------------------ adding declarations
    def _fresh(self, name):
        if name in self.decls:
            raise KernelError(f"'{name}' is already declared")

    def _check_closed(self, t, what):
        if not is_closed(t):
            raise KernelError(f"{what} is not closed (contains free variables or metavariables)")

    def _add(self, d):
        self.decls[d.name] = d
        self.order.append(d.name)

    def add_axiom(self, name, ty):
        self._fresh(name)
        self._check_closed(ty, "type")
        self.sort_of(Ctx(), ty)
        self._add(Decl("axiom", name, ty))

    def add_def(self, name, ty, val, opaque=False):
        self._fresh(name)
        self._check_closed(ty, "type")
        self._check_closed(val, "value")
        self.sort_of(Ctx(), ty)
        self.check(Ctx(), val, self.eval([], ty))
        self._add(Decl("theorem" if opaque else "def", name, ty, val))

    # ------------------------------------------------------------ inductive families
    def add_inductive(self, name, ty, nparams, ctors):
        """ty: closed `Π params. Π indices. Sort u`; ctors: [(cname, closed type)]."""
        self._fresh(name)
        cnames = [c for c, _ in ctors]
        if len(set(cnames)) != len(cnames):
            raise KernelError("duplicate constructor names")
        for c in cnames:
            self._fresh(c)
            if c == name or c in (name + ".rec",) or any(c == f"{name}.rec_{k}" for k in range(1, MAX_ELIM + 1)):
                raise KernelError(f"constructor name '{c}' clashes")
        self._check_closed(ty, "inductive type")
        self.sort_of(Ctx(), ty)
        snapshot = (dict(self.decls), list(self.order))
        try:
            self._add_inductive(name, ty, nparams, ctors)
        except Exception:
            self.decls, self.order = snapshot
            raise

    def _peel(self, t, n, prefix):
        """Peel up to n (or all, n=None) Π binders from t, instantiating with fresh Fvs."""
        fvs = []
        while isinstance(t, Pi) and (n is None or len(fvs) < n):
            fv = Fv(t.name if t.name and t.name != "_" else f"{prefix}{len(fvs)}", t.dom)
            fvs.append(fv)
            t = instantiate(t.cod, fv)
        return fvs, t

    def _add_inductive(self, name, ty, nparams, ctors):
        P, rest = self._peel(ty, nparams, "p")
        if len(P) != nparams:
            raise KernelError(f"'{name}' declares {nparams} parameters but its type has fewer binders")
        IDX, srt = self._peel(rest, None, "i")
        if not isinstance(srt, Sort):
            raise KernelError(f"the type of '{name}' must end in a universe (Type n), not '{self.show(Ctx(), srt)}'")
        u = srt.n
        ni = len(IDX)
        self._add(Decl("ind", name, ty, info=IndInfo(name, nparams, ni, u, [c for c, _ in ctors])))
        I = Const(name)

        # ---- analyse constructors
        cinfo = []                      # (cname, ctype, fields[(Fv, rec or None)], result idx args)
        for ci, (cname, cty) in enumerate(ctors):
            self._check_closed(cty, f"type of constructor '{cname}'")
            self.sort_of(Ctx(), cty)
            t = cty
            for pf in P:                                      # instantiate parameters with our Fvs
                if not isinstance(t, Pi):
                    raise KernelError(f"constructor '{cname}' must take the {nparams} parameter(s) of '{name}' first")
                if not self.def_eq(t.dom, pf.ty):
                    raise KernelError(f"constructor '{cname}': parameter '{t.name}' does not match the type's parameter")
                t = instantiate(t.cod, pf)
            fields = []
            while isinstance(t, Pi):
                hd0 = unapps(t.dom)[0]
                guess = hd0.name[0].lower() if isinstance(hd0, Const) and hd0.name[:1].isalpha() else "a"
                fv = Fv(t.name if t.name and t.name != "_" else guess, t.dom)
                xs, c = self._peel(t.dom, None, "x")
                h, args = unapps(c)
                rec = None
                if isinstance(h, Const) and h.name == name:
                    if len(args) != nparams + ni:
                        raise KernelError(f"constructor '{cname}': '{name}' applied to the wrong number of arguments in field '{fv.name}'")
                    for a, pf in zip(args[:nparams], P):
                        if not (isinstance(a, Fv) and a.id == pf.id):
                            raise KernelError(f"constructor '{cname}': recursive occurrence must use the parameters unchanged (uniform parameters)")
                    idx_args = args[nparams:]
                    if any(occurs_const(x.ty, name) for x in xs) or any(occurs_const(a, name) for a in idx_args):
                        raise KernelError(f"constructor '{cname}': field '{fv.name}' is not strictly positive ('{name}' occurs to the left of an arrow)")
                    rec = (xs, idx_args)
                    for x in xs:                              # universe of the telescope
                        if self.sort_level(x.ty) > u:
                            raise KernelError(f"constructor '{cname}': field '{fv.name}' lives in a universe above Type {u}")
                elif occurs_const(t.dom, name):
                    raise KernelError(f"constructor '{cname}': field '{fv.name}' mentions '{name}' in a non-strictly-positive position")
                else:
                    if self.sort_level(t.dom) > u:
                        raise KernelError(f"constructor '{cname}': field '{fv.name}' has type in Type {self.sort_level(t.dom)}, "
                                          f"but '{name}' only lives in Type {u} (universe too small)")
                fields.append((fv, rec))
                t = instantiate(t.cod, fv)
            h, args = unapps(t)
            if not (isinstance(h, Const) and h.name == name and len(args) == nparams + ni):
                raise KernelError(f"constructor '{cname}' must return '{name}' applied to its {nparams + ni} arguments, not '{self.show(Ctx(), t)}'")
            for a, pf in zip(args[:nparams], P):
                if not (isinstance(a, Fv) and a.id == pf.id):
                    raise KernelError(f"constructor '{cname}': result must use the parameters unchanged")
            ridx = args[nparams:]
            if any(occurs_const(a, name) for a in ridx):
                raise KernelError(f"constructor '{cname}': result indices may not mention '{name}'")
            cinfo.append((cname, cty, fields, ridx))

        # ---- register constructors
        for i, (cname, cty, fields, _) in enumerate(cinfo):
            self._add(Decl("ctor", cname, cty, info=CtorInfo(name, i, len(fields), [r is not None for _, r in fields])))

        # ---- generate recursors
        def app_I(idx):
            return apps(I, *P, *idx)

        for k in range(0, MAX_ELIM + 1):
            rname = name + (".rec" if k == 0 else f".rec_{k}")
            idxm, _ = self._peel(self._inst_params(ty, P), None, "i")
            tm = Fv("t", app_I(idxm))
            M = Fv("motive", pi_over(idxm + [tm], Sort(k)))
            minors, rules_data = [], []
            for cname, cty, fields, ridx in cinfo:
                F = [f for f, _ in fields]
                ihs = []
                for f, rec in fields:
                    if rec is not None:
                        xs, ia = rec
                        ihs.append((f, xs, ia, Fv(f.name + "_ih", pi_over(xs, apps(M, *ia, apps(f, *xs))))))
                c_app = apps(Const(cname), *P, *F)
                mty = pi_over(F + [ih[3] for ih in ihs], apps(M, *ridx, c_app))
                mv = Fv("m_" + cname, mty)
                minors.append(mv)
                rules_data.append((cname, F, ihs, mv))
            IDX2, _ = self._peel(self._inst_params(ty, P), None, "i")
            t = Fv("t", app_I(IDX2))
            rty = pi_over(P + [M] + minors + IDX2 + [t], apps(M, *IDX2, t))
            rules = {}
            for cname, F, ihs, mv in rules_data:
                ihterms = []
                for f, xs, ia, _ in ihs:
                    ihterms.append(lam_over(xs, apps(Const(rname), *P, M, *minors, *ia, apps(f, *xs))))
                body = apps(mv, *F, *ihterms)
                rules[cname] = (lam_over(P + [M] + minors + F, body), len(F))
            # the recursor must be registered before its own rules are evaluated/checked
            self._add(Decl("rec", rname, rty, val={}, info=RecInfo(name, k, nparams, len(cinfo), ni, rules)))
        # sanity: generated recursor types must themselves type-check
        for k in range(0, MAX_ELIM + 1):
            rname = name + (".rec" if k == 0 else f".rec_{k}")
            self.sort_of(Ctx(), self.decls[rname].ty)

    def _inst_params(self, ty, P):
        t = ty
        for pf in P:
            t = instantiate(t.cod, pf)
        return t
