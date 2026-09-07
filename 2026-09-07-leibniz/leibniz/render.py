"""Render an expression tree to a human-readable string or to LaTeX."""

from __future__ import annotations

from .expr import Add, Constant, Expr, Func, Imaginary, Mul, Num, Pow, Symbol

_LATEX_FUNC = {
    "sin": r"\sin", "cos": r"\cos", "tan": r"\tan",
    "exp": r"\exp", "ln": r"\ln",
}


def _num_str(v) -> str:
    if v.denominator == 1:
        return str(v.numerator)
    return f"{v.numerator}/{v.denominator}"


def _is_negative(t: Expr) -> bool:
    if isinstance(t, Num):
        return t.value < 0
    if isinstance(t, Mul) and isinstance(t.args[0], Num):
        return t.args[0].value < 0
    return False


def _negate(t: Expr):
    from .expr import mul

    return mul(Num(-1), t)


def _atom_str(e: Expr, fn) -> str:
    """Render e, parenthesizing if it isn't already a single 'atomic' token."""
    s = fn(e)
    if isinstance(e, (Num, Symbol)) and not (isinstance(e, Num) and e.value < 0):
        return s
    if isinstance(e, Func):
        return s
    return f"({s})"


def to_str(e: Expr) -> str:
    if isinstance(e, Num):
        return _num_str(e.value)
    if isinstance(e, Imaginary):
        return "i"
    if isinstance(e, Constant):
        return e.name
    if isinstance(e, Symbol):
        return e.name
    if isinstance(e, Func):
        return f"{e.name}({to_str(e.arg)})"
    if isinstance(e, Pow):
        if isinstance(e.exp, Num) and e.exp.value < 0:
            from .expr import pow_

            positive = pow_(e.base, Num(-e.exp.value))
            return f"1/{_atom_str(positive, to_str)}"
        base_s = _atom_str(e.base, to_str)
        exp_s = _atom_str(e.exp, to_str)
        return f"{base_s}^{exp_s}"
    if isinstance(e, Mul):
        num_factors, den_factors = [], []
        for f in e.args:
            if isinstance(f, Pow) and isinstance(f.exp, Num) and f.exp.value < 0:
                from .expr import pow_

                den_factors.append(pow_(f.base, Num(-f.exp.value)))
            else:
                num_factors.append(f)

        def part(f):
            return f"({to_str(f)})" if isinstance(f, Add) else to_str(f)

        neg = len(num_factors) > 1 and isinstance(num_factors[0], Num) and num_factors[0].value == -1
        if neg:
            num_factors = num_factors[1:]
        num_s = "*".join(part(f) for f in num_factors) or "1"
        if neg:
            num_s = f"-{num_s}"
        if den_factors:
            den_s = "*".join(part(f) for f in den_factors)
            if len(den_factors) > 1:
                den_s = f"({den_s})"
            return f"{num_s}/{den_s}"
        return num_s
    if isinstance(e, Add):
        pieces = []
        for i, t in enumerate(e.args):
            neg = _is_negative(t)
            s = to_str(_negate(t)) if neg else to_str(t)
            if i == 0:
                pieces.append(f"-{s}" if neg else s)
            else:
                pieces.append(f" - {s}" if neg else f" + {s}")
        return "".join(pieces)
    raise TypeError(type(e))


def _latex_atom(e: Expr) -> str:
    s = to_latex(e)
    if isinstance(e, (Num, Symbol)) and not (isinstance(e, Num) and e.value < 0):
        return s
    if isinstance(e, Func):
        return s
    return f"\\left({s}\\right)"


def to_latex(e: Expr) -> str:
    if isinstance(e, Num):
        v = e.value
        if v.denominator == 1:
            return str(v.numerator)
        sign = "-" if v < 0 else ""
        return f"{sign}\\frac{{{abs(v.numerator)}}}{{{v.denominator}}}"
    if isinstance(e, Imaginary):
        return "i"
    if isinstance(e, Constant):
        return {"pi": r"\pi", "e": "e"}.get(e.name, e.name)
    if isinstance(e, Symbol):
        return e.name
    if isinstance(e, Func):
        if e.name == "sqrt":
            return f"\\sqrt{{{to_latex(e.arg)}}}"
        if e.name == "abs":
            return f"\\left|{to_latex(e.arg)}\\right|"
        return f"{_LATEX_FUNC[e.name]}\\left({to_latex(e.arg)}\\right)"
    if isinstance(e, Pow):
        if isinstance(e.exp, Num) and e.exp.value == -1:
            return f"\\frac{{1}}{{{to_latex(e.base)}}}"
        return f"{_latex_atom(e.base)}^{{{to_latex(e.exp)}}}"
    if isinstance(e, Mul):
        # render a*b^-1 as \frac{a}{b}
        num_factors = [f for f in e.args if not (isinstance(f, Pow) and isinstance(f.exp, Num) and f.exp.value < 0)]
        den_factors = []
        for f in e.args:
            if isinstance(f, Pow) and isinstance(f.exp, Num) and f.exp.value < 0:
                from .expr import pow_

                den_factors.append(pow_(f.base, Num(-f.exp.value)))
        if den_factors:
            # a \frac{}{} already groups its contents, so a lone factor on
            # either side doesn't need _latex_atom's extra \left(\right)
            num = (" \\cdot ".join(_latex_atom(f) for f in num_factors) or "1") if len(num_factors) != 1 else to_latex(num_factors[0])
            den = " \\cdot ".join(_latex_atom(f) for f in den_factors) if len(den_factors) != 1 else to_latex(den_factors[0])
            return f"\\frac{{{num}}}{{{den}}}"
        return " \\cdot ".join(_latex_atom(f) for f in e.args)
    if isinstance(e, Add):
        pieces = []
        for i, t in enumerate(e.args):
            neg = _is_negative(t)
            s = to_latex(_negate(t)) if neg else to_latex(t)
            if i == 0:
                pieces.append(f"-{s}" if neg else s)
            else:
                pieces.append(f" - {s}" if neg else f" + {s}")
        return "".join(pieces)
    raise TypeError(type(e))


def to_tree(e: Expr) -> dict:
    """A small JSON-serializable tree, used by the HTML visualizer to draw
    the real expression structure rather than just its rendered string."""
    if isinstance(e, Num):
        return {"type": "Num", "label": _num_str(e.value)}
    if isinstance(e, Imaginary):
        return {"type": "Imaginary", "label": "i"}
    if isinstance(e, Constant):
        return {"type": "Constant", "label": e.name}
    if isinstance(e, Symbol):
        return {"type": "Symbol", "label": e.name}
    if isinstance(e, Func):
        return {"type": "Func", "label": e.name, "children": [to_tree(e.arg)]}
    if isinstance(e, Pow):
        return {"type": "Pow", "label": "^", "children": [to_tree(e.base), to_tree(e.exp)]}
    if isinstance(e, Mul):
        return {"type": "Mul", "label": "*", "children": [to_tree(a) for a in e.args]}
    if isinstance(e, Add):
        return {"type": "Add", "label": "+", "children": [to_tree(a) for a in e.args]}
    raise TypeError(type(e))


class Steps:
    """Records a human-readable derivation trail for the CLI's --steps flag
    and for the HTML visualizer."""

    def __init__(self):
        self.entries: list[dict] = []

    def add(self, label: str, expr: Expr, note: str = ""):
        self.entries.append({
            "label": label,
            "expr": to_str(expr),
            "latex": to_latex(expr),
            "tree": to_tree(expr),
            "note": note,
        })

    def to_json(self):
        return list(self.entries)
