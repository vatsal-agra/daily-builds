"""Gradient checking for the from-scratch autograd engine: every op's
analytic gradient (computed by Tensor.backward()) is compared against a
central-difference numerical gradient on random inputs."""
import numpy as np

from loom.tensor import Tensor
from loom.functional import softmax, log_softmax, cross_entropy, layer_norm, gelu

RNG = np.random.default_rng(42)


def numeric_grad(f, x, eps=1e-6):
    """f: numpy array -> scalar. x: numpy array. Returns numeric d f/d x."""
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


def check(build_fn, shapes, tol=1e-4):
    """build_fn(*Tensors) -> scalar Tensor. Checks analytic vs numeric grad
    for every input tensor."""
    arrays = [RNG.normal(size=s) * 0.5 + 0.1 for s in shapes]

    tensors = [Tensor(a.copy(), requires_grad=True) for a in arrays]
    out = build_fn(*tensors)
    out.backward()
    analytic = [t.grad.copy() for t in tensors]

    for i, a in enumerate(arrays):
        def f(x, i=i):
            local = [Tensor(arr.copy()) for arr in arrays]
            local[i] = Tensor(x)
            return build_fn(*local).data.reshape(())[()] if build_fn(*local).data.shape == () \
                else float(build_fn(*local).data)
        num = numeric_grad(f, a.copy())
        assert np.allclose(analytic[i], num, atol=tol, rtol=1e-2), \
            f"grad mismatch on input {i}: analytic {analytic[i]} vs numeric {num}"


def test_add_mul():
    check(lambda a, b: (a * b + a).sum(), [(3, 4), (3, 4)])


def test_broadcast_add():
    check(lambda a, b: (a + b).sum(), [(3, 4), (1, 4)])


def test_broadcast_mul_vector():
    check(lambda a, b: (a * b).sum(), [(3, 4), (4,)])


def test_matmul():
    check(lambda a, b: (a @ b).sum(), [(3, 4), (4, 5)])


def test_matmul_batched_broadcast():
    check(lambda a, b: (a @ b).sum(), [(2, 3, 4), (4, 5)])


def test_pow_div():
    check(lambda a: ((a ** 2) / (a + 3.0)).sum(), [(3, 4)])


def test_exp_log():
    check(lambda a: (a.exp().log() * a).sum(), [(3, 4)])


def test_tanh():
    check(lambda a: a.tanh().sum(), [(3, 4)])


def test_reshape_transpose():
    check(lambda a: (a.reshape(4, 3).transpose(1, 0)).sum(), [(3, 4)])


def test_getitem():
    def f(a):
        return a[np.array([0, 2]), np.array([1, 3])].sum()
    check(f, [(3, 4)])


def test_cat():
    check(lambda a, b: Tensor.cat([a, b], axis=1).sum(), [(3, 4), (3, 2)])


def test_softmax_grad():
    check(lambda a: (softmax(a, axis=-1) * a).sum(), [(3, 4)])


def test_log_softmax_grad():
    check(lambda a: log_softmax(a, axis=-1).sum(), [(3, 4)])


def test_layer_norm_grad():
    def build(x, gamma, beta):
        return layer_norm(x, gamma, beta).sum()
    check(build, [(3, 4), (4,), (4,)])


def test_gelu_grad():
    check(lambda a: gelu(a).sum(), [(3, 4)])


def test_cross_entropy_grad():
    logits = Tensor(RNG.normal(size=(5, 6)), requires_grad=True)
    targets = np.array([0, 1, 2, 3, 4])
    loss = cross_entropy(logits, targets)
    loss.backward()
    analytic = logits.grad.copy()

    def f(x):
        return cross_entropy(Tensor(x), targets).item()
    num = numeric_grad(f, logits.data.copy())
    assert np.allclose(analytic, num, atol=1e-4, rtol=1e-2)


def test_embedding_gradient_accumulates_over_duplicate_indices():
    from loom.nn import Embedding
    rng = np.random.default_rng(0)
    emb = Embedding(10, 4, rng)
    idx = np.array([[0, 1, 0, 2]])  # row 0 looked up twice in the same batch

    out = emb(idx)
    loss = (out * out).sum()
    loss.backward()
    analytic = emb.weight.grad[0].copy()

    def f(x):
        w = emb.weight.data.copy()
        w[0] = x
        return float((w[idx] ** 2).sum())
    numeric = numeric_grad(f, emb.weight.data[0].copy())
    assert np.allclose(analytic, numeric, atol=1e-4)


def test_deep_chain_no_nan():
    a = Tensor(RNG.normal(size=(4, 4)) * 0.1, requires_grad=True)
    x = a
    for _ in range(6):
        x = (x @ a).tanh()
    loss = (x * x).sum()
    loss.backward()
    assert np.isfinite(a.grad).all()
