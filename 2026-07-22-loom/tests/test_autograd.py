"""Gradient-check every autograd primitive against numerical finite differences.

This is the correctness bar for the whole project: it is not enough that
the transformer "runs" -- every backward rule has to match a numerical
gradient to a tight tolerance, or the model is silently training on wrong
gradients.
"""

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np
from loom.autograd import Tensor, Parameter, cat, softmax, layer_norm, gelu, masked_fill, embedding_lookup, cross_entropy

rng = np.random.default_rng(42)


def numerical_grad(f, x, eps=1e-6):
    """Central-difference gradient of scalar-valued f w.r.t. array x."""
    grad = np.zeros_like(x)
    it = np.nditer(x, flags=["multi_index"])
    for _ in it:
        idx = it.multi_index
        orig = x[idx]
        x[idx] = orig + eps
        f_plus = f(x)
        x[idx] = orig - eps
        f_minus = f(x)
        x[idx] = orig
        grad[idx] = (f_plus - f_minus) / (2 * eps)
    return grad


def check(name, build_fn, shapes, tol=2e-4):
    """``build_fn(*tensors) -> scalar Tensor``. Gradient-checks w.r.t. every input."""
    arrays = [rng.normal(0, 1, size=s) for s in shapes]
    failures = []
    for i in range(len(arrays)):
        def f(perturbed_val, i=i):
            local_arrays = [a.copy() for a in arrays]
            local_arrays[i] = perturbed_val
            tensors = [Parameter(a) for a in local_arrays]
            out = build_fn(*tensors)
            return out.data.item() if out.data.size == 1 else out.sum().data.item()

        numgrad = numerical_grad(f, arrays[i].copy())

        tensors = [Parameter(a) for a in arrays]
        out = build_fn(*tensors)
        loss = out if out.data.size == 1 else out.sum()
        loss.backward()
        angrad = tensors[i].grad

        diff = np.abs(numgrad - angrad)
        denom = np.maximum(np.abs(numgrad), np.abs(angrad)) + 1e-8
        relerr = (diff / denom).max()
        if relerr > tol:
            failures.append(f"  input {i}: max rel err {relerr:.2e}")

    status = "OK" if not failures else "FAIL"
    print(f"[{status}] {name}")
    for line in failures:
        print(line)
    return not failures


def run_all():
    results = []

    results.append(check("add (broadcast)", lambda a, b: a + b, [(3, 4), (4,)]))
    results.append(check("sub", lambda a, b: a - b, [(3, 4), (3, 4)]))
    results.append(check("mul (broadcast)", lambda a, b: a * b, [(2, 3, 4), (4,)]))
    results.append(check("div", lambda a, b: a / b, [(3, 4), (3, 4)]))
    results.append(check("neg", lambda a: -a, [(3, 4)]))
    results.append(check("pow", lambda a: a ** 3, [(3, 4)]))
    results.append(check("matmul 2D", lambda a, b: a.matmul(b), [(3, 4), (4, 5)]))
    results.append(check("matmul batched", lambda a, b: a.matmul(b), [(2, 3, 4), (2, 4, 5)]))
    results.append(check("matmul broadcast weight", lambda a, b: a.matmul(b), [(2, 3, 4), (4, 5)]))
    results.append(check("reshape", lambda a: a.reshape(2, 6), [(3, 4)]))
    results.append(check("transpose", lambda a: a.transpose(1, 0, 2), [(2, 3, 4)]))
    results.append(check("sum axis", lambda a: a.sum(axis=1), [(3, 4)]))
    results.append(check("mean axis", lambda a: a.mean(axis=-1), [(3, 4)]))
    results.append(check("exp", lambda a: a.exp(), [(3, 4)]))
    results.append(check("tanh", lambda a: a.tanh(), [(3, 4)]))
    results.append(check("sqrt", lambda a: (a * a + 1.0).sqrt(), [(3, 4)]))
    results.append(check("log", lambda a: (a * a + 1.0).log(), [(3, 4)]))
    # softmax rows always sum to exactly 1, so a plain `.sum()` objective has a
    # provably-zero gradient everywhere and can't distinguish a correct
    # backward rule from a broken one -- weight the output first.
    results.append(check("softmax", lambda a, w: (softmax(a, axis=-1) * w).sum(), [(3, 4), (3, 4)]))
    results.append(check("gelu", lambda a: gelu(a), [(3, 4)]))
    results.append(check("layer_norm", lambda x, g, b: layer_norm(x, g, b), [(3, 4), (4,), (4,)]))
    results.append(check("cat", lambda a, b: cat([a, b], axis=1), [(2, 3), (2, 2)]))

    def mf(a):
        mask = np.array([[True, False, False, True]] * 3)
        return masked_fill(a, mask, -100.0)
    results.append(check("masked_fill", mf, [(3, 4)]))

    def emb(table):
        idx = np.array([0, 2, 1, 2])
        return embedding_lookup(table, idx)
    results.append(check("embedding_lookup", emb, [(5, 3)]))

    def ce(logits):
        targets = np.array([0, 2, 1])
        return cross_entropy(logits, targets)
    results.append(check("cross_entropy", ce, [(3, 4)]))

    def gi(a):
        return a[:, 1:3]
    results.append(check("getitem slice", gi, [(3, 4)]))

    ok = all(results)
    print()
    print("ALL PASS" if ok else "SOME FAILED")
    return ok


if __name__ == "__main__":
    ok = run_all()
    sys.exit(0 if ok else 1)
