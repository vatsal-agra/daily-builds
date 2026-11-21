"""Tactic engine (untrusted): goals with metavariables, a first-order unifier, and the tactics.

A tactic never produces a trusted fact — it only builds a proof *term*, which the kernel then checks.
"""
from .terms import (Var, Sort, Const, App, Pi, Lam, Fv, Meta, BindF, apps, unapps, instantiate, abstract,
                    subst_fv, pi_over, lam_over, bind, has_meta, free_fvs, occurs_fv, size)
from .kernel import KernelError, Ctx, VPi, VNe, VSort, MAX_ELIM
from .pretty import show
from .syntax import LemmaError, Tac


class TacticError(Exception):
    pass


class Goal:
    def __init__(self, hyps, target, name=""):
        self.hyps = list(hyps)             # Fvs, in order
        self.target = target
        self.meta = Meta("g", target)
        self.name = name
        self.closed = False


def has_loose(t, d=0):
    if isinstance(t, Var):
        return t.i >= d
    if isinstance(t, App):
        return has_loose(t.f, d) or has_loose(t.a, d)
    if isinstance(t, Pi):
        return has_loose(t.dom, d) or has_loose(t.cod, d + 1)
    if isinstance(t, Lam):
        return has_loose(t.dom, d) or has_loose(t.body, d + 1)
    return False


def head_const(t):
    h, _ = unapps(t)
    return h.name if isinstance(h, Const) else None


class State:
    def __init__(self, sess):
        self.s = sess
        self.k = sess.k
        self.el = sess.el
        self.assign = {}
        self.goals = []
        self.fresh_counter = 0

    # ------------------------------------------------------------ metas
    def zk(self, t):
        if isinstance(t, Meta):
            if t.id in self.assign:
                return self.zk(self.assign[t.id])
            return t
        if isinstance(t, App):
            return App(self.zk(t.f), self.zk(t.a))
        if isinstance(t, Pi):
            return Pi(t.name, self.zk(t.dom), self.zk(t.cod))
        if isinstance(t, Lam):
            return Lam(t.name, self.zk(t.dom), self.zk(t.body))
        if isinstance(t, BindF):
            return bind(t.kind, [t.fv], self.zk(t.body))
        return t

    def zk_fv_types(self, t):
        """Zonk inside Fv types too (so kernels see no metas)."""
        t = self.zk(t)
        if has_meta(t):
            return t
        return t

    # ------------------------------------------------------------ unification (first-order)
    def occurs(self, m, t):
        t = self.zk(t)
        if isinstance(t, Meta):
            return t.id == m.id
        if isinstance(t, App):
            return self.occurs(m, t.f) or self.occurs(m, t.a)
        if isinstance(t, (Pi, Lam)):
            return self.occurs(m, t.dom) or self.occurs(m, t.cod if isinstance(t, Pi) else t.body)
        return False

    def unify(self, a, b):
        snap = dict(self.assign)
        if self._unify(a, b):
            return True
        self.assign = snap
        return False

    def _unify(self, a, b):
        a, b = self.zk(a), self.zk(b)
        if a is b:
            return True
        if isinstance(a, Meta):
            if isinstance(b, Meta) and a.id == b.id:
                return True
            if self.occurs(a, b):
                return False
            self.assign[a.id] = b
            return True
        if isinstance(b, Meta):
            return self._unify(b, a)
        if isinstance(a, App) and isinstance(b, App):
            ha, aa = unapps(a)
            hb, ab = unapps(b)
            if len(aa) == len(ab) and self._unify(ha, hb) and all(self._unify(x, y) for x, y in zip(aa, ab)):
                return True
        elif isinstance(a, Pi) and isinstance(b, Pi):
            if self._unify(a.dom, b.dom):
                fv = Fv(a.name, a.dom)
                if self._unify(instantiate(a.cod, fv), instantiate(b.cod, fv)):
                    return True
        elif isinstance(a, Lam) and isinstance(b, Lam):
            if self._unify(a.dom, b.dom):
                fv = Fv(a.name, a.dom)
                if self._unify(instantiate(a.body, fv), instantiate(b.body, fv)):
                    return True
        elif a == b:
            return True
        # fallback: definitional equality when no metavariables remain
        if not has_meta(a) and not has_meta(b):
            try:
                return self.k.def_eq(a, b)
            except KernelError:
                return False
        return False

    # ------------------------------------------------------------ goals & display
    def scope(self, goal):
        sc = {}
        for h in goal.hyps:
            if h.name and h.name != "_":
                sc[h.name] = self.el.entry(h)
        return sc

    def render_goal(self, g, idx=None):
        lines = []
        groups = []
        for h in g.hyps:
            ty = show(self.zk(h.ty), [], self.k)
            if groups and groups[-1][1] == ty:
                groups[-1][0].append(h.name)
            else:
                groups.append(([h.name], ty))
        for names, ty in groups:
            lines.append(f"{' '.join(names)} : {ty}")
        head = f"case {g.name}\n" if g.name else ""
        lines.append("⊢ " + show(self.zk(g.target), [], self.k))
        return head + "\n".join(lines)

    def render_goals(self, goals=None):
        goals = self.goals if goals is None else goals
        if not goals:
            return "no goals"
        out = []
        for i, g in enumerate(goals):
            out.append((f"[goal {i + 1}/{len(goals)}]\n" if len(goals) > 1 else "") + self.render_goal(g))
        return "\n\n".join(out)

    def fail(self, tac, msg, goal=None):
        g = goal if goal is not None else (self.goals[0] if self.goals else None)
        txt = f"tactic '{tac.name}' failed: {msg}"
        if g is not None:
            txt += "\n\n" + self.render_goal(g)
        raise LemmaError(txt, tac.pos)

    def new_goal(self, hyps, target, name=""):
        return Goal(hyps, self.zk(target), name)

    def uniq_name(self, base, hyps):
        names = {h.name for h in hyps}
        n = base
        i = 0
        while n in names:
            i += 1
            n = f"{base}{i}"
        return n

    # ------------------------------------------------------------ running
    def run(self, tacs, final=True):
        for tac in tacs:
            self.step(tac)

    def step(self, tac):
        if tac.name == "block":
            if not self.goals:
                raise LemmaError("no goals to focus on with '{'", tac.pos)
            rest = self.goals[1:]
            self.goals = [self.goals[0]]
            self.run(tac.args[0])
            if self.goals:
                raise LemmaError("unsolved goals at the end of this '{ … }' block:\n\n" + self.render_goals(), tac.pos)
            self.goals = rest
            return
        if not self.goals:
            raise LemmaError(f"no goals left, but the tactic '{tac.name}' was given (the proof is already complete)", tac.pos)
        before = self.render_goals() if self.s.trace is not None else None
        fn = getattr(self, "t_" + tac.name, None)
        if fn is None:
            raise LemmaError(f"tactic '{tac.name}' is not implemented", tac.pos)
        goal = self.goals[0]
        try:
            new = fn(tac, goal, tac.args) if tac.name in ("intro", "intros", "revert", "unfold") else fn(tac, goal, *tac.args)
        except KernelError as e:
            self.fail(tac, f"kernel error while building the step: {e}", goal)
        if new is None:
            new = []
        self.goals = list(new) + self.goals[1:]
        if self.s.trace is not None:
            self.s.trace.append(dict(tac=tac.text or tac.name, before=before, after=self.render_goals()))

    def solve(self, goal, term):
        self.assign[goal.meta.id] = term

    # ------------------------------------------------------------ helpers
    def whnf_target(self, t):
        t = self.zk(t)
        if has_meta(t):
            return t
        return self.k.whnf_term(t)

    def elab_infer(self, s, goal):
        self.el.rec = None
        t, ty = self.el.infer(s, self.scope(goal))
        return t

    def elab_check(self, s, goal, ty_term):
        self.el.rec = None
        return self.el.check(s, self.scope(goal), self.k.eval([], ty_term))

    def type_of(self, t):
        """Type of a term, keeping definitions folded where we can (so lemma statements stay readable)."""
        h, args = unapps(t)
        if isinstance(h, Const):
            ty = self.k.decls[h.name].ty
        elif isinstance(h, Fv):
            ty = h.ty
        else:
            return self.k.infer_term(t)
        for a in args:
            if not isinstance(ty, Pi):
                ty = self.k.whnf_term(ty)
            if not isinstance(ty, Pi):
                return self.k.infer_term(t)
            ty = instantiate(ty.cod, a)
        return ty

    def peel(self, ty, n=None):
        """Open Π binders as fresh metas. Returns (metas, conclusion)."""
        metas = []
        t = ty
        while n is None or len(metas) < n:
            if not isinstance(t, Pi):
                t2 = t if has_meta(t) else self.k.whnf_term(t)
                if not isinstance(t2, Pi):
                    break
                t = t2
            m = Meta(t.name, t.dom)
            metas.append(m)
            t = instantiate(t.cod, m)
        return metas, t

    def leftover_goals(self, goal, metas):
        out = []
        for m in metas:
            if m.id not in self.assign:
                g = Goal(goal.hyps, self.zk(m.ty), name=m.name if m.name not in ("_", "?") else "")
                self.assign[m.id] = g.meta
                out.append(g)
        return out

    def level_of(self, t):
        return self.k.sort_level(self.zk(t))

    # ================================================================ tactics
    def t_intro(self, tac, goal, names):
        names = names or [None]
        hyps, cur = list(goal.hyps), self.zk(goal.target)
        fvs = []
        for nm in names:
            t = cur if isinstance(cur, Pi) else self.whnf_target(cur)
            if not isinstance(t, Pi):
                self.fail(tac, "the goal is not a function, ∀ or implication", goal)
            base = nm or (t.name if t.name not in ("_", "") else "h")
            name = nm if nm else self.uniq_name(base, hyps)
            fv = Fv(name, t.dom)
            fvs.append(fv)
            hyps.append(fv)
            cur = instantiate(t.cod, fv)
        g = self.new_goal(hyps, cur, goal.name)
        body = g.meta
        for fv in reversed(fvs):
            body = BindF("lam", fv, body)
        self.solve(goal, body)
        return [g]

    def t_intros(self, tac, goal, names):
        if names:
            return self.t_intro(tac, goal, names)
        hyps, cur, fvs = list(goal.hyps), self.zk(goal.target), []
        while True:
            t = cur if isinstance(cur, Pi) else self.whnf_target(cur)
            if not isinstance(t, Pi):
                break
            base = t.name if t.name not in ("_", "") else "h"
            fv = Fv(self.uniq_name(base, hyps), t.dom)
            fvs.append(fv); hyps.append(fv)
            cur = instantiate(t.cod, fv)
        if not fvs:
            self.fail(tac, "nothing to introduce", goal)
        g = self.new_goal(hyps, cur, goal.name)
        body = g.meta
        for fv in reversed(fvs):
            body = BindF("lam", fv, body)
        self.solve(goal, body)
        return [g]

    def t_exact(self, tac, goal, term, *more):
        tgt = self.zk(goal.target)
        try:
            t = self.elab_check(term, goal, tgt)
        except LemmaError as e:
            self.fail(tac, e.msg, goal)
        self.solve(goal, t)
        return []

    def _apply_term(self, tac, goal, tm):
        tgt = self.zk(goal.target)
        ty = self.type_of(tm)
        metas, concl = [], ty
        t = ty
        attempt = 0
        while True:
            snap = dict(self.assign)
            if self.unify(concl, tgt):
                break
            self.assign = snap
            if not isinstance(t, Pi):
                t2 = t if has_meta(t) else self.k.whnf_term(t)
                if not isinstance(t2, Pi):
                    return None
                t = t2
            m = Meta(t.name, t.dom)
            metas.append(m)
            t = instantiate(t.cod, m)
            concl = t
        self.solve(goal, apps(tm, *metas))
        return self.leftover_goals(goal, metas)

    def t_apply(self, tac, goal, term, *more):
        tm = self.elab_infer(term, goal)
        r = self._apply_term(tac, goal, tm)
        if r is None:
            self.fail(tac, f"cannot unify the conclusion of '{show(tm, [], self.k)} : "
                           f"{show(self.type_of(tm), [], self.k)}' with the goal", goal)
        return r

    def t_assumption(self, tac, goal):
        tgt = self.zk(goal.target)
        for h in reversed(goal.hyps):
            if self.k.def_eq(self.zk(h.ty), tgt):
                self.solve(goal, h)
                return []
        self.fail(tac, "no hypothesis matches the goal", goal)

    def eq_parts(self, t):
        t = self.zk(t)
        h, args = unapps(t)
        if isinstance(h, Const) and h.name == "Eq" and len(args) == 3:
            return args
        if not has_meta(t):
            t2 = self.k.whnf_term(t)
            h, args = unapps(t2)
            if isinstance(h, Const) and h.name == "Eq" and len(args) == 3:
                return args
        return None

    def t_refl(self, tac, goal):
        parts = self.eq_parts(goal.target)
        if parts is None:
            self.fail(tac, "the goal is not an equation 'a = b'", goal)
        A, a, b = parts
        if not self.k.def_eq(a, b):
            self.fail(tac, f"the two sides are not definitionally equal:\n  {show(self.k.normalize(a), [], self.k)}\n  {show(self.k.normalize(b), [], self.k)}", goal)
        self.solve(goal, apps(Const("refl"), A, a))
        return []

    t_reflexivity = t_refl

    def lemma(self, tac, name):
        if name not in self.k.decls:
            raise LemmaError(f"tactic '{tac.name}' needs the library lemma '{name}' (not defined)", tac.pos)
        return Const(name)

    def t_symm(self, tac, goal):
        parts = self.eq_parts(goal.target)
        if parts is None:
            self.fail(tac, "the goal is not an equation", goal)
        A, a, b = parts
        g = self.new_goal(goal.hyps, apps(Const("Eq"), A, b, a), goal.name)
        self.solve(goal, apps(self.lemma(tac, "Eq.symm"), A, b, a, g.meta))
        return [g]

    # ---- rewriting
    def subterms(self, t, depth=0):
        if has_loose(t, 0) and depth == 0:
            pass
        if isinstance(t, App):
            yield t
            yield from self.subterms(t.f)
            yield from self.subterms(t.a)
        elif isinstance(t, (Const, Fv)):
            yield t
        elif isinstance(t, (Pi, Lam)):
            yield from self.subterms(t.dom)
            yield from self.subterms(t.cod if isinstance(t, Pi) else t.body)

    def replace_all(self, t, pat, fv):
        if not has_loose(t) and t == pat:
            return fv
        if isinstance(t, App):
            return App(self.replace_all(t.f, pat, fv), self.replace_all(t.a, pat, fv))
        if isinstance(t, Pi):
            return Pi(t.name, self.replace_all(t.dom, pat, fv), self.replace_all(t.cod, pat, fv))
        if isinstance(t, Lam):
            return Lam(t.name, self.replace_all(t.dom, pat, fv), self.replace_all(t.body, pat, fv))
        return t

    def rewrite_in(self, tac, goal, tm, rev, container):
        """Find an instance of lemma `tm` (an equation) inside `container`.
        Returns (A, a, b, pf, P_motive_fv_info, metas) or None."""
        ty = self.type_of(tm)
        metas, concl = self.peel(ty)
        parts = self.eq_parts(concl)
        if parts is None:
            self.fail(tac, f"'{show(tm, [], self.k)}' is not an equation (its type is {show(ty, [], self.k)})", goal)
        A, l, r = parts
        pf = apps(tm, *metas)
        if rev:
            A, l, r = A, r, l
            pf = apps(self.lemma(tac, "Eq.symm"), A, r, l, pf)
        pat = self.zk(l)
        if isinstance(pat, Meta):
            self.fail(tac, "the left-hand side of the equation is a bare variable; cannot rewrite", goal)
        hc = head_const(pat)
        container = self.zk(container)
        for sub in self.subterms(container):
            if has_loose(sub):
                continue
            if hc is not None and head_const(sub) != hc:
                continue
            snap = dict(self.assign)
            if self.unify(pat, sub):
                inst = self.zk(pat)
                return A, inst, self.zk(r), pf, metas
            self.assign = snap
        return None

    def do_rewrite(self, tac, goal, tm, rev, at):
        if at is None:
            found = self.rewrite_in(tac, goal, tm, rev, goal.target)
            if found is None:
                self.fail(tac, f"did not find an instance of the pattern in the goal:\n  pattern: "
                               f"{show(self.pattern_of(tm, rev), [], self.k)}", goal)
            A, a, b, pf, metas = found
            tgt = self.zk(goal.target)
            x = Fv("x", self.zk(A))
            body = self.replace_all(tgt, a, x)
            P = Lam("x", self.zk(A), abstract(body, x))
            new_tgt = self.zk(self.replace_all(tgt, a, b)) if False else instantiate(abstract(body, x), b)
            g = self.new_goal(goal.hyps, new_tgt, goal.name)
            sym = apps(self.lemma(tac, "Eq.symm"), A, a, b, pf)
            self.solve(goal, apps(self.lemma(tac, "Eq.subst"), A, b, a, sym, P, g.meta))
            extra = self.leftover_goals(goal, metas)
            self.autoclose(g)
            return [g] + extra
        # rewrite at a hypothesis
        h = next((x for x in reversed(goal.hyps) if x.name == at), None)
        if h is None:
            self.fail(tac, f"no hypothesis named '{at}'", goal)
        found = self.rewrite_in(tac, goal, tm, rev, h.ty)
        if found is None:
            self.fail(tac, f"did not find an instance of the pattern in hypothesis '{at}'", goal)
        A, a, b, pf, metas = found
        hty = self.zk(h.ty)
        x = Fv("x", self.zk(A))
        body = self.replace_all(hty, a, x)
        P = Lam("x", self.zk(A), abstract(body, x))
        new_ty = instantiate(abstract(body, x), b)
        h2 = Fv(h.name, new_ty)
        hyps = [h2 if y.id == h.id else y for y in goal.hyps]
        g = self.new_goal(hyps, goal.target, goal.name)
        transported = apps(self.lemma(tac, "Eq.subst"), A, a, b, pf, P, h)
        self.solve(goal, App(BindF("lam", h2, g.meta), transported))
        return [g] + self.leftover_goals(goal, metas)

    def pattern_of(self, tm, rev):
        metas, concl = self.peel(self.type_of(tm))
        parts = self.eq_parts(concl)
        if parts is None:
            return concl
        return parts[2] if rev else parts[1]

    def autoclose(self, g):
        """Like Coq/Lean: after a rewrite, close `x = x` goals that are syntactically reflexive."""
        parts = self.eq_parts(g.target) if not has_meta(self.zk(g.target)) else None
        if parts and parts[1] == parts[2]:
            self.solve(g, apps(Const("refl"), parts[0], parts[1]))
            g.closed = True

    def t_rewrite(self, tac, goal, items, at):
        goals = [goal]
        cur = goal
        extra_all = []
        for rev, term in items:
            if cur.closed:
                self.fail(tac, "the goal was already closed by an earlier rewrite", goal)
            tm = self.elab_infer(term, cur)
            res = self.do_rewrite(tac, cur, tm, rev, at)
            main, extra = res[0], res[1:]
            extra_all += extra
            cur = main
        out = ([] if cur.closed else [cur]) + extra_all
        return out

    def t_simp(self, tac, goal, lemmas, at):
        cands = []
        for name in self.k.order:
            if ".eq_" in name:
                cands.append((False, Const(name)))
        for rev, term in lemmas:
            cands.append((rev, self.elab_infer(term, goal)))
        cands = [(r, t) for r, t in cands]
        # user lemmas first
        user = cands[len([1 for n in self.k.order if ".eq_" in n]):]
        cands = user + cands[:len(cands) - len(user)]
        cur = goal
        steps = 0
        seen = set()
        while steps < 200 and not cur.closed:
            if at is None:
                key = repr(self.zk(cur.target))
                if key in seen:
                    break
                seen.add(key)
            progressed = False
            for rev, tm in cands:
                try:
                    res = self.try_rewrite(tac, cur, tm, rev, at)
                except LemmaError:
                    res = None
                if res is not None:
                    cur = res
                    steps += 1
                    progressed = True
                    break
            if not progressed:
                break
        if steps == 0 and at is None:
            parts = self.eq_parts(cur.target)
            if not (parts and self.k.def_eq(parts[1], parts[2])):
                self.fail(tac, "simp made no progress", goal)
        if not cur.closed and at is None:
            parts = self.eq_parts(cur.target)
            if parts and not has_meta(self.zk(cur.target)) and self.k.def_eq(parts[1], parts[2]):
                self.solve(cur, apps(Const("refl"), parts[0], parts[1]))
                return []
        return [] if cur.closed else [cur]

    def try_rewrite(self, tac, goal, tm, rev, at):
        snap = dict(self.assign)
        pending = self.assign.get(goal.meta.id)
        try:
            ty = self.type_of(tm)
            if self.eq_parts(self.peel(ty)[1]) is None:
                return None
            res = self.do_rewrite(tac, goal, tm, rev, at)
        except LemmaError:
            self.assign = snap
            return None
        main = res[0]
        # reject rewrites that leave side goals (simp only uses fully-instantiated lemmas)
        if len(res) > 1:
            self.assign = snap
            return None
        return main

    # ---- induction / cases
    def _ind_info(self, tac, goal, name):
        h = next((x for x in reversed(goal.hyps) if x.name == name), None)
        if h is None:
            self.fail(tac, f"no hypothesis named '{name}'", goal)
        ty = self.whnf_target(h.ty)
        hd, args = unapps(ty)
        if not (isinstance(hd, Const) and self.k.decls[hd.name].kind == "ind"):
            self.fail(tac, f"'{name}' has type {show(ty, [], self.k)}, which is not an inductive type", goal)
        return h, self.k.decls[hd.name], args

    def t_induction(self, tac, goal, name, groups):
        return self._elim(tac, goal, name, groups, with_ih=True)

    def t_cases(self, tac, goal, name, groups):
        return self._elim(tac, goal, name, groups, with_ih=False)

    def _elim(self, tac, goal, name, groups, with_ih):
        k = self.k
        x, ind, args = self._ind_info(tac, goal, name)
        info = ind.info
        P, IDX = args[:info.nparams], args[info.nparams:]
        for ix in IDX:
            if not isinstance(ix, Fv):
                self.fail(tac, f"the type of '{name}' has an index that is not a variable "
                               f"({show(ix, [], k)}); {tac.name} needs a variable there", goal)
        if len({ix.id for ix in IDX}) != len(IDX) or any(ix.id == x.id for ix in IDX):
            self.fail(tac, "the indices must be distinct variables", goal)
        by_ctor = {}
        for c, ns in groups:
            if c not in info.ctors:
                self.fail(tac, f"'{c}' is not a constructor of {ind.name} (constructors: {', '.join(info.ctors)})", goal)
            by_ctor[c] = ns
        gone = {x.id} | {ix.id for ix in IDX}
        deps = []
        depids = set()
        for h in goal.hyps:
            if h.id in gone:
                continue
            fvs = free_fvs(self.zk(h.ty))
            if any(i in fvs for i in gone) or any(i in fvs for i in depids):
                deps.append(h); depids.add(h.id)
        tgt = self.zk(goal.target)
        body = pi_over(deps, tgt)
        # motive
        ity = ind.ty
        for p in P:
            ity = instantiate(ity.cod, p)
        idxf, t_ = [], ity
        while isinstance(t_, Pi):
            fv = Fv(t_.name if t_.name != "_" else "i", t_.dom)
            idxf.append(fv); t_ = instantiate(t_.cod, fv)
        tf = Fv("t", apps(Const(ind.name), *P, *idxf))
        mb = subst_fv(body, x, tf)
        for ix, iv in zip(IDX, idxf):
            mb = subst_fv(mb, ix, iv)
        M = lam_over(idxf + [tf], mb)
        level = k.sort_level(mb)
        if level > MAX_ELIM:
            self.fail(tac, f"goal lives in Type {level}; elimination supports up to Type {MAX_ELIM}", goal)
        rname = ind.name + (".rec" if level == 0 else f".rec_{level}")
        base_hyps = [h for h in goal.hyps if h.id not in gone and h.id not in depids]
        np_ = info.nparams
        minors, goals = [], []
        for cname in info.ctors:
            cd = k.decls[cname]
            cinf = cd.info
            nf, nrec = cinf.nfields, sum(cinf.rec_fields)
            given = by_ctor.get(cname, [])
            if len(given) > nf + nrec:
                self.fail(tac, f"constructor '{cname}' binds {nf + nrec} name(s) ({nf} field(s), {nrec} induction hypothesis(es)); {len(given)} given", goal)
            hyps = list(base_hyps)
            binders, ffvs, recs = [], [], []
            ct = cd.ty
            for p in P:
                ct = instantiate(ct.cod, p)
            for i in range(nf):
                if i < len(given):
                    nm = given[i]
                else:
                    hd0 = unapps(ct.dom)[0]
                    raw = ct.name if ct.name not in ("_", "") else (
                        hd0.name[0].lower() if isinstance(hd0, Const) and hd0.name[:1].isalpha() else "a")
                    nm = self.uniq_name(raw, hyps + binders)
                fv = Fv(nm, ct.dom)
                xs, c = [], ct.dom
                while isinstance(c, Pi):
                    xv = Fv(c.name, c.dom); xs.append(xv); c = instantiate(c.cod, xv)
                hd, cargs = unapps(c)
                recs.append((xs, cargs[np_:]) if isinstance(hd, Const) and hd.name == ind.name else None)
                ffvs.append(fv); binders.append(fv); hyps.append(fv)
                ct = instantiate(ct.cod, fv)
            ridx = unapps(ct)[1][np_:]
            ihs, j = [], 0
            for f, rec in zip(ffvs, recs):
                if rec is None:
                    continue
                xs, ia = rec
                j += 1
                ihty_body = mb
                ihty_body = subst_fv(ihty_body, tf, apps(f, *xs))
                for iv, ie in zip(idxf, ia):
                    ihty_body = subst_fv(ihty_body, iv, ie)
                idx_in_given = nf + len(ihs)
                nm = given[idx_in_given] if idx_in_given < len(given) else self.uniq_name(f"{f.name}_ih", hyps + binders)
                ih = Fv(nm, pi_over(xs, ihty_body))
                ihs.append(ih)
                binders.append(ih)
                if with_ih:
                    hyps.append(ih)
            c_app = apps(Const(cname), *P, *ffvs)
            cur = subst_fv(mb, tf, c_app)
            for iv, ie in zip(idxf, ridx):
                cur = subst_fv(cur, iv, ie)
            redeps = []
            for d in deps:
                fv = Fv(d.name, cur.dom)
                redeps.append(fv); hyps.append(fv)
                cur = instantiate(cur.cod, fv)
            g = self.new_goal(hyps, cur, name=cname)
            goals.append(g)
            minors.append(lam_over_deferred(binders + redeps, g.meta))
        self.solve(goal, apps(Const(rname), *P, M, *minors, *IDX, x, *deps))
        return goals

    # ---- constructors & friends
    def _target_ind(self, tac, goal):
        ty = self.whnf_target(goal.target)
        hd, args = unapps(ty)
        if not (isinstance(hd, Const) and self.k.decls[hd.name].kind == "ind"):
            self.fail(tac, f"the goal {show(ty, [], self.k)} is not an inductive type", goal)
        return self.k.decls[hd.name], args

    def t_constructor(self, tac, goal):
        ind, args = self._target_ind(tac, goal)
        for c in ind.info.ctors:
            snap = dict(self.assign)
            pa = args[:ind.info.nparams]
            r = self._apply_term(tac, goal, apps(Const(c), *pa))
            if r is not None:
                return r
            self.assign = snap
        self.fail(tac, f"no constructor of {ind.name} applies to the goal", goal)

    def _nth_ctor(self, tac, goal, n):
        ind, args = self._target_ind(tac, goal)
        if len(ind.info.ctors) <= n:
            self.fail(tac, f"{ind.name} has only {len(ind.info.ctors)} constructor(s)", goal)
        r = self._apply_term(tac, goal, apps(Const(ind.info.ctors[n]), *args[:ind.info.nparams]))
        if r is None:
            self.fail(tac, f"constructor {ind.info.ctors[n]} does not match the goal", goal)
        return r

    def t_left(self, tac, goal):
        return self._nth_ctor(tac, goal, 0)

    def t_right(self, tac, goal):
        return self._nth_ctor(tac, goal, 1)

    def t_split(self, tac, goal):
        ind, _ = self._target_ind(tac, goal)
        if len(ind.info.ctors) != 1:
            self.fail(tac, f"'split' needs a single-constructor type (like And); {ind.name} has {len(ind.info.ctors)}", goal)
        return self.t_constructor(tac, goal)

    def t_exists(self, tac, goal, *witnesses):
        ind, args = self._target_ind(tac, goal)
        if len(ind.info.ctors) != 1:
            self.fail(tac, "'exists' needs a single-constructor type such as Exists", goal)
        c = ind.info.ctors[0]
        tm = apps(Const(c), *args[:ind.info.nparams])
        for w in witnesses:
            ty = self.k.whnf_term(self.type_of(tm))
            if not isinstance(ty, Pi):
                self.fail(tac, "too many witnesses", goal)
            wt = self.elab_check(w, goal, ty.dom)
            tm = App(tm, wt)
        r = self._apply_term(tac, goal, tm)
        if r is None:
            self.fail(tac, "the witness does not fit the goal", goal)
        return r

    def t_exfalso(self, tac, goal):
        if "False" not in self.k.decls:
            self.fail(tac, "no 'False' in scope", goal)
        tgt = self.zk(goal.target)
        lvl = self.level_of(tgt)
        g = self.new_goal(goal.hyps, Const("False"), goal.name)
        motive = Lam("_", Const("False"), tgt)
        rn = "False.rec" if lvl == 0 else f"False.rec_{lvl}"
        self.solve(goal, apps(Const(rn), motive, g.meta))
        return [g]

    def t_contradiction(self, tac, goal):
        tgt = self.zk(goal.target)
        lvl = self.level_of(tgt)
        rn = "False.rec" if lvl == 0 else f"False.rec_{lvl}"
        motive = Lam("_", Const("False"), tgt)
        F = Const("False")
        for h in reversed(goal.hyps):
            if self.k.def_eq(self.zk(h.ty), F):
                self.solve(goal, apps(Const(rn), motive, h))
                return []
        for h in reversed(goal.hyps):
            hty = self.k.whnf_term(self.zk(h.ty))
            if isinstance(hty, Pi) and not has_loose(hty.cod) and self.k.def_eq(hty.cod, F):
                for a in reversed(goal.hyps):
                    if self.k.def_eq(self.zk(a.ty), hty.dom):
                        self.solve(goal, apps(Const(rn), motive, App(h, a)))
                        return []
        self.fail(tac, "no contradictory hypotheses found (need h : False, or h : ¬A together with a : A)", goal)

    def t_have(self, tac, goal, name, ty_s, val_s):
        ty = self.elab_type_t(ty_s, goal)
        h = Fv(name, ty)
        main = self.new_goal(goal.hyps + [h], goal.target, goal.name)
        if val_s is not None:
            val = self.elab_check(val_s, goal, ty)
            self.solve(goal, App(BindF("lam", h, main.meta), val))
            return [main]
        side = self.new_goal(goal.hyps, ty, name)
        self.solve(goal, App(BindF("lam", h, main.meta), side.meta))
        return [side, main]

    def elab_type_t(self, s, goal):
        self.el.rec = None
        return self.el.elab_type(s, self.scope(goal))

    def t_show(self, tac, goal, ty_s):
        ty = self.elab_type_t(ty_s, goal)
        if not self.k.def_eq(ty, self.zk(goal.target)):
            self.fail(tac, f"the goal is not (definitionally) {show(ty, [], self.k)}", goal)
        g = self.new_goal(goal.hyps, ty, goal.name)
        self.solve(goal, g.meta)
        return [g]

    def t_norm(self, tac, goal):
        g = self.new_goal(goal.hyps, self.k.normalize(self.zk(goal.target)), goal.name)
        self.solve(goal, g.meta)
        return [g]

    def t_unfold(self, tac, goal, names):
        tgt = self.zk(goal.target)
        for nm in names:
            d = self.k.decls.get(nm)
            if d is None or d.kind != "def":
                self.fail(tac, f"'{nm}' is not an unfoldable definition", goal)
            tgt = self.unfold_const(tgt, nm, d.val)
        g = self.new_goal(goal.hyps, tgt, goal.name)
        self.solve(goal, g.meta)
        return [g]

    def unfold_const(self, t, nm, val):
        if isinstance(t, Const) and t.name == nm:
            return val
        if isinstance(t, App):
            f = self.unfold_const(t.f, nm, val)
            a = self.unfold_const(t.a, nm, val)
            if isinstance(f, Lam):
                return instantiate(f.body, a)
            return App(f, a)
        if isinstance(t, Pi):
            return Pi(t.name, self.unfold_const(t.dom, nm, val), self.unfold_const(t.cod, nm, val))
        if isinstance(t, Lam):
            return Lam(t.name, self.unfold_const(t.dom, nm, val), self.unfold_const(t.body, nm, val))
        return t

    def t_revert(self, tac, goal, names):
        hyps = list(goal.hyps)
        tgt = self.zk(goal.target)
        rev = []
        for nm in names:
            h = next((x for x in reversed(hyps) if x.name == nm), None)
            if h is None:
                self.fail(tac, f"no hypothesis named '{nm}'", goal)
            hyps.remove(h)
            rev.append(h)
        g = self.new_goal(hyps, pi_over(list(reversed(rev)), tgt), goal.name)
        self.solve(goal, apps(g.meta, *reversed(rev)))
        return [g]

    def t_trivial(self, tac, goal):
        for fn in (lambda: self.t_assumption(tac, goal), lambda: self.t_refl(tac, goal),
                   lambda: self.t_constructor(tac, goal)):
            snap = dict(self.assign)
            try:
                r = fn()
                if not r:
                    return r
            except LemmaError:
                pass
            self.assign = snap
        self.fail(tac, "could not solve the goal by assumption, reflexivity or a constructor", goal)



def lam_over_deferred(fvs, body):
    for fv in reversed(fvs):
        body = BindF("lam", fv, body)
    return body


# `try` replaces goals itself, so wrap step to honour that
_orig_step = State.step


def _step(self, tac):
    if tac.name == "try":
        snap_assign, snap_goals = dict(self.assign), list(self.goals)
        tr = self.s.trace
        self.s.trace = None
        try:
            _orig_step(self, tac.args[0])
        except LemmaError:
            self.assign, self.goals = snap_assign, snap_goals
        finally:
            self.s.trace = tr
        return
    return _orig_step(self, tac)


State.step = _step


def run_block(sess, block, params, scope, target):
    """Run a `by` block proving `target` (a term over the Fvs `params`); return the proof term."""
    st = State(sess)
    sess.trace = []
    goal = Goal(params, target)
    st.goals = [goal]
    st.run(block.tactics)
    if st.goals:
        raise LemmaError("unsolved goals:\n\n" + st.render_goals(), block.pos)
    term = st.zk(goal.meta)
    if has_meta(term):
        raise LemmaError("internal error: proof term still contains metavariables", block.pos)
    _check_no_bindf(term)
    extra = [f for f in free_fvs(term).values() if all(f.id != p.id for p in params)]
    if extra:
        raise LemmaError("internal error: proof term mentions a variable that is out of scope: " + ", ".join(f.name for f in extra), block.pos)
    return term


def _check_no_bindf(t):
    if isinstance(t, BindF):
        raise LemmaError("internal error: unresolved binder in proof term")
    if isinstance(t, App):
        _check_no_bindf(t.f); _check_no_bindf(t.a)
    elif isinstance(t, (Pi, Lam)):
        _check_no_bindf(t.dom); _check_no_bindf(t.cod if isinstance(t, Pi) else t.body)
