"""Numerical gradient checking for every primitive op in loom/tensor.py,
plus a full mini forward+backward pass through a tiny transformer block.

For each op we build a small random input, run forward + backward to get
the analytic gradient, then perturb each input element by +-eps and use
central differences to get the numerical gradient. We report the maximum
relative error across all elements; a healthy op should be below ~1e-6
(float64, central differences, well-scaled inputs).
"""
from __future__ import annotations

import numpy as np

from loom.tensor import Tensor, embedding, gather_rows, softmax, layer_norm, gelu, cross_entropy

EPS = 1e-6
RNG = np.random.default_rng(0)


def _numeric_grad(f, x: np.ndarray) -> np.ndarray:
    grad = np.zeros_like(x)
    it = np.nditer(x, flags=["multi_index"])
    for _ in it:
        idx = it.multi_index
        orig = x[idx]
        x[idx] = orig + EPS
        plus = f()
        x[idx] = orig - EPS
        minus = f()
        x[idx] = orig
        grad[idx] = (plus - minus) / (2 * EPS)
    return grad


def _rel_error(a: np.ndarray, b: np.ndarray) -> float:
    denom = np.maximum(np.abs(a), np.abs(b))
    denom = np.where(denom < 1e-8, 1.0, denom)
    return float(np.max(np.abs(a - b) / denom))


def check_op(name, build_fn, tol=1e-4):
    """build_fn() -> (inputs: list[Tensor], loss_fn: () -> Tensor built fresh
    from `inputs`). We compute analytic grads once, then numeric grads by
    re-invoking loss_fn() (which must rebuild the graph from the *same*
    input arrays) for every perturbation."""
    inputs, loss_fn = build_fn()
    for t in inputs:
        t.zero_grad()
    loss = loss_fn()
    loss.backward()
    analytic = [t.grad.copy() if t.grad is not None else np.zeros_like(t.data) for t in inputs]

    worst = 0.0
    for i, t in enumerate(inputs):
        def f():
            for u in inputs:
                u.zero_grad()
            return float(loss_fn().data.sum())
        numeric = _numeric_grad(f, t.data)
        err = _rel_error(analytic[i], numeric)
        worst = max(worst, err)
    ok = worst < tol
    print(f"  {'OK ' if ok else 'FAIL'} {name:24s} max_rel_err={worst:.3e}")
    return ok


def run_all(verbose=True) -> bool:
    results = []

    def scalarize(t):
        return t.sum()

    # add / mul / sub / pow / div (with broadcasting)
    def build_add():
        a = Tensor(RNG.normal(size=(3, 4)), requires_grad=True)
        b = Tensor(RNG.normal(size=(4,)), requires_grad=True)
        return [a, b], lambda: scalarize(a + b)
    results.append(check_op("add (broadcast)", build_add))

    def build_mul():
        a = Tensor(RNG.normal(size=(3, 4)), requires_grad=True)
        b = Tensor(RNG.normal(size=(3, 4)), requires_grad=True)
        return [a, b], lambda: scalarize(a * b)
    results.append(check_op("mul", build_mul))

    def build_pow():
        a = Tensor(np.abs(RNG.normal(size=(3, 4))) + 0.5, requires_grad=True)
        return [a], lambda: scalarize(a ** 1.7)
    results.append(check_op("pow", build_pow))

    def build_div():
        a = Tensor(RNG.normal(size=(3, 4)), requires_grad=True)
        b = Tensor(np.abs(RNG.normal(size=(3, 4))) + 0.5, requires_grad=True)
        return [a, b], lambda: scalarize(a / b)
    results.append(check_op("div", build_div))

    def build_exp():
        a = Tensor(RNG.normal(size=(3, 4)) * 0.3, requires_grad=True)
        return [a], lambda: scalarize(a.exp())
    results.append(check_op("exp", build_exp))

    def build_log():
        a = Tensor(np.abs(RNG.normal(size=(3, 4))) + 0.5, requires_grad=True)
        return [a], lambda: scalarize(a.log())
    results.append(check_op("log", build_log))

    def build_tanh():
        a = Tensor(RNG.normal(size=(3, 4)), requires_grad=True)
        return [a], lambda: scalarize(a.tanh())
    results.append(check_op("tanh", build_tanh))

    def build_sum_mean():
        a = Tensor(RNG.normal(size=(3, 4, 5)), requires_grad=True)
        return [a], lambda: scalarize(a.sum(axis=1)) + scalarize(a.mean(axis=(1, 2)))
    results.append(check_op("sum/mean(axis)", build_sum_mean))

    def build_matmul():
        a = Tensor(RNG.normal(size=(2, 3, 4)), requires_grad=True)
        b = Tensor(RNG.normal(size=(4, 5)), requires_grad=True)
        return [a, b], lambda: scalarize(a @ b)
    results.append(check_op("matmul (batched)", build_matmul))

    def build_reshape_permute():
        a = Tensor(RNG.normal(size=(2, 3, 4)), requires_grad=True)
        return [a], lambda: scalarize(a.reshape(2, 12).reshape(2, 3, 4).permute(1, 0, 2))
    results.append(check_op("reshape+permute", build_reshape_permute))

    def build_softmax():
        a = Tensor(RNG.normal(size=(3, 5)), requires_grad=True)
        w = RNG.normal(size=(3, 5))
        return [a], lambda: scalarize(softmax(a, axis=-1) * Tensor(w))
    results.append(check_op("softmax", build_softmax))

    def build_layernorm():
        a = Tensor(RNG.normal(size=(3, 6)), requires_grad=True)
        gamma = Tensor(RNG.normal(size=(6,)) * 0.1 + 1.0, requires_grad=True)
        beta = Tensor(RNG.normal(size=(6,)), requires_grad=True)
        return [a, gamma, beta], lambda: scalarize(layer_norm(a, gamma, beta))
    results.append(check_op("layer_norm", build_layernorm))

    def build_gelu():
        a = Tensor(RNG.normal(size=(3, 6)), requires_grad=True)
        return [a], lambda: scalarize(gelu(a))
    results.append(check_op("gelu", build_gelu))

    def build_embedding():
        w = Tensor(RNG.normal(size=(8, 4)), requires_grad=True)
        idx = RNG.integers(0, 8, size=(2, 3))

        def loss_fn():
            return scalarize(embedding(w, idx))
        return [w], loss_fn
    results.append(check_op("embedding", build_embedding))

    def build_gather_rows():
        x = Tensor(RNG.normal(size=(5, 4)), requires_grad=True)
        idx = RNG.integers(0, 4, size=(5,))
        return [x], lambda: scalarize(gather_rows(x, idx))
    results.append(check_op("gather_rows", build_gather_rows))

    def build_cross_entropy():
        logits = Tensor(RNG.normal(size=(6, 5)), requires_grad=True)
        targets = RNG.integers(0, 5, size=(6,))
        return [logits], lambda: cross_entropy(logits, targets)
    results.append(check_op("cross_entropy", build_cross_entropy))

    # Full mini transformer block (attention + MLP + layernorm together)
    def build_block():
        from loom.model import Block
        d_model, n_head, T, B = 8, 2, 3, 2
        block = Block(d_model, n_head, block_size=T)
        x = Tensor(RNG.normal(size=(B, T, d_model)), requires_grad=True)
        params = [x] + block.parameters()

        def loss_fn():
            return scalarize(block(x))
        return params, loss_fn
    results.append(check_op("full transformer block", build_block, tol=1e-3))

    all_ok = all(results)
    if verbose:
        print(f"\n{sum(results)}/{len(results)} gradient checks passed.")
    return all_ok


if __name__ == "__main__":
    ok = run_all()
    raise SystemExit(0 if ok else 1)
