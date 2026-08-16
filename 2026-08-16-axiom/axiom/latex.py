"""Expression -> LaTeX rendering, used by the CLI (`--latex`) and the HTML
report's typeset display. Precedence-aware (parenthesizes exactly where the
plain-text printer in `expr.py` would), and renders fractions with `\\frac`,
`sqrt` with `\\sqrt`, and named functions/greek constants properly."""

from fractions import Fraction

from .expr import Add, Func, Mul, Num, Pow, Symbol, mul, num, power

_GREEK = {"pi": r"\pi", "theta": r"\theta", "alpha": r"\alpha", "beta": r"\beta",
          "gamma": r"\gamma", "delta": r"\delta", "epsilon": r"\epsilon",
          "lambda": r"\lambda", "mu": r"\mu", "sigma": r"\sigma", "phi": r"\phi",
          "omega": r"\omega"}

_FUNC_LATEX = {"sin": r"\sin", "cos": r"\cos", "tan": r"\tan", "log": r"\ln",
               "exp": r"\exp", "asin": r"\arcsin", "acos": r"\arccos",
               "atan": r"\arctan", "sinh": r"\sinh", "cosh": r"\cosh",
               "tanh": r"\tanh"}

_PRECEDENCE = {"add": 1, "mul": 2, "pow": 4}


def to_latex(e, parent_prec=0):
    if isinstance(e, Num):
        v = e.value
        if v.denominator == 1:
            return str(v.numerator)
        sign = "-" if v < 0 else ""
        return f"{sign}\\frac{{{abs(v.numerator)}}}{{{v.denominator}}}"
    if isinstance(e, Symbol):
        return _GREEK.get(e.name, e.name)
    if isinstance(e, Func):
        name = _FUNC_LATEX.get(e.name, f"\\operatorname{{{e.name}}}")
        return f"{name}\\left({to_latex(e.arg)}\\right)"
    if isinstance(e, Pow):
        if isinstance(e.exp, Num) and e.exp.value == Fraction(1, 2):
            return f"\\sqrt{{{to_latex(e.base)}}}"
        base_s = to_latex(e.base, _PRECEDENCE["pow"] + 1)
        exp_s = to_latex(e.exp)
        s = f"{{{base_s}}}^{{{exp_s}}}"
        return f"\\left({s}\\right)" if parent_prec > _PRECEDENCE["pow"] else s
    if isinstance(e, Mul):
        num_factors, den_factors = [], []
        for f in e.factors:
            if isinstance(f, Pow) and isinstance(f.exp, Num) and f.exp.value < 0:
                den_factors.append(power(f.base, num(-f.exp.value)))
            else:
                num_factors.append(f)
        if den_factors:
            num_s = _mul_latex(num_factors) if num_factors else "1"
            den_s = _mul_latex(den_factors)
            return f"\\frac{{{num_s}}}{{{den_s}}}"
        s = _mul_latex(num_factors)
        return f"\\left({s}\\right)" if parent_prec > _PRECEDENCE["mul"] else s
    if isinstance(e, Add):
        parts = []
        for i, t in enumerate(e.terms):
            s = to_latex(t, _PRECEDENCE["add"] + 1)
            if i == 0:
                parts.append(s)
            elif s.startswith("-"):
                parts.append(f" - {s[1:]}")
            else:
                parts.append(f" + {s}")
        s = "".join(parts)
        return f"\\left({s}\\right)" if parent_prec > _PRECEDENCE["add"] else s
    raise TypeError(type(e))


def _mul_latex(factors):
    if not factors:
        return "1"
    if len(factors) == 1:
        return to_latex(factors[0], _PRECEDENCE["mul"] + 1)
    if isinstance(factors[0], Num) and factors[0].value == -1:
        return f"-{_mul_latex(list(factors[1:]))}"
    return " \\cdot ".join(to_latex(f, _PRECEDENCE["mul"] + 1) for f in factors)
