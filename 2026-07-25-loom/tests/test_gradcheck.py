"""
Numerical gradient check for every hand-written backward() in loom/layers.py
and for the full GPT model (including the tied embedding/output-head
gradient, which must sum contributions from two paths). No pytest — run
directly: `python3 tests/test_gradcheck.py`.
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loom.layers import Block, CausalSelfAttention, Embedding, GELU, LayerNorm, Linear, MLP
from loom.model import GPT, GPTConfig
from loom.tensor_ops import numerical_gradient

TOL = 1e-3


def check_layer(name, layer, x, rng):
    x = x.astype(np.float64)
    out = layer.forward(x)
    dout = rng.normal(size=out.shape)

    def f():
        return np.sum(layer.forward(x) * dout)

    layer.forward(x)
    dx_analytic = layer.backward(dout)
    dx_num = numerical_gradient(f, x, eps=1e-5)
    err = np.max(np.abs(dx_analytic - dx_num)) / (np.max(np.abs(dx_num)) + 1e-8)
    assert err < TOL, f"{name}: dx grad mismatch, relerr={err:.2e}"
    print(f"  {name}: dx relerr = {err:.2e}")

    for pname, p in layer.params().items():
        def fp():
            return np.sum(layer.forward(x) * dout)

        g_num = numerical_gradient(fp, p, eps=1e-5)
        g_an = layer.grads[pname]
        err = np.max(np.abs(g_an - g_num)) / (np.max(np.abs(g_num)) + 1e-8)
        assert err < TOL, f"{name}.{pname}: grad mismatch, relerr={err:.2e}"
        print(f"  {name}.{pname}: relerr = {err:.2e}")


def test_layers():
    rng = np.random.default_rng(0)
    x = rng.normal(size=(2, 3, 8))
    print("Layer gradient checks:")
    check_layer("Linear", Linear(8, 5, rng), x, rng)
    check_layer("LayerNorm", LayerNorm(8), x, rng)
    check_layer("GELU", GELU(), x, rng)
    check_layer("MLP", MLP(8, 16, rng), x, rng)
    check_layer("Attn", CausalSelfAttention(8, 2, n_ctx=6, rng=rng), x, rng)
    check_layer("Block", Block(8, 2, n_ctx=6, n_hidden=16, rng=rng), x, rng)


def test_embedding_grad():
    rng = np.random.default_rng(1)
    emb = Embedding(vocab_size=10, n_ctx=6, n_embd=4, rng=rng)
    idx = rng.integers(0, 10, size=(2, 5))

    def f():
        return np.sum(emb.forward(idx) * dout)

    out = emb.forward(idx)
    dout = rng.normal(size=out.shape)
    emb.forward(idx)
    emb.backward(dout)
    for pname in ("wte", "wpe"):
        p = emb.params()[pname]
        g_num = numerical_gradient(f, p, eps=1e-5)
        g_an = emb.grads[pname]
        err = np.max(np.abs(g_an - g_num)) / (np.max(np.abs(g_num)) + 1e-8)
        assert err < TOL, f"Embedding.{pname} grad mismatch, relerr={err:.2e}"
        print(f"  Embedding.{pname}: relerr = {err:.2e}")


def test_full_model_gradcheck():
    print("Full-model gradient check (including tied wte/head):")
    rng = np.random.default_rng(2)
    cfg = GPTConfig(vocab_size=20, n_ctx=6, n_embd=8, n_head=2, n_layer=2, n_hidden=16)
    model = GPT(cfg, seed=2)

    B, T = 2, 5
    idx = rng.integers(0, cfg.vocab_size, size=(B, T))
    targets = rng.integers(0, cfg.vocab_size, size=(B, T))

    model.loss(idx, targets)
    params = model.params()
    grads = model.grads
    max_err = 0.0
    n_checked = 0
    for pname, p in params.items():
        flat_size = p.size
        n_test = min(3, flat_size)
        test_idx = rng.choice(flat_size, size=n_test, replace=False)
        for fi in test_idx:
            multi = np.unravel_index(fi, p.shape)
            orig = p[multi]
            eps = 1e-5
            p[multi] = orig + eps
            l_plus, _ = model.loss(idx, targets)
            p[multi] = orig - eps
            l_minus, _ = model.loss(idx, targets)
            p[multi] = orig
            g_num = (l_plus - l_minus) / (2 * eps)
            g_an = grads[pname][multi]
            err = abs(g_an - g_num) / max(abs(g_num), 1e-8)
            max_err = max(max_err, err)
            n_checked += 1
    print(f"  checked {n_checked} params across {len(params)} tensors, max relerr = {max_err:.2e}")
    assert max_err < 1e-2, f"full model grad check failed, max relerr={max_err:.2e}"


def test_ignore_index():
    from loom.tensor_ops import cross_entropy_from_logits
    rng = np.random.default_rng(3)
    logits = rng.normal(size=(4, 10))
    targets = np.array([2, -1, 5, -1])
    loss, dlogits = cross_entropy_from_logits(logits, targets, ignore_index=-1)
    assert np.all(dlogits[1] == 0.0) and np.all(dlogits[3] == 0.0), "ignore_index rows must have zero grad"
    assert np.any(dlogits[0] != 0.0), "non-ignored rows must have nonzero grad"
    print("  ignore_index masking: OK")


if __name__ == "__main__":
    test_layers()
    test_embedding_grad()
    test_full_model_gradcheck()
    test_ignore_index()
    print("ALL GRADCHECK TESTS PASSED")
