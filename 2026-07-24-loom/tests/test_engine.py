"""Gradient checks for loom/engine.py: every op's analytic backward pass is
compared against a central-difference numerical gradient. This is the real
correctness gate for the autodiff engine -- a bug here means the model
would train (or fail to) silently, with no crash to point at the mistake.
"""
import os
import sys
import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from loom.engine import Tensor, layer_norm, embedding, cross_entropy, dropout  # noqa: E402

np.random.seed(0)


def numerical_grad(f, x, eps=1e-6):
    grad = np.zeros_like(x)
    it = np.nditer(x, flags=["multi_index"])
    while not it.finished:
        idx = it.multi_index
        orig = x[idx]
        x[idx] = orig + eps
        f_pos = f(x)
        x[idx] = orig - eps
        f_neg = f(x)
        x[idx] = orig
        grad[idx] = (f_pos - f_neg) / (2 * eps)
        it.iternext()
    return grad


def check(name, build_fn, data_shapes, atol=1e-4):
    """build_fn(*tensors) -> scalar Tensor loss. Checks grad of each input."""
    datas = [np.random.randn(*s) * 0.5 for s in data_shapes]

    def loss_of(datas_list):
        tensors = [Tensor(d.copy()) for d in datas_list]
        out = build_fn(*tensors)
        return out.data.item() if out.data.ndim == 0 else out.data.sum()

    tensors = [Tensor(d.copy()) for d in datas]
    out = build_fn(*tensors)
    assert out.data.ndim == 0, f"{name}: loss must be scalar for backward()"
    out.backward()

    for i, t in enumerate(tensors):
        def f(x, i=i):
            local = [d.copy() for d in datas]
            local[i] = x
            return loss_of(local)

        num = numerical_grad(f, datas[i].copy())
        analytic = t.grad
        max_err = np.max(np.abs(num - analytic))
        denom = np.max(np.abs(num)) + 1e-8
        rel_err = max_err / denom
        assert max_err < atol or rel_err < 1e-2, (
            f"{name} input {i}: grad mismatch, max_abs_err={max_err:.6f} rel_err={rel_err:.6f}\n"
            f"numerical=\n{num}\nanalytic=\n{analytic}"
        )
    print(f"  ok: {name}")


def test_add_broadcast():
    check("add (broadcast)", lambda a, b: (a + b).sum(), [(3, 4), (4,)])


def test_sub_neg():
    check("sub", lambda a, b: (a - b).sum(), [(3, 2), (3, 2)])


def test_mul_broadcast():
    check("mul (broadcast)", lambda a, b: (a * b).sum(), [(3, 4), (1, 4)])


def test_div_pow():
    check("div", lambda a, b: (a / b).sum(), [(3, 3), (3, 3)])
    check("pow", lambda a: (a ** 3).sum(), [(4,)])


def test_matmul_2d():
    check("matmul 2d", lambda a, b: (a @ b).sum(), [(3, 4), (4, 5)])


def test_matmul_batched():
    check("matmul batched", lambda a, b: (a @ b).sum(), [(2, 3, 4, 5), (2, 3, 5, 6)])


def test_transpose_reshape():
    check("transpose", lambda a: a.transpose(-1, -2).sum(), [(3, 4)])
    check("reshape", lambda a: a.reshape(2, 6).sum(), [(3, 4)])


def test_sum_mean():
    check("sum axis", lambda a: a.sum(axis=1).sum(), [(3, 4)])
    check("mean axis", lambda a: a.mean(axis=1).sum(), [(3, 4)])
    check("mean all", lambda a: a.mean(), [(3, 4)])


def test_exp_log():
    check("exp", lambda a: a.exp().sum(), [(4,)])
    x = np.abs(np.random.randn(4)) + 0.5
    t = Tensor(x)
    out = t.log().sum()
    out.backward()
    num = numerical_grad(lambda z: np.log(z).sum(), x.copy())
    assert np.max(np.abs(num - t.grad)) < 1e-4
    print("  ok: log")


def test_relu_gelu():
    check("relu", lambda a: a.relu().sum(), [(6,)])
    check("gelu", lambda a: a.gelu().sum(), [(6,)])


def test_softmax():
    check("softmax", lambda a: (a.softmax(axis=-1) * a).sum(), [(3, 5)])


def test_layer_norm():
    check(
        "layer_norm",
        lambda x, g, b: layer_norm(x, g, b).sum(),
        [(3, 5), (5,), (5,)],
    )


def test_embedding():
    weight = Tensor(np.random.randn(10, 4) * 0.3)
    idx = np.array([1, 3, 3, 7])
    out = embedding(weight, idx)
    loss = (out * out).sum()
    loss.backward()

    def f(w):
        return ((w[idx]) ** 2).sum()

    num = numerical_grad(f, weight.data.copy())
    assert np.max(np.abs(num - weight.grad)) < 1e-4
    print("  ok: embedding (repeated indices scatter-add correctly)")


def test_cross_entropy():
    logits = Tensor(np.random.randn(5, 7) * 0.4)
    targets = np.array([0, 6, 3, 3, 1])
    loss = cross_entropy(logits, targets)
    loss.backward()

    def f(x):
        shifted = x - x.max(axis=-1, keepdims=True)
        lse = np.log(np.exp(shifted).sum(axis=-1, keepdims=True))
        lp = shifted - lse
        return -lp[np.arange(5), targets].mean()

    num = numerical_grad(f, logits.data.copy())
    assert np.max(np.abs(num - logits.grad)) < 1e-4
    print("  ok: cross_entropy")

    # uniform logits -> loss should be near ln(vocab_size)
    uniform = Tensor(np.zeros((1, 7)))
    u_loss = cross_entropy(uniform, np.array([0]))
    assert abs(u_loss.data.item() - np.log(7)) < 1e-6
    print("  ok: cross_entropy baseline == ln(vocab_size)")


def test_dropout_eval_is_identity():
    x = Tensor(np.random.randn(4, 4))
    out = dropout(x, 0.5, training=False)
    assert np.array_equal(out.data, x.data)
    print("  ok: dropout eval-mode identity")


def test_dropout_train_scales_and_masks():
    np.random.seed(1)
    x = Tensor(np.ones((2000,)))
    out = dropout(x, 0.3, training=True)
    zeros = np.sum(out.data == 0.0)
    frac = zeros / 2000
    assert 0.2 < frac < 0.4, f"expected ~30% dropped, got {frac}"
    nonzero = out.data[out.data != 0.0]
    assert np.allclose(nonzero, 1.0 / 0.7)
    print("  ok: dropout train-mode mask fraction + inverted scaling")


def test_getitem_backward():
    x = Tensor(np.arange(12, dtype=np.float64).reshape(3, 4))
    out = x[1]
    loss = (out * out).sum()
    loss.backward()
    expected = np.zeros((3, 4))
    expected[1] = 2 * np.arange(4, 8)
    assert np.allclose(x.grad, expected)
    print("  ok: getitem backward")


if __name__ == "__main__":
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for fn in fns:
        print(f"{fn.__name__}:")
        fn()
    print(f"\nAll {len(fns)} engine gradient-check groups passed.")
