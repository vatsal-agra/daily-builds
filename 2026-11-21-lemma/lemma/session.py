"""Command driver: runs a source file command by command against one kernel."""
import os
import time
from .terms import (Const, App, Pi, Lam, Fv, Sort, apps, pi_over, lam_over, subst_fv, occurs_const, size)
from .kernel import Kernel, KernelError, Ctx, VPi, VNe, VSort
from .elab import Elaborator, RecCtx
from .pretty import Notation, show
from .syntax import *

PRELUDE = os.path.join(os.path.dirname(__file__), "prelude.lm")


class Session:
    def __init__(self, load_prelude=True):
        self.k = Kernel()
        self.k.notation = Notation()
        self.nota = self.k.notation
        self.nota.infix["="] = (50, "n", "=")
        self.el = Elaborator(self.k, self.nota)
        self.out = []            # informational lines (#check results, "ok theorem ...")
        self.errors = []         # rendered error strings
        self.results = []        # per-command records (for reports)
        self.trace = None        # tactic trace collector for the current theorem
        self.n_prelude = 0
        self.equations = []      # auto-generated equation lemma names (the default simp set)
        self.filename = "<input>"
        self.src = ""
        if load_prelude:
            with open(PRELUDE, encoding="utf-8") as f:
                src = f.read()
            self.run(src, "prelude.lm", quiet=True)
            if self.errors:
                raise RuntimeError("prelude failed to load:\n" + "\n".join(self.errors))
        self.n_prelude = len(self.results)       # results beyond this index belong to the user's file

    # ------------------------------------------------------------ running
    def run(self, src, filename="<input>", quiet=False):
        self.filename, self.src = filename, src
        n_err = len(self.errors)
        try:
            parser = Parser(src, self.nota)
        except LemmaError as e:
            self.errors.append(e.render(filename, src))
            return False
        while parser.tok.kind != "eof":
            start = parser.p
            try:
                cmd = parser.command()
            except LemmaError as e:
                self.errors.append(e.render(filename, src))
                self.results.append(dict(kind="error", name="<syntax>", ok=False, msg=e.msg))
                parser.p = max(parser.p, start + 1)
                self._skip_to_command(parser)
                continue
            t0 = time.time()
            try:
                rec = self.exec(cmd, quiet)
                if rec:
                    rec["time"] = time.time() - t0
                    self.results.append(rec)
            except LemmaError as e:
                self.errors.append(e.render(filename, src))
                self.results.append(dict(kind=type(cmd).__name__, name=getattr(cmd, "name", ""), ok=False,
                                         msg=e.msg, pos=e.pos, steps=self.trace))
            except KernelError as e:
                msg = f"kernel rejected the declaration: {e}"
                self.errors.append(LemmaError(msg, cmd.pos, src).render(filename, src))
                self.results.append(dict(kind=type(cmd).__name__, name=getattr(cmd, "name", ""), ok=False, msg=msg, pos=cmd.pos))
            except RecursionError:
                msg = "term too deeply nested (recursion limit)"
                self.errors.append(LemmaError(msg, cmd.pos, src).render(filename, src))
                self.results.append(dict(kind=type(cmd).__name__, name=getattr(cmd, "name", ""), ok=False, msg=msg, pos=cmd.pos))
            except Exception as e:                      # never crash on user input
                msg = f"internal error ({type(e).__name__}: {e}); this is a bug in Lemma, not in your file"
                self.errors.append(LemmaError(msg, cmd.pos, src).render(filename, src))
                self.results.append(dict(kind=type(cmd).__name__, name=getattr(cmd, "name", ""), ok=False, msg=msg, pos=cmd.pos))
        return len(self.errors) == n_err

    def _skip_to_command(self, parser):
        while parser.tok.kind != "eof" and not (parser.tok.kind == "ident" and parser.tok.text in COMMANDS):
            parser.p += 1

    def say(self, line):
        self.out.append(line)

    # ------------------------------------------------------------ commands
    def exec(self, c, quiet):
        if isinstance(c, CNotation):
            assoc = {"infixl": "l", "infixr": "r", "infix": "n"}.get(c.kind)
            if c.kind == "prefix":
                self.nota.add_prefix(c.tok, c.prec, c.target)
            else:
                self.nota.add_infix(c.tok, c.prec, assoc, c.target)
            return None
        if isinstance(c, CInductive):
            return self.exec_inductive(c, quiet)
        if isinstance(c, CDef):
            return self.exec_def(c, quiet)
        if isinstance(c, CAxiom):
            return self.exec_axiom(c, quiet)
        if isinstance(c, CCheck):
            t, ty = self.el.infer(c.term, {})
            if isinstance(t, Const):
                tt = self.k.decls[t.name].ty
            else:
                tt = self.k.quote(0, ty)
            self.say(f"{show(t, [], self.k)} : {show(tt, [], self.k)}")
            return None
        if isinstance(c, CEval):
            t, ty = self.el.infer(c.term, {})
            nf = self.k.normalize(t)
            self.say(f"{show(nf, [], self.k)} : {show(self.k.quote(0, ty), [], self.k)}")
            return None
        if isinstance(c, CPrint):
            self.print_decl(c)
            return None
        raise LemmaError(f"unsupported command {type(c).__name__}", c.pos)

    def binders_to_fvs(self, binders, scope):
        fvs, sc = [], scope
        for name, ann in binders:
            ty = self.el.elab_type(ann, sc)
            fv = Fv(name, ty)
            fvs.append(fv)
            sc = self.el.extend(sc, name, fv)
        return fvs, sc

    def exec_inductive(self, c, quiet):
        k = self.k
        if c.name in k.decls:
            raise LemmaError(f"'{c.name}' is already declared", c.pos)
        params, scope = self.binders_to_fvs(c.params, {})
        arity = self.el.elab_type(c.arity, scope)
        a = arity
        while isinstance(a, Pi):
            a = a.cod
        if not isinstance(a, Sort):
            raise LemmaError("the arity of an inductive type must end in 'Type' (or 'Type n')", c.arity.pos)
        ind_ty = pi_over(params, arity)
        k.add_axiom(c.name, ind_ty)                  # temporary: lets constructor types mention the type
        try:
            ctors = []
            for cn, cty, cpos in c.ctors:
                if cn in k.decls:
                    raise LemmaError(f"'{cn}' is already declared", cpos)
                t = self.el.elab_type(cty, scope)
                ctors.append((cn, pi_over(params, t), cpos))
        finally:
            k.decls.pop(c.name, None)
            if k.order and k.order[-1] == c.name:
                k.order.pop()
        try:
            k.add_inductive(c.name, ind_ty, len(params), [(cn, t) for cn, t, _ in ctors])
        except KernelError as e:
            pos = c.pos
            for cn, _, cpos in ctors:
                if f"'{cn}'" in str(e):
                    pos = cpos
            raise LemmaError(f"inductive type '{c.name}' rejected: {e}", pos)
        if not quiet:
            self.say(f"inductive {c.name}  ({', '.join(cn for cn, _, _ in ctors)}; recursors {c.name}.rec, {c.name}.rec_1, {c.name}.rec_2)")
        return dict(kind="inductive", name=c.name, ok=True, pos=c.pos,
                    stmt=show(ind_ty, [], k) + "  where  " + ", ".join(cn for cn, _, _ in ctors))

    def exec_axiom(self, c, quiet):
        params, scope = self.binders_to_fvs(c.binders, {})
        ty = self.el.elab_type(c.ty, scope)
        try:
            self.k.add_axiom(c.name, pi_over(params, ty))
        except KernelError as e:
            raise LemmaError(str(e), c.pos)
        if not quiet:
            self.say(f"axiom {c.name}")
        return dict(kind="axiom", name=c.name, ok=True, pos=c.pos, stmt=show(pi_over(params, ty), [], self.k))

    def exec_def(self, c, quiet):
        k, el = self.k, self.el
        if c.kind != "example" and c.name in k.decls:
            raise LemmaError(f"'{c.name}' is already declared", c.pos)
        params, scope = self.binders_to_fvs(c.binders, {})
        T = el.elab_type(c.ty, scope)
        body = c.body
        # absorb leading `fun` binders into parameters (so they can be recursed on)
        while isinstance(body, SLam):
            tv = k.force(k.eval([], T))
            if not isinstance(tv, VPi):
                break
            name, ann = body.binders[0]
            dom = k.quote(0, tv.dom)
            if ann is not None:
                adom = el.elab_type(ann, scope)
                if not k.def_eq(adom, dom):
                    raise LemmaError(f"binder '{name}' is annotated {show(adom, [], k)} but the expected type is {show(dom, [], k)}", body.pos)
            fv = Fv(name, dom)
            params.append(fv)
            scope = el.extend(scope, name, fv)
            T = k.quote(0, k.apply(tv.cod, VNe(("fv", fv))))
            rest = body.binders[1:]
            body = SLam(rest, body.body, pos=body.pos) if rest else body.body
        name = c.name
        temp = c.kind != "example"
        if temp:
            k.add_axiom(name, pi_over(params, T))        # temporary: recursive calls typecheck against it
        el.rec = RecCtx(name, params, T)
        self.trace = None
        try:
            if isinstance(body, ByBlock):
                from .tactics import run_block
                val = run_block(self, body, params, scope, T)
            else:
                val = el.check(body, scope, k.eval([], T))
            rec = el.rec
        finally:
            el.rec = None
            if temp:
                k.decls.pop(name, None)
                if k.order and k.order[-1] == name:
                    k.order.pop()
        if occurs_const(val, name):
            raise LemmaError(f"'{name}' is used recursively, but not in a structurally decreasing way: "
                             f"a recursive call must be applied to a variable bound by an 'elim' branch "
                             f"(the argument being eliminated), with the earlier arguments unchanged", c.pos)
        ty = pi_over(params, T)
        value = lam_over(params, val)
        if c.kind == "example":
            k.check_term(value, ty)
            self.say(f"example ok")
            return dict(kind="example", name="example", ok=True)
        try:
            k.add_def(name, ty, value, opaque=(c.kind == "theorem"))
        except KernelError as e:
            raise LemmaError(f"kernel rejected '{name}': {e}", c.pos)
        neqs = self.add_equations(name, params, T, rec) if c.kind == "def" else 0
        axs = k.axioms_of(name)
        if not quiet:
            self.say(f"{c.kind} {name} : {show(ty, [], k)}" + (f"   [+{neqs} equation lemma(s)]" if neqs else "")
                     + (f"   [uses axiom(s): {', '.join(axs)}]" if axs else ""))
        return dict(kind=c.kind, name=name, ok=True, size=size(value), steps=self.trace, stmt=show(ty, [], k),
                    pos=c.pos, axioms=axs, equations=neqs)

    def add_equations(self, fname, params, T, rec):
        k = self.k
        if "Eq" not in k.decls or "refl" not in k.decls:
            return 0
        n = 0
        for cname, fields, rfvs, c_app, body_pre, p in rec.equations:
            xp = params[p]
            gen_R = params[p + 1:]
            Teq = subst_fv(T, xp, c_app)
            for r, r2 in zip(gen_R, rfvs):
                Teq = subst_fv(Teq, r, r2)
            fixed = params[:p]
            lhs = apps(Const(fname), *fixed, c_app, *rfvs)
            stmt = apps(Const("Eq"), Teq, lhs, body_pre)
            binders = fixed + fields + rfvs
            proof = apps(Const("refl"), Teq, lhs)
            try:
                k.add_def(f"{fname}.eq_{cname}", pi_over(binders, stmt), lam_over(binders, proof), opaque=True)
                self.equations.append(f"{fname}.eq_{cname}")
                n += 1
            except KernelError:
                pass
        return n

    def print_decl(self, c):
        k = self.k
        d = k.decls.get(c.name)
        if d is None:
            raise LemmaError(f"unknown constant '{c.name}'", c.pos)
        if c.axioms:
            axs = k.axioms_of(c.name)
            self.say(f"'{c.name}' depends on axioms: {', '.join(axs)}" if axs else f"'{c.name}' does not depend on any axioms")
            return
        kinds = {"def": "def", "theorem": "theorem", "axiom": "axiom", "ind": "inductive", "ctor": "constructor", "rec": "recursor"}
        self.say(f"{kinds[d.kind]} {d.name} : {show(d.ty, [], k)}")
        if d.kind in ("def", "theorem"):
            self.say(f"  := {show(d.val, [], k)}")
        if d.kind == "ind":
            for cn in d.info.ctors:
                self.say(f"  | {cn} : {show(k.decls[cn].ty, [], k)}")
