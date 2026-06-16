"""Finite-difference gradient checking.

Given a scalar function ``f(inputs) -> Value`` where ``inputs`` is a list of
``Value`` leaves, compare the engine's analytic gradients against central
finite-difference estimates::

    df/dx_i  ~=  (f(x_i + h) - f(x_i - h)) / (2h)

We report the max relative error over all inputs. This is the project's honest
correctness gate: it verifies the chain-rule math, not merely that code runs.
"""

from __future__ import annotations

from typing import Callable

from engine import Value


def numeric_grad(f: Callable[[list[Value]], Value], xs: list[float],
                 h: float = 1e-5) -> list[float]:
    """Central-difference gradient of f at point xs (list of floats)."""
    grads = []
    for i in range(len(xs)):
        plus = list(xs)
        minus = list(xs)
        plus[i] += h
        minus[i] -= h
        fp = f([Value(v) for v in plus]).data
        fm = f([Value(v) for v in minus]).data
        grads.append((fp - fm) / (2 * h))
    return grads


def analytic_grad(f: Callable[[list[Value]], Value], xs: list[float]) -> list[float]:
    """Engine gradient of f at point xs via backward()."""
    inputs = [Value(v) for v in xs]
    out = f(inputs)
    out.backward()
    return [v.grad for v in inputs]


def rel_error(a: float, b: float) -> float:
    """Relative error robust to small magnitudes."""
    denom = max(abs(a), abs(b), 1e-12)
    return abs(a - b) / denom


def check(f: Callable[[list[Value]], Value], xs: list[float],
          h: float = 1e-5) -> dict:
    """Run a gradient check; return a report dict."""
    ana = analytic_grad(f, xs)
    num = numeric_grad(f, xs, h)
    errs = [rel_error(a, n) for a, n in zip(ana, num)]
    return {
        "xs": xs,
        "analytic": ana,
        "numeric": num,
        "rel_errors": errs,
        "max_rel_error": max(errs) if errs else 0.0,
    }


def report_str(name: str, rep: dict) -> str:
    lines = [f"[{name}]  max_rel_error={rep['max_rel_error']:.2e}"]
    for i, (a, n, e) in enumerate(zip(rep["analytic"], rep["numeric"],
                                      rep["rel_errors"])):
        lines.append(f"    x[{i}]: analytic={a:+.6f}  numeric={n:+.6f}  rel={e:.2e}")
    return "\n".join(lines)
