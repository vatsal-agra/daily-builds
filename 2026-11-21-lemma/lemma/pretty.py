"""Pretty printer: binder names, infix notation, numerals, `A -> B`, `fun`, `forall`."""
from .terms import Var, Sort, Const, App, Pi, Lam, Fv, Meta, BindF, unapps


class Notation:
    """Operator tables shared by the parser and the printer."""
    def __init__(self):
        self.infix = {}        # token -> (prec, assoc 'l'|'r'|'n', const name or '=')
        self.prefix = {}       # token -> (prec, const name)
        self.by_const = {}     # const name -> (token, prec, assoc)
        self.prefix_by_const = {}

    def add_infix(self, tok, prec, assoc, target):
        self.infix[tok] = (prec, assoc, target)
        self.by_const[target] = (tok, prec, assoc)

    def add_prefix(self, tok, prec, target):
        self.prefix[tok] = (prec, target)
        self.prefix_by_const[target] = (tok, prec)

    def symbols(self):
        return set(self.infix) | set(self.prefix)


def uses_var(t, i):
    if isinstance(t, Var):
        return t.i == i
    if isinstance(t, App):
        return uses_var(t.f, i) or uses_var(t.a, i)
    if isinstance(t, Pi):
        return uses_var(t.dom, i) or uses_var(t.cod, i + 1)
    if isinstance(t, Lam):
        return uses_var(t.dom, i) or uses_var(t.body, i + 1)
    if isinstance(t, BindF):
        return uses_var(t.body, i)
    return False


def show(t, names=None, kernel=None):
    return _Printer(kernel).go(t, list(names or []), 0)


ATOM, APP = 2000, 1000


class _Printer:
    def __init__(self, kernel):
        self.k = kernel
        self.nota = getattr(kernel, "notation", None) if kernel is not None else None

    def paren(self, s, need):
        return f"({s})" if need else s

    def fresh(self, name, names):
        n = name if name and name != "_" else "x"
        while n in names:
            n += "'"
        return n

    def numeral(self, t):
        n = 0
        while isinstance(t, App) and isinstance(t.f, Const) and t.f.name == "succ":
            n += 1
            t = t.a
        if isinstance(t, Const) and t.name == "zero":
            return n
        return None

    def go(self, t, names, prec):
        if isinstance(t, Var):
            return names[-1 - t.i] if t.i < len(names) else f"#{t.i}"
        if isinstance(t, Fv):
            return t.name
        if isinstance(t, Meta):
            return f"?{t.name}{t.id}" if t.name != "?" else f"?{t.id}"
        if isinstance(t, Const):
            if t.name == "zero" and self.k is not None and "succ" in self.k.decls:
                return "0"
            return t.name
        if isinstance(t, Sort):
            return "Type" if t.n == 0 else f"Type {t.n}"
        if isinstance(t, BindF):
            return self.go(t.body, names, prec)
        if isinstance(t, Pi):
            if not uses_var(t.cod, 0):
                s = self.go(t.dom, names, 21) + " -> " + self.go(t.cod, names + ["_"], 20)
                return self.paren(s, prec > 20)
            binders = []
            cur, nms = t, list(names)
            while isinstance(cur, Pi) and uses_var(cur.cod, 0):
                n = self.fresh(cur.name, nms)
                binders.append((n, self.go(cur.dom, nms, 0)))
                nms = nms + [n]
                cur = cur.cod
            groups = []
            for n, d in binders:
                if groups and groups[-1][1] == d:
                    groups[-1][0].append(n)
                else:
                    groups.append(([n], d))
            bs = " ".join(f"({' '.join(ns)} : {d})" for ns, d in groups)
            s = f"forall {bs}, " + self.go(cur, nms, 0)
            return self.paren(s, prec > 0)
        if isinstance(t, Lam):
            binders, cur, nms = [], t, list(names)
            while isinstance(cur, Lam):
                n = self.fresh(cur.name, nms)
                binders.append(f"({n} : {self.go(cur.dom, nms, 0)})")
                nms = nms + [n]
                cur = cur.body
            s = "fun " + " ".join(binders) + " => " + self.go(cur, nms, 0)
            return self.paren(s, prec > 0)
        if isinstance(t, App):
            num = self.numeral(t)
            if num is not None and self.k is not None and "succ" in self.k.decls:
                return str(num)
            h, args = unapps(t)
            if isinstance(h, Const) and self.nota is not None:
                if h.name == "Eq" and len(args) == 3 and "=" in self.nota.infix:
                    p = self.nota.infix["="][0]
                    s = self.go(args[1], names, p + 1) + " = " + self.go(args[2], names, p + 1)
                    return self.paren(s, prec > p)
                if h.name in self.nota.by_const and len(args) == 2:
                    tok, p, assoc = self.nota.by_const[h.name]
                    lp = p if assoc == "l" else p + 1
                    rp = p if assoc == "r" else p + 1
                    s = self.go(args[0], names, lp) + f" {tok} " + self.go(args[1], names, rp)
                    return self.paren(s, prec > p)
                if h.name in self.nota.prefix_by_const and len(args) == 1:
                    tok, p = self.nota.prefix_by_const[h.name]
                    return self.paren(tok + " " + self.go(args[0], names, p), prec > p)
            s = " ".join([self.go(h, names, ATOM)] + [self.go(a, names, ATOM) for a in args])
            return self.paren(s, prec > APP)
        return "<?>"
