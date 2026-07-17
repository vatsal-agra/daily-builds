"""Numerical gradient checking for every module in nn.py.

This is the correctness gate for the from-scratch backward pass: for every
parameter (and the input), perturb by +/-eps and compare the finite-difference
slope of the loss to the analytic gradient computed by backward(). If these
disagree, the hand-derived math is wrong -- no amount of training will fix it.
"""
import numpy as np

from nn import Linear, LayerNorm, Embedding, CausalSelfAttention, MLP, Block, GPT, cross_entropy_loss

np.random.seed(0)


def rel_error(a, b):
    return np.max(np.abs(a - b) / (np.maximum(1e-8, np.abs(a) + np.abs(b))))


def numeric_grad(f, x, eps=1e-5):
    grad = np.zeros_like(x)
    it = np.nditer(x, flags=["multi_index"])
    while not it.finished:
        idx = it.multi_index
        orig = x[idx]
        x[idx] = orig + eps
        fp = f()
        x[idx] = orig - eps
        fm = f()
        x[idx] = orig
        grad[idx] = (fp - fm) / (2 * eps)
        it.iternext()
    return grad


def scalar_loss(out):
    """A fixed, deterministic pseudo-loss so every module gets a nonzero,
    well-conditioned upstream gradient without needing a real loss function."""
    return float(np.sum(out * WEIGHTS[: out.size].reshape(out.shape)))


WEIGHTS = np.sin(np.arange(100000) * 0.7 + 0.3)  # deterministic, unit-scale-ish


def dloss_dout(out):
    return WEIGHTS[: out.size].reshape(out.shape)


def check_module(name, module, x, tol=3e-4, extra_forward=None):
    """x: input array. extra_forward: optional fn(module, x)->out overriding module.forward."""
    forward = extra_forward or module.forward
    out = forward(x)
    dout = dloss_dout(out)
    dx = module.backward(dout)

    failures = []

    if dx is not None:
        def f_x():
            return scalar_loss(forward(x))

        num_dx = numeric_grad(f_x, x)
        err = rel_error(dx, num_dx)
        status = "OK" if err < tol else "FAIL"
        if status == "FAIL":
            failures.append(f"{name}: dx rel_error={err:.2e}")
        print(f"  [{status}] {name}.dx        rel_error={err:.2e}")

    for pname, p, g in module.parameters():
        module.zero_grad()
        forward(x)  # rerun to repopulate cache after zero_grad (cache untouched, but be safe)
        dout2 = dloss_dout(module.forward(x))
        module.backward(dout2)
        analytic = g.copy()

        def f_p():
            return scalar_loss(forward(x))

        num_p = numeric_grad(f_p, p)
        err = rel_error(analytic, num_p)
        status = "OK" if err < tol else "FAIL"
        if status == "FAIL":
            failures.append(f"{name}.{pname}: rel_error={err:.2e}")
        print(f"  [{status}] {name}.{pname:12s} rel_error={err:.2e}")

    return failures


def main():
    all_failures = []

    print("Linear")
    x = np.random.randn(2, 3, 8)
    all_failures += check_module("Linear", Linear(8, 5), x)

    print("LayerNorm")
    x = np.random.randn(2, 3, 8) * 3 + 1
    all_failures += check_module("LayerNorm", LayerNorm(8), x)

    print("MLP")
    x = np.random.randn(2, 3, 8)
    all_failures += check_module("MLP", MLP(8, hidden_mult=2), x)

    print("CausalSelfAttention")
    x = np.random.randn(2, 4, 8)
    all_failures += check_module("CausalSelfAttention", CausalSelfAttention(8, n_heads=2), x)

    print("Block")
    x = np.random.randn(2, 4, 8)
    all_failures += check_module("Block", Block(8, n_heads=2), x)

    print("Embedding (params only, no dx)")
    emb = Embedding(10, 6)
    ids = np.array([[1, 2, 3], [4, 5, 1]])
    out = emb.forward(ids)
    dout = dloss_dout(out)
    emb.backward(dout)
    analytic = emb.grads["table"].copy()

    def f_table():
        return scalar_loss(emb.forward(ids))

    num_table = numeric_grad(f_table, emb.params["table"])
    err = rel_error(analytic, num_table)
    status = "OK" if err < 3e-4 else "FAIL"
    if status == "FAIL":
        all_failures.append(f"Embedding.table: rel_error={err:.2e}")
    print(f"  [{status}] Embedding.table    rel_error={err:.2e}")

    print("Full GPT (loss = cross_entropy)")
    model = GPT(vocab_size=12, block_size=6, n_layer=2, n_head=2, n_embd=8)
    idx = np.array([[1, 2, 3, 4, 5, 1], [2, 3, 1, 4, 5, 2]])
    targets = np.array([[2, 3, 4, 5, 1, 0], [3, 1, 4, 5, 2, 0]])

    def full_loss():
        logits = model.forward(idx)
        loss, _ = cross_entropy_loss(logits, targets)
        return loss

    model.zero_grad()
    logits = model.forward(idx)
    loss, dlogits = cross_entropy_loss(logits, targets)
    model.backward(dlogits)

    checked = 0
    for pname, p, g in model.parameters():
        if p.size > 40:
            # sample a handful of entries for large matrices to keep this fast
            flat_idx = np.random.choice(p.size, size=min(6, p.size), replace=False)
        else:
            flat_idx = np.arange(p.size)
        analytic_flat = g.reshape(-1)
        num_flat = np.zeros(len(flat_idx))
        p_flat = p.reshape(-1)
        for j, fi in enumerate(flat_idx):
            orig = p_flat[fi]
            p_flat[fi] = orig + 1e-5
            lp = full_loss()
            p_flat[fi] = orig - 1e-5
            lm = full_loss()
            p_flat[fi] = orig
            num_flat[j] = (lp - lm) / (2e-5)
        err = rel_error(analytic_flat[flat_idx], num_flat)
        status = "OK" if err < 3e-3 else "FAIL"
        if status == "FAIL":
            all_failures.append(f"GPT.{pname}: rel_error={err:.2e}")
        print(f"  [{status}] GPT.{pname:20s} rel_error={err:.2e} (n={len(flat_idx)})")
        checked += 1

    print()
    if all_failures:
        print(f"GRADIENT CHECK FAILED ({len(all_failures)} issues):")
        for f in all_failures:
            print(" -", f)
        raise SystemExit(1)
    else:
        print("ALL GRADIENT CHECKS PASSED.")


if __name__ == "__main__":
    main()
