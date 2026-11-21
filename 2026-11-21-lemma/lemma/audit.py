"""Independent auditor.

A *second*, deliberately different implementation of the type theory:
  * named terms with capture-avoiding substitution (the kernel uses de Bruijn + NbE closures);
  * weak-head reduction by explicit substitution, full δ-unfolding (the kernel uses smart unfolding);
  * conversion = compare weak-head normal forms step by step with η;
  * recursors and ι-rules are **re-derived from the constructor types** here and must be
    convertible with what the certificate claims — a tampered or buggy recursor is caught.

It shares no code with `kernel.py`.  Input is a JSON certificate exported by `lemma check --export`.
"""
import json
from itertools import count

_fresh = count(1)


def fresh(base="v"):
    return f"{base}#{next(_fresh)}"


# ---------------------------------------------------------------- named terms
# ('v', name) ('s', n) ('c', name) ('a', f, a) ('p', name, dom, cod) ('l', name, dom, body)

def from_json(j, names):
    k = j[0]
    if k == "var":
        return ("v", names[-1 - j[1]])
    if k == "sort":
        return ("s", j[1])
    if k == "const":
        return ("c", j[1])
    if k == "app":
        return ("a", from_json(j[1], names), from_json(j[2], names))
    if k in ("pi", "lam"):
        dom = from_json(j[2], names)
        n = fresh(j[1] or "x")
        body = from_json(j[3], names + [n])
        return ("p" if k == "pi" else "l", n, dom, body)
    raise AuditError(f"malformed term {j!r}")


class AuditError(Exception):
    pass


def spine(t):
    args = []
    while t[0] == "a":
        args.append(t[2]); t = t[1]
    args.reverse()
    return t, args


def apps(f, args):
    for a in args:
        f = ("a", f, a)
    return f


def free_vars(t, acc=None):
    if acc is None:
        acc = set()
    k = t[0]
    if k == "v":
        acc.add(t[1])
    elif k == "a":
        free_vars(t[1], acc); free_vars(t[2], acc)
    elif k in ("p", "l"):
        free_vars(t[2], acc)
        inner = free_vars(t[3], set())
        inner.discard(t[1])
        acc |= inner
    return acc


def subst(t, x, v, fvv=None):
    k = t[0]
    if k == "v":
        return v if t[1] == x else t
    if k in ("s", "c"):
        return t
    if k == "a":
        return ("a", subst(t[1], x, v, fvv), subst(t[2], x, v, fvv))
    if fvv is None:
        fvv = free_vars(v)
    name, dom, body = t[1], subst(t[2], x, v, fvv), t[3]
    if name == x:
        return (k, name, dom, body)
    if name in fvv:                                    # avoid capture
        n2 = fresh(name.split("#")[0])
        body = subst(body, name, ("v", n2))
        name = n2
    return (k, name, dom, subst(body, x, v, fvv))


def occurs_const(t, c):
    k = t[0]
    if k == "c":
        return t[1] == c
    if k == "a":
        return occurs_const(t[1], c) or occurs_const(t[2], c)
    if k in ("p", "l"):
        return occurs_const(t[2], c) or occurs_const(t[3], c)
    return False


class Decl:
    def __init__(self, kind, name, ty, val=None, info=None):
        self.kind, self.name, self.ty, self.val, self.info = kind, name, ty, val, info


class Result:
    def __init__(self):
        self.ok = True
        self.checked = 0
        self.errors = []
        self.inductives = 0
        self.theorems = 0

    def fail(self, name, msg):
        self.ok = False
        self.errors.append(f"{name}: {msg}")

    def summary(self):
        if self.ok:
            return (f"auditor: ALL {self.checked} declaration(s) verified independently "
                    f"({self.theorems} theorem(s), {self.inductives} inductive type(s) with re-derived recursors)")
        return "auditor: REJECTED\n  " + "\n  ".join(self.errors[:10])


class Auditor:
    def __init__(self):
        self.env = {}

    # ---------------------------------------------------------------- reduction
    def whnf(self, t):
        while True:
            h, args = spine(t)
            if h[0] == "l" and args:
                t = apps(subst(h[3], h[1], args[0]), args[1:])
                continue
            if h[0] == "c":
                d = self.env.get(h[1])
                if d is None:
                    raise AuditError(f"unknown constant {h[1]}")
                if d.kind == "def" and d.val is not None:
                    t = apps(d.val, args)
                    continue
                if d.kind == "rec" and len(args) >= d.info["arity"]:
                    ar = d.info["arity"]
                    major = self.whnf(args[ar - 1])
                    mh, margs = spine(major)
                    if mh[0] == "c":
                        cd = self.env.get(mh[1])
                        if cd is not None and cd.kind == "ctor" and cd.info["ind"] == d.info["ind"]:
                            np_, nm = d.info["nparams"], d.info["nminors"]
                            rule, nf = d.info["rules"][mh[1]]
                            if len(margs) == np_ + nf:
                                t = apps(rule, list(args[:np_ + 1 + nm]) + margs[np_:] + list(args[ar:]))
                                continue
            return t

    def conv(self, a, b):
        if a == b:
            return True
        a, b = self.whnf(a), self.whnf(b)
        ka, kb = a[0], b[0]
        if ka == "s" and kb == "s":
            return a[1] == b[1]
        if ka == "p" and kb == "p":
            if not self.conv(a[2], b[2]):
                return False
            x = ("v", fresh("c"))
            return self.conv(subst(a[3], a[1], x), subst(b[3], b[1], x))
        if ka == "l" and kb == "l":
            x = ("v", fresh("c"))
            return self.conv(subst(a[3], a[1], x), subst(b[3], b[1], x))
        if ka == "l":
            x = ("v", fresh("c"))
            return self.conv(subst(a[3], a[1], x), ("a", b, x))
        if kb == "l":
            x = ("v", fresh("c"))
            return self.conv(("a", a, x), subst(b[3], b[1], x))
        ha, aa = spine(a)
        hb, ab = spine(b)
        if ha[0] in ("v", "c") and hb[0] in ("v", "c") and ha == hb and len(aa) == len(ab):
            return all(self.conv(x, y) for x, y in zip(aa, ab))
        return False

    def subtype(self, a, b):
        a, b = self.whnf(a), self.whnf(b)
        if a[0] == "s" and b[0] == "s":
            return a[1] <= b[1]
        if a[0] == "p" and b[0] == "p":
            if not self.conv(a[2], b[2]):
                return False
            x = ("v", fresh("c"))
            return self.subtype(subst(a[3], a[1], x), subst(b[3], b[1], x))
        return self.conv(a, b)

    # ---------------------------------------------------------------- typing
    def infer(self, t, ctx):
        k = t[0]
        if k == "v":
            if t[1] not in ctx:
                raise AuditError(f"free variable {t[1]} out of scope")
            return ctx[t[1]]
        if k == "s":
            return ("s", t[1] + 1)
        if k == "c":
            d = self.env.get(t[1])
            if d is None:
                raise AuditError(f"unknown constant {t[1]}")
            return d.ty
        if k == "p":
            s1 = self.sort(t[2], ctx)
            ctx2 = dict(ctx); ctx2[t[1]] = t[2]
            s2 = self.sort(t[3], ctx2)
            return ("s", max(s1, s2))
        if k == "l":
            self.sort(t[2], ctx)
            ctx2 = dict(ctx); ctx2[t[1]] = t[2]
            return ("p", t[1], t[2], self.infer(t[3], ctx2))
        if k == "a":
            ft = self.whnf(self.infer(t[1], ctx))
            if ft[0] != "p":
                raise AuditError("applying a non-function")
            at = self.infer(t[2], ctx)
            if not self.subtype(at, ft[2]):
                raise AuditError("argument type mismatch")
            return subst(ft[3], ft[1], t[2])
        raise AuditError("bad term")

    def sort(self, t, ctx):
        ty = self.whnf(self.infer(t, ctx))
        if ty[0] != "s":
            raise AuditError("not a type")
        return ty[1]

    def check(self, t, ty, ctx):
        got = self.infer(t, ctx)
        if not self.subtype(got, ty):
            raise AuditError("type mismatch")

    # ---------------------------------------------------------------- inductive packages
    def open_pis(self, t, ctx, n=None):
        """Open Π binders with fresh variables: returns (vars, rest)."""
        vs = []
        while t[0] == "p" and (n is None or len(vs) < n):
            x = fresh(t[1].split("#")[0] or "x")
            ctx[x] = t[2]
            vs.append(x)
            t = subst(t[3], t[1], ("v", x))
        return vs, t

    def mkpi(self, vs, body, ctx):
        for x in reversed(vs):
            body = ("p", x, ctx[x], body)
        return body

    def mklam(self, vs, body, ctx):
        for x in reversed(vs):
            body = ("l", x, ctx[x], body)
        return body

    def add_inductive(self, ind, ctors, recs, res):
        name, nparams = ind["name"], ind["nparams"]
        self.env[name] = Decl("ind", name, ind["ty"])
        self.sort(ind["ty"], {})
        ctx = {}
        P, rest = self.open_pis(ind["ty"], ctx, nparams)
        if len(P) != nparams:
            raise AuditError("fewer binders than parameters")
        IDXs, srt = self.open_pis(rest, ctx)
        if srt[0] != "s":
            raise AuditError("inductive type must end in a universe")
        u, ni = srt[1], len(IDXs)
        info = []
        for ci, c in enumerate(ctors):
            self.env[c["name"]] = Decl("ctor", c["name"], c["ty"], info={"ind": name, "index": ci})
            self.sort(c["ty"], {})
        for ci, c in enumerate(ctors):
            t = c["ty"]
            cctx = dict(ctx)
            for p in P:
                if t[0] != "p" or not self.conv(t[2], cctx[p]):
                    raise AuditError(f"constructor {c['name']}: parameters differ from the type's")
                t = subst(t[3], t[1], ("v", p))
            fields = []                       # (var, rec) rec = None | (xs, idx_args)
            while t[0] == "p":
                f = fresh(t[1].split("#")[0] or "a")
                cctx[f] = t[2]
                xs, cod = self.open_pis(t[2], cctx)
                h, args = spine(cod)
                rec = None
                if h == ("c", name):
                    if len(args) != nparams + ni:
                        raise AuditError(f"constructor {c['name']}: wrong arity in recursive field")
                    if any(a != ("v", p) for a, p in zip(args[:nparams], P)):
                        raise AuditError(f"constructor {c['name']}: non-uniform parameters")
                    if any(occurs_const(cctx[x], name) for x in xs) or any(occurs_const(a, name) for a in args[nparams:]):
                        raise AuditError(f"constructor {c['name']}: field is not strictly positive")
                    for x in xs:
                        if self.sort(cctx[x], cctx) > u:
                            raise AuditError(f"constructor {c['name']}: universe too large")
                    rec = (xs, args[nparams:])
                else:
                    if occurs_const(t[2], name):
                        raise AuditError(f"constructor {c['name']}: non-positive occurrence")
                    if self.sort(t[2], cctx) > u:
                        raise AuditError(f"constructor {c['name']}: universe too large")
                fields.append((f, rec))
                t = subst(t[3], t[1], ("v", f))
            h, args = spine(t)
            if h != ("c", name) or len(args) != nparams + ni or any(a != ("v", p) for a, p in zip(args[:nparams], P)):
                raise AuditError(f"constructor {c['name']}: bad result type")
            if any(occurs_const(a, name) for a in args[nparams:]):
                raise AuditError(f"constructor {c['name']}: result index mentions the type")
            info.append((c["name"], fields, args[nparams:], cctx))
        # regenerate every recursor and compare with the certificate's
        nm = len(ctors)
        for k, rc in enumerate(recs):
            rname = rc["name"]
            expect_name = name + (".rec" if k == 0 else f".rec_{k}")
            if rname != expect_name or rc["k"] != k:
                raise AuditError(f"unexpected recursor {rname}")
            gctx = dict(ctx)
            for c_name, fields, ridx, cctx in info:
                gctx.update(cctx)
            Iapp = lambda idx: apps(("c", name), [("v", p) for p in P] + idx)
            idxm = []
            t = ind["ty"]
            for p in P:
                t = subst(t[3], t[1], ("v", p))
            idxm, _ = self.open_pis(t, gctx)
            tm = fresh("t"); gctx[tm] = Iapp([("v", i) for i in idxm])
            M = fresh("motive"); gctx[M] = self.mkpi(idxm + [tm], ("s", k), gctx)
            rname_c = ("c", rname)
            minors, rdata = [], []
            for c_name, fields, ridx, cctx in info:
                F = [f for f, _ in fields]
                ihs = []
                for f, rec in fields:
                    if rec is not None:
                        xs, ia = rec
                        ih = fresh(f.split("#")[0] + "_ih")
                        gctx[ih] = self.mkpi(xs, apps(("v", M), list(ia) + [apps(("v", f), [("v", x) for x in xs])]), gctx)
                        ihs.append((f, xs, ia, ih))
                capp = apps(("c", c_name), [("v", p) for p in P] + [("v", f) for f in F])
                mv = fresh("m_" + c_name)
                gctx[mv] = self.mkpi(F + [i[3] for i in ihs], apps(("v", M), list(ridx) + [capp]), gctx)
                minors.append(mv)
                rdata.append((c_name, F, ihs, mv))
            t = ind["ty"]
            for p in P:
                t = subst(t[3], t[1], ("v", p))
            idx2, _ = self.open_pis(t, gctx)
            tt = fresh("t"); gctx[tt] = Iapp([("v", i) for i in idx2])
            rty = self.mkpi(P + [M] + minors + idx2 + [tt], apps(("v", M), [("v", i) for i in idx2] + [("v", tt)]), gctx)
            if not self.conv(rty, rc["ty"]):
                raise AuditError(f"recursor {rname}: type differs from the re-derived one")
            rules = {}
            for c_name, F, ihs, mv in rdata:
                ihterms = []
                for f, xs, ia, _ in ihs:
                    ihterms.append(self.mklam(xs, apps(rname_c, [("v", p) for p in P] + [("v", M)] + [("v", m) for m in minors]
                                                       + list(ia) + [apps(("v", f), [("v", x) for x in xs])]), gctx))
                body = apps(("v", mv), [("v", f) for f in F] + ihterms)
                rules[c_name] = (self.mklam(P + [M] + minors + F, body, gctx), len(F))
            # register our own regenerated recursor first (rules may mention it), then compare
            self.env[rname] = Decl("rec", rname, rty, info={"ind": name, "k": k, "nparams": nparams, "nminors": nm,
                                                            "arity": nparams + 1 + nm + ni + 1, "rules": rules})
            for c_name, (rule, nf) in rules.items():
                theirs = rc["rules"].get(c_name)
                if theirs is None or theirs[1] != nf or not self.conv(rule, theirs[0]):
                    raise AuditError(f"recursor {rname}: ι-rule for {c_name} differs from the re-derived one")
            self.sort(rty, {})
        res.inductives += 1


def to_named(j):
    return from_json(j, [])


def audit_certificate(cert):
    res = Result()
    a = Auditor()
    decls = cert["decls"]
    i = 0
    while i < len(decls):
        d = decls[i]
        kind, name = d["kind"], d["name"]
        try:
            if kind == "axiom":
                ty = to_named(d["ty"])
                a.sort(ty, {})
                a.env[name] = Decl("axiom", name, ty)
                res.checked += 1
                i += 1
            elif kind in ("def", "theorem"):
                ty, val = to_named(d["ty"]), to_named(d["val"])
                a.sort(ty, {})
                a.check(val, ty, {})
                a.env[name] = Decl("def" if kind == "def" else "theorem", name, ty, val if kind == "def" else None)
                res.checked += 1
                if kind == "theorem":
                    res.theorems += 1
                i += 1
            elif kind == "ind":
                nctors = d["nctors"]
                cts = [{"name": c["name"], "ty": to_named(c["ty"])} for c in decls[i + 1:i + 1 + nctors]]
                recs = []
                for r in decls[i + 1 + nctors:i + 1 + nctors + d["nrecs"]]:
                    recs.append({"name": r["name"], "k": r["k"], "ty": to_named(r["ty"]),
                                 "rules": {c: (to_named(t), nf) for c, (t, nf) in r["rules"].items()}})
                if any(c["kind"] != "ctor" for c in decls[i + 1:i + 1 + nctors]) or \
                        any(r["kind"] != "rec" for r in decls[i + 1 + nctors:i + 1 + nctors + d["nrecs"]]):
                    raise AuditError("malformed inductive package")
                a.add_inductive({"name": name, "nparams": d["nparams"], "ty": to_named(d["ty"])}, cts, recs, res)
                res.checked += 1 + nctors + d["nrecs"]
                i += 1 + nctors + d["nrecs"]
            else:
                raise AuditError(f"unexpected declaration kind {kind}")
        except AuditError as e:
            res.fail(name, str(e))
            return res
        except RecursionError:
            res.fail(name, "recursion limit while checking")
            return res
    return res


# ---------------------------------------------------------------- export / import
def term_json(t):
    from .terms import Var, Sort, Const, App, Pi, Lam
    if isinstance(t, Var):
        return ["var", t.i]
    if isinstance(t, Sort):
        return ["sort", t.n]
    if isinstance(t, Const):
        return ["const", t.name]
    if isinstance(t, App):
        return ["app", term_json(t.f), term_json(t.a)]
    if isinstance(t, Pi):
        return ["pi", t.name, term_json(t.dom), term_json(t.cod)]
    if isinstance(t, Lam):
        return ["lam", t.name, term_json(t.dom), term_json(t.body)]
    raise ValueError("cannot export non-closed term")


def export_certificate(sess, path):
    k = sess.k
    out = []
    for name in k.order:
        d = k.decls[name]
        if d.kind == "axiom":
            out.append({"kind": "axiom", "name": name, "ty": term_json(d.ty)})
        elif d.kind in ("def", "theorem"):
            out.append({"kind": d.kind, "name": name, "ty": term_json(d.ty), "val": term_json(d.val)})
        elif d.kind == "ind":
            nrecs = sum(1 for n in k.order if n.startswith(name + ".rec") and k.decls[n].kind == "rec"
                        and k.decls[n].info.ind == name)
            out.append({"kind": "ind", "name": name, "ty": term_json(d.ty), "nparams": d.info.nparams,
                        "nctors": len(d.info.ctors), "nrecs": nrecs})
        elif d.kind == "ctor":
            out.append({"kind": "ctor", "name": name, "ty": term_json(d.ty)})
        elif d.kind == "rec":
            out.append({"kind": "rec", "name": name, "ty": term_json(d.ty), "k": d.info.k,
                        "rules": {c: [term_json(r), nf] for c, (r, nf) in d.info.rules.items()}})
    cert = {"version": 1, "decls": out}
    if path:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(cert, f)
    return cert


def load_certificate(path):
    with open(path, encoding="utf-8") as f:
        return json.load(f)
