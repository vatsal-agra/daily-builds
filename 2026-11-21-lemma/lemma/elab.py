"""Elaborator: surface syntax (named binders) -> kernel terms, plus the command driver.

Untrusted by design: whatever it produces is re-checked by the kernel before being admitted.
Locally nameless: binders become `Fv`s while elaborating and are abstracted afterwards.
"""
import difflib
from .terms import (Var, Sort, Const, App, Pi, Lam, Fv, apps, unapps, instantiate, pi_over, lam_over,
                    subst_fv, occurs_const, size)
from .kernel import Kernel, KernelError, Ctx, VPi, VSort, VNe, VLam, MAX_ELIM
from .pretty import Notation, show
from .syntax import *


class RecCtx:
    """State for structural recursion while elaborating one definition."""
    def __init__(self, fname, params, result):
        self.fname = fname
        self.params = params          # Fvs of the definition's parameters, in order
        self.result = result          # result type term T
        self.top_done = False
        self.equations = []           # (ctor, fields, rfvs, c_app, body_pre)
        self.generalised = False


class Elaborator:
    def __init__(self, kernel, notation):
        self.k = kernel
        self.nota = notation
        self.rec = None

    # ------------------------------------------------------------ helpers
    def sv(self, v):
        return show(self.k.quote(0, v), [], self.k)

    def st(self, t):
        return show(t, [], self.k)

    def err(self, msg, s=None):
        raise LemmaError(msg, getattr(s, "pos", None))

    def tyval(self, t):
        return self.k.eval([], t)

    def whnf(self, v):
        return self.k.force(v)

    def kcheck(self, fn, s):
        try:
            return fn()
        except KernelError as e:
            raise LemmaError(str(e), getattr(s, "pos", None))

    def entry(self, fv):
        return (fv, self.k.eval([], fv.ty))

    def extend(self, scope, name, fv):
        if name == "_":
            return scope
        d = dict(scope)
        d[name] = self.entry(fv)
        return d

    # ------------------------------------------------------------ types
    def elab_type(self, s, scope):
        t, ty = self.infer(s, scope)
        ty = self.whnf(ty)
        if not isinstance(ty, VSort):
            self.err(f"expected a type, but '{self.st(t)}' has type '{self.sv(ty)}'", s)
        return t

    # ------------------------------------------------------------ inference
    def infer(self, s, scope):
        if isinstance(s, SVar):
            if s.name in scope:
                return scope[s.name]
            if s.name in self.k.decls:
                d = self.k.decls[s.name]
                return Const(s.name), self.k.type_value(d)
            if s.name == "_":
                self.err("holes ('_') are not supported here", s)
            cands = list(scope) + list(self.k.decls)
            close = difflib.get_close_matches(s.name, cands, n=3, cutoff=0.6)
            hint = f" (did you mean {', '.join(repr(c) for c in close)}?)" if close else ""
            self.err(f"unknown identifier '{s.name}'{hint}", s)
        if isinstance(s, SNum):
            if "zero" not in self.k.decls or "succ" not in self.k.decls:
                self.err("numerals need constructors 'zero' and 'succ' (define Nat first)", s)
            t = Const("zero")
            for _ in range(s.n):
                t = App(Const("succ"), t)
            return t, self.k.type_value(self.k.decls["zero"])
        if isinstance(s, SSort):
            return Sort(s.n), VSort(s.n + 1)
        if isinstance(s, SAnn):
            ty = self.elab_type(s.ty, scope)
            tv = self.tyval(ty)
            return self.check(s.t, scope, tv), tv
        if isinstance(s, SApp):
            return self.infer_app(s, scope)
        if isinstance(s, SArrow):
            a = self.elab_type(s.a, scope)
            b = self.elab_type(s.b, scope)
            t = Pi("_", a, b)
            return t, self.kcheck(lambda: self.k.infer(Ctx(), t), s)
        if isinstance(s, SPi):
            fvs, sc = [], scope
            for name, ann in s.binders:
                dom = self.elab_type(ann, sc)
                fv = Fv(name, dom)
                fvs.append(fv)
                sc = self.extend(sc, name, fv)
            body = self.elab_type(s.body, sc)
            t = pi_over(fvs, body)
            return t, self.kcheck(lambda: self.k.infer(Ctx(), t), s)
        if isinstance(s, SLam):
            fvs, sc = [], scope
            for name, ann in s.binders:
                if ann is None:
                    self.err(f"cannot infer the type of '{name}' here; annotate it as '({name} : T)'", s)
                dom = self.elab_type(ann, sc)
                fv = Fv(name, dom)
                fvs.append(fv)
                sc = self.extend(sc, name, fv)
            body, bty = self.infer(s.body, sc)
            t = lam_over(fvs, body)
            return t, self.tyval(pi_over(fvs, self.k.quote(0, bty)))
        if isinstance(s, SLet):
            if s.ty is not None:
                ty = self.elab_type(s.ty, scope)
                tv = self.tyval(ty)
                val = self.check(s.val, scope, tv)
            else:
                val, tv = self.infer(s.val, scope)
            sc = dict(scope)
            sc[s.name] = (val, tv)           # `let` is a macro: the value is substituted
            return self.infer(s.body, sc)
        if isinstance(s, SEq):
            if "Eq" not in self.k.decls:
                self.err("'=' needs the inductive type 'Eq' (load the prelude)", s)
            l, lt = self.infer(s.l, scope)
            r = self.check(s.r, scope, lt)
            A = self.k.quote(0, lt)
            t = apps(Const("Eq"), A, l, r)
            return t, self.kcheck(lambda: self.k.infer(Ctx(), t), s)
        if isinstance(s, SElim):
            return self.elab_elim(s, scope, None)
        if isinstance(s, SBinderGroup):
            self.err("unexpected binder group", s)
        self.err(f"cannot elaborate {type(s).__name__}", s)

    def infer_app(self, s, scope):
        args = []
        h = s
        while isinstance(h, SApp):
            args.append(h.a)
            h = h.f
        args.reverse()
        f, fty = self.infer(h, scope)
        hname = h.name if isinstance(h, SVar) else "the function"
        for i, a in enumerate(args):
            fty = self.whnf(fty)
            if not isinstance(fty, VPi):
                self.err(f"'{hname}' is applied to too many arguments ({len(args)} given, it takes {i}); "
                         f"after {i} argument(s) it has type '{self.sv(fty)}', which is not a function", a)
            at = self.check(a, scope, fty.dom, what=f"argument {i + 1} of '{hname}'")
            f = App(f, at)
            fty = self.k.apply(fty.cod, self.tyval(at))
        return f, fty

    # ------------------------------------------------------------ checking
    def check(self, s, scope, expected, what=None):
        if isinstance(s, SLam):
            return self.check_lam(s, scope, expected)
        if isinstance(s, SElim):
            t, _ = self.elab_elim(s, scope, expected)
            return t
        if isinstance(s, SLet):
            if s.ty is not None:
                ty = self.elab_type(s.ty, scope)
                tv = self.tyval(ty)
                val = self.check(s.val, scope, tv)
            else:
                val, tv = self.infer(s.val, scope)
            sc = dict(scope)
            sc[s.name] = (val, tv)
            return self.check(s.body, sc, expected, what)
        t, ty = self.infer(s, scope)
        if not self.k.subtype(0, ty, expected):
            ctx = f" ({what})" if what else ""
            self.err(f"type mismatch{ctx}\n  expected: {self.sv(expected)}\n  but got:  {self.sv(ty)}"
                     f"\n  for term: {self.st(t)}", s)
        return t

    def check_lam(self, s, scope, expected):
        fvs, sc = [], scope
        cur = expected
        for name, ann in s.binders:
            cur = self.whnf(cur)
            if not isinstance(cur, VPi):
                self.err(f"too many parameters in 'fun': the expected type '{self.sv(cur)}' is not a function type", s)
            if ann is not None:
                dom = self.elab_type(ann, sc)
                if not self.k.conv(0, self.tyval(dom), cur.dom):
                    self.err(f"binder '{name}' is annotated {self.st(dom)}, but the expected parameter type is {self.sv(cur.dom)}", s)
            else:
                dom = self.k.quote(0, cur.dom)
            fv = Fv(name, dom)
            fvs.append(fv)
            sc = self.extend(sc, name, fv)
            cur = self.k.apply(cur.cod, VNe(("fv", fv)))
        body = self.check(s.body, sc, cur)
        return lam_over(fvs, body)

    # ------------------------------------------------------------ elim
    def elab_elim(self, s, scope, expected):
        k = self.k
        tm, tv = self.infer(s.scrut, scope)
        tv = self.whnf(tv)
        if not (isinstance(tv, VNe) and tv.head[0] == "const" and k.decls[tv.head[1]].kind == "ind"):
            self.err(f"cannot eliminate '{self.st(tm)}': its type '{self.sv(tv)}' is not an inductive type", s.scrut)
        ind = k.decls[tv.head[1]]
        info = ind.info
        args = [k.quote(0, a) for a in tv.spine]
        P, IDX = args[:info.nparams], args[info.nparams:]
        I = Const(ind.name)
        ity = ind.ty
        for p in P:
            ity = instantiate(ity.cod, p)

        def fresh_idx():
            out, t = [], ity
            while isinstance(t, Pi):
                fv = Fv(t.name if t.name != "_" else "i", t.dom)
                out.append(fv)
                t = instantiate(t.cod, fv)
            return out

        rec = self.rec
        gen_R, p_index = [], None
        if rec is not None and isinstance(tm, Fv) and any(tm.id == q.id for q in rec.params):
            p_index = [q.id for q in rec.params].index(tm.id)
            gen_R = rec.params[p_index + 1:]
        if s.motive is not None:
            M, mty = self.infer(s.motive, scope)
            t = k.quote(0, mty)
            while isinstance(t, Pi):
                t = t.cod
            if not isinstance(t, Sort):
                self.err("the 'return' motive must be a function ending in a type, e.g. fun n => Nat", s.motive)
            level = t.n
            res_ty = None
        else:
            if expected is None:
                self.err("cannot infer the result type of 'elim' here; annotate it, e.g. (elim … : T) or "
                         "write 'elim x return (fun x => T) with …'", s)
            E = k.quote(0, expected)
            level = self.kcheck(lambda: k.sort_level(E), s)
            idxf = fresh_idx()
            tf = Fv("t", apps(I, *P, *idxf))
            body = E
            if gen_R:
                body = pi_over(gen_R, body)
            if isinstance(tm, Fv):
                body = subst_fv(body, tm, tf)
            for it, iv in zip(IDX, idxf):
                if isinstance(it, Fv):
                    body = subst_fv(body, it, iv)
            M = lam_over(idxf + [tf], body)
            res_ty = expected
        if level > MAX_ELIM:
            self.err(f"elimination into Type {level} is not supported (max Type {MAX_ELIM})", s)
        rname = ind.name + (".rec" if level == 0 else f".rec_{level}")
        rdecl = k.decls[rname]
        # minor-premise telescope straight from the generated recursor type
        v = k.type_value(rdecl)
        for p in P:
            v = k.apply(v.cod, self.tyval(p))
        v = k.apply(v.cod, self.tyval(M))
        by_ctor = {}
        for b in s.branches:
            if b[0] not in info.ctors:
                self.err(f"'{b[0]}' is not a constructor of '{ind.name}' (constructors: {', '.join(info.ctors)})", None if len(b) < 4 else _P(b[3]))
            if b[0] in by_ctor:
                self.err(f"duplicate branch for constructor '{b[0]}'", _P(b[3]))
            by_ctor[b[0]] = b
        missing = [c for c in info.ctors if c not in by_ctor]
        if missing:
            self.err(f"non-exhaustive 'elim': missing branch for constructor(s) {', '.join(missing)}", s)
        top = (rec is not None and p_index is not None and not rec.top_done and expected is not None
               and k.quote(0, expected) == rec.result)
        if top:
            rec.top_done = True
        minors = []
        for cname in info.ctors:
            cd = k.decls[cname]
            minor = self.elab_branch(by_ctor[cname], cd, v.dom, scope, gen_R, p_index, tm, P, top)
            minors.append(minor)
            v = k.apply(v.cod, self.tyval(minor))
        result = apps(Const(rname), *P, M, *minors, *IDX, tm, *gen_R)
        if res_ty is None:
            mv = self.tyval(M)
            for ix in IDX + [tm]:
                mv = k.vapp(mv, self.tyval(ix))
            for r in gen_R:
                mv = k.apply(mv.cod, self.tyval(r))
            res_ty = mv
        return result, res_ty

    def elab_branch(self, branch, cd, mdom, scope, gen_R, p_index, scrut_tm, P, top):
        cname, names, body, bpos = branch
        k = self.k
        nf = cd.info.nfields
        nrec = sum(cd.info.rec_fields)
        if len(names) != nf + nrec:
            desc = f"{nf} field(s)" + (f" and {nrec} inductive hypothesis(es)" if nrec else "")
            self.err(f"constructor '{cname}' has {desc}, so its branch must bind {nf + nrec} name(s) "
                     f"(use '_' to ignore one); {len(names)} given", _P(bpos))
        cur = mdom
        fvs, sc = [], scope
        for name in names:
            cur = self.whnf(cur)
            fv = Fv(name, k.quote(0, cur.dom))
            fvs.append(fv)
            sc = self.extend(sc, name, fv)
            cur = k.apply(cur.cod, VNe(("fv", fv)))
        fields, ihs = fvs[:nf], fvs[nf:]
        rfvs = []
        if gen_R:
            for r in gen_R:
                cur = self.whnf(cur)
                fv = Fv(r.name, k.quote(0, cur.dom))
                rfvs.append(fv)
                sc = self.extend(sc, r.name, fv)
                cur = k.apply(cur.cod, VNe(("fv", fv)))
        body_t = self.check(body, sc, cur)
        if self.rec is not None and p_index is not None:
            rec_fields = [f for f, isr in zip(fields, cd.info.rec_fields) if isr]
            fmap = {f.id: ih for f, ih in zip(rec_fields, ihs)}
            replaced = self.replace_calls(body_t, p_index, fmap)
            if top:
                c_app = apps(Const(cname), *P, *fields)
                self.rec.equations.append((cname, fields, rfvs, c_app, body_t, p_index))
            body_t = replaced
        return lam_over(fvs + rfvs, body_t)

    def replace_calls(self, t, p, fmap):
        rec = self.rec
        params = rec.params
        if isinstance(t, App) or (isinstance(t, Const) and t.name == rec.fname):
            h, args = unapps(t)
            args = [self.replace_calls(a, p, fmap) for a in args]
            if isinstance(h, Const) and h.name == rec.fname:
                if (len(args) > p and isinstance(args[p], Fv) and args[p].id in fmap and
                        all(isinstance(args[i], Fv) and args[i].id == params[i].id for i in range(p))):
                    return apps(fmap[args[p].id], *args[p + 1:])
                return apps(h, *args)
            return apps(self.replace_calls(h, p, fmap) if not isinstance(h, (Const, Fv, Var, Sort)) else h, *args)
        if isinstance(t, Pi):
            return Pi(t.name, self.replace_calls(t.dom, p, fmap), self.replace_calls(t.cod, p, fmap))
        if isinstance(t, Lam):
            return Lam(t.name, self.replace_calls(t.dom, p, fmap), self.replace_calls(t.body, p, fmap))
        return t


class _P:
    """Position wrapper for error reporting."""
    def __init__(self, pos): self.pos = pos
