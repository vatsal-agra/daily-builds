"""Finite-difference gradient checking. This is Loom's proof of correctness:
every primitive `Tensor` op, and the full `GPT` model end to end, has its
analytic backward() gradient compared against a numerically estimated one
(central differences). Reused by both `loom.py gradcheck` (a live CLI
demonstration) and the automated test suite."""
import numpy as np

from .nn import GPT
from .tensor import Tensor, cat, cross_entropy, gelu

OP_CHECKS = [
    ("add (broadcast)", lambda a, b: a + b, [(3, 4), (4,)]),
    ("mul", lambda a, b: a * b, [(3, 4), (3, 4)]),
    ("sub", lambda a, b: a - b, [(3, 4), (3, 4)]),
    ("matmul", lambda a, b: a @ b, [(3, 4), (4, 5)]),
    ("batched matmul (broadcast)", lambda a, b: a @ b, [(2, 3, 4), (4, 5)]),
    ("pow", lambda a: a ** 3, [(3, 4)]),
    ("div", lambda a, b: a / (b.exp()), [(3, 4), (3, 4)]),
    ("exp", lambda a: a.exp(), [(3, 4)]),
    ("log", lambda a: a.exp().log(), [(3, 4)]),
    ("sqrt", lambda a: (a * a + 1.0).sqrt(), [(3, 4)]),
    ("tanh", lambda a: a.tanh(), [(3, 4)]),
    ("relu", lambda a: a.relu() * a, [(3, 4)]),
    ("reshape", lambda a: a.reshape(2, 6), [(3, 4)]),
    ("transpose (2d)", lambda a: a.transpose(1, 0), [(3, 4)]),
    ("transpose (4d permute)", lambda a: a.transpose(0, 2, 1, 3), [(2, 3, 4, 5)]),
    ("getitem (slice)", lambda a: a[1:3, :], [(5, 4)]),
    ("getitem (fancy, repeated idx)", lambda a: a[np.array([0, 2, 2, 1])], [(5, 4)]),
    ("softmax", lambda a: a.softmax(-1), [(3, 4)]),
    ("log_softmax", lambda a: a.log_softmax(-1), [(3, 4)]),
    ("gelu", lambda a: gelu(a), [(3, 4)]),
    ("cat", lambda a, b: cat([a, b], axis=1), [(3, 4), (3, 2)]),
    ("masked_fill + softmax", lambda a: a.masked_fill(
        np.array([[True, False, True, False]] * 3), -1e9).softmax(-1), [(3, 4)]),
    ("cross_entropy", lambda a: cross_entropy(a, np.array([0, 1, 2])), [(3, 4)]),
]


def _scalarize(out, weight):
    if out.ndim == 0:
        return out
    return (out * Tensor(weight)).sum()


def check_op(build_fn, shapes, seed=0, eps=1e-5):
    rng = np.random.RandomState(seed)
    arrs = [rng.randn(*s) * 0.5 for s in shapes]

    probe = build_fn(*[Tensor(a.copy()) for a in arrs])
    weight = None if probe.ndim == 0 else rng.randn(*probe.shape)

    def scalar_loss(tensors):
        return _scalarize(build_fn(*tensors), weight)

    ts = [Tensor(a.copy(), requires_grad=True) for a in arrs]
    loss = scalar_loss(ts)
    loss.backward()
    analytic = [t.grad.copy() for t in ts]

    worst = 0.0
    for i, a in enumerate(arrs):
        numeric = np.zeros_like(a)
        it = np.nditer(a, flags=["multi_index"])
        for _ in it:
            idx = it.multi_index
            orig = a[idx]
            a[idx] = orig + eps
            l1 = float(scalar_loss([Tensor(x.copy(), requires_grad=True) for x in arrs]).data)
            a[idx] = orig - eps
            l2 = float(scalar_loss([Tensor(x.copy(), requires_grad=True) for x in arrs]).data)
            a[idx] = orig
            numeric[idx] = (l1 - l2) / (2 * eps)
        relerr = np.max(np.abs(numeric - analytic[i])) / (np.max(np.abs(numeric)) + 1e-8)
        worst = max(worst, float(relerr))
    return worst


def check_ops(tol=1e-3):
    results = []
    for name, fn, shapes in OP_CHECKS:
        err = check_op(fn, shapes)
        results.append((name, err <= tol, err))
    return results


def check_model(vocab_size=6, dim=8, n_layer=2, n_head=2, max_len=5, seed=42,
                 n_samples=6, eps=1e-5, tol=1e-3):
    """Gradient-check every parameter of a real (tiny) GPT through a full
    forward -> cross_entropy -> backward pass, spot-checking a handful of
    random scalar entries per parameter tensor (full enumeration would be
    slow but is exactly what check_ops does for individual primitives)."""
    rng = np.random.RandomState(seed)
    model = GPT(vocab_size=vocab_size, dim=dim, n_layer=n_layer, n_head=n_head, max_len=max_len, seed=seed)
    params = model.parameters()
    B, T = 2, max_len - 1
    idx = rng.randint(0, vocab_size, (B, T))
    targets = rng.randint(0, vocab_size, (B, T))

    def loss_fn():
        logits = model.forward(idx)
        return cross_entropy(logits.reshape(B * T, logits.shape[-1]), targets.reshape(-1))

    model.zero_grad()
    loss = loss_fn()
    loss.backward()
    analytic = [p.grad.copy() for p in params]

    worst = 0.0
    n_checked = 0
    for pi, p in enumerate(params):
        flat = p.data.reshape(-1)
        n_check = min(n_samples, flat.size)
        idxs = rng.choice(flat.size, n_check, replace=False)
        for fi in idxs:
            orig = flat[fi]
            flat[fi] = orig + eps
            l1 = loss_fn().item()
            flat[fi] = orig - eps
            l2 = loss_fn().item()
            flat[fi] = orig
            numeric = (l1 - l2) / (2 * eps)
            analytic_g = analytic[pi].reshape(-1)[fi]
            rel = abs(numeric - analytic_g) / (abs(numeric) + abs(analytic_g) + 1e-8)
            worst = max(worst, rel)
            n_checked += 1
    return worst <= tol, worst, n_checked
