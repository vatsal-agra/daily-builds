"""Finite-difference gradient checking.

For every parameter tensor that requires grad, perturbs each element by
+-eps, re-runs the (scalar-valued) function, and compares the numeric slope
to the analytic gradient produced by `Tensor.backward()`. This is the
independent oracle that proves the hand-derived backward passes in
tensor.py / nn.py are actually correct, the same discipline Cotangent
(2026-06-16) used for its scalar autodiff engine.
"""
import numpy as np


def numeric_grad(f, tensor, eps=1e-5):
    """f: () -> Tensor (scalar). Returns a numpy array the same shape as
    tensor.data holding the central-difference numeric gradient."""
    grad = np.zeros_like(tensor.data)
    it = np.nditer(tensor.data, flags=["multi_index"])
    orig = tensor.data.copy()
    while not it.finished:
        idx = it.multi_index
        old = orig[idx]
        tensor.data[idx] = old + eps
        plus = f().data.copy()
        tensor.data[idx] = old - eps
        minus = f().data.copy()
        tensor.data[idx] = old
        grad[idx] = (plus - minus) / (2 * eps)
        it.iternext()
    return grad


def check(f, tensors, eps=1e-5, tol=1e-4, names=None):
    """f: () -> scalar Tensor, freshly built from `tensors` each call.
    tensors: list of Tensor leaves to check gradients for.
    Returns (ok: bool, report: list[str])."""
    names = names or [f"t{i}" for i in range(len(tensors))]
    ok = True
    report = []
    for t in tensors:
        t.grad = None
    out = f()
    out.backward()
    analytic = [t.grad.copy() if t.grad is not None else np.zeros_like(t.data) for t in tensors]

    for t, a, name in zip(tensors, analytic, names):
        n = numeric_grad(f, t, eps=eps)
        denom = np.maximum(np.abs(a), np.abs(n)) + 1e-8
        rel_err = np.abs(a - n) / denom
        max_err = rel_err.max() if rel_err.size else 0.0
        passed = max_err < tol
        ok = ok and passed
        status = "OK" if passed else "FAIL"
        report.append(f"[{status}] {name}: shape={t.data.shape} max_rel_err={max_err:.3e}")
    return ok, report
