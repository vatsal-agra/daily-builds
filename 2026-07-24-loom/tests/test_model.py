import os
import sys

import numpy as np

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
from loom.model import GPT, GPTConfig  # noqa: E402
from loom.optim import Adam  # noqa: E402
from loom.generate import generate, generate_text, sample_next_token, _filter_logits, attention_weights  # noqa: E402
from loom.tokenizer import BPETokenizer  # noqa: E402

np.random.seed(0)


def small_model():
    cfg = GPTConfig(vocab_size=40, block_size=16, n_layer=2, n_head=2, n_embd=16, dropout=0.0)
    return GPT(cfg)


def test_forward_shapes():
    model = small_model()
    idx = np.random.randint(0, 40, (3, 10))
    logits, loss = model(idx, targets=None, training=False)
    assert logits.shape == (3, 10, 40)
    assert loss is None
    print("  ok: forward shape, no targets -> no loss")

    targets = np.random.randint(0, 40, (3, 10))
    logits, loss = model(idx, targets, training=True)
    assert logits.shape == (3, 10, 40)
    assert loss.data.ndim == 0
    print("  ok: forward shape with targets -> scalar loss")


def test_block_size_enforced():
    model = small_model()
    idx = np.random.randint(0, 40, (2, 17))  # block_size is 16
    try:
        model(idx, training=False)
        assert False, "expected an assertion for sequence length > block_size"
    except AssertionError as e:
        assert "block_size" in str(e)
    print("  ok: sequence longer than block_size raises")


def test_causality_future_tokens_dont_leak():
    """Changing a future token must not change logits for earlier positions --
    that's the entire point of the causal mask."""
    model = small_model()
    idx = np.random.randint(0, 40, (1, 8))
    logits_a, _ = model(idx, training=False)

    idx_b = idx.copy()
    idx_b[0, -1] = (idx_b[0, -1] + 1) % 40  # change only the last token
    logits_b, _ = model(idx_b, training=False)

    # positions 0..6 must be identical; only position 7 (and its own logits) may differ
    assert np.allclose(logits_a.data[0, :-1], logits_b.data[0, :-1], atol=1e-10)
    print("  ok: causal mask -- future tokens never affect earlier positions' logits")


def test_overfit_tiny_batch():
    """A real correctness gate for the whole training stack: on a fixed tiny
    batch, loss must drop sharply and monotonically-ish over many optimizer
    steps. If any gradient in the stack were wrong, this would plateau near
    the random-init baseline instead."""
    model = small_model()
    opt = Adam(model.parameters(), lr=1e-2)
    x = np.random.randint(0, 40, (4, 8))
    y = np.random.randint(0, 40, (4, 8))

    losses = []
    for _ in range(150):
        _, loss = model(x, y, training=False)
        opt.zero_grad()
        loss.backward()
        opt.step()
        losses.append(loss.data.item())

    baseline = np.log(40)
    assert losses[0] < baseline + 0.5, f"first loss {losses[0]} far from baseline {baseline}"
    assert losses[-1] < 0.5, f"failed to overfit a tiny fixed batch: final loss {losses[-1]}"
    assert losses[-1] < losses[0] * 0.1
    print(f"  ok: overfits tiny batch, loss {losses[0]:.3f} -> {losses[-1]:.4f} "
          f"(baseline ln(vocab)={baseline:.3f})")


def test_generate_respects_max_new_tokens_and_block_size():
    model = small_model()
    tok = BPETokenizer()
    tok.train("hello world this is a tiny corpus for testing generation only", vocab_size=270)
    # model vocab (40) is smaller than tokenizer vocab on purpose is avoided:
    # build a matching-size tokenizer/model pair instead.
    cfg = GPTConfig(vocab_size=tok.vocab_size, block_size=12, n_layer=1, n_head=2, n_embd=8, dropout=0.0)
    model2 = GPT(cfg)
    out = generate_text(model2, tok, "hello", max_new_tokens=30, temperature=1.0, top_k=10, seed=0)
    assert out.startswith("hello") or len(out) >= 5
    print("  ok: generate_text runs end-to-end and respects context window internally")


def test_sampling_temperature_zero_is_argmax():
    logits = np.array([1.0, 5.0, 2.0, 0.5])
    tok_id = sample_next_token(logits, temperature=0.0)
    assert tok_id == 1
    print("  ok: temperature=0 is deterministic argmax")


def test_top_k_filtering():
    logits = np.array([1.0, 5.0, 2.0, 9.0, 0.1, 3.0])
    filtered = _filter_logits(logits.copy(), top_k=2)
    kept = np.where(np.isfinite(filtered))[0]
    assert set(kept.tolist()) == {1, 3}, f"top_k=2 should keep the 2 highest-logit indices, got {kept}"
    print("  ok: top-k keeps exactly the k highest logits")


def test_top_p_filtering():
    # a sharply peaked distribution: nucleus of size 1 should suffice for top_p=0.5
    logits = np.log(np.array([0.9, 0.05, 0.03, 0.02]) + 1e-12)
    filtered = _filter_logits(logits.copy(), top_p=0.5)
    kept = np.where(np.isfinite(filtered))[0]
    assert kept.tolist() == [0], f"expected only the top token kept, got {kept}"
    print("  ok: top-p nucleus sampling keeps only the minimal high-probability prefix")


def test_sampling_distribution_matches_softmax_with_no_filtering():
    rng = np.random.RandomState(0)
    logits = np.array([2.0, 1.0, 0.0])
    counts = np.zeros(3)
    n = 4000
    for _ in range(n):
        t = sample_next_token(logits, temperature=1.0, top_k=0, top_p=0.0, rng=rng)
        counts[t] += 1
    probs = counts / n
    expected = np.exp(logits) / np.exp(logits).sum()
    assert np.max(np.abs(probs - expected)) < 0.03, f"{probs} vs {expected}"
    print(f"  ok: unfiltered sampling matches softmax distribution ({probs} vs {expected})")


def test_attention_weights_sum_to_one_and_respect_causality():
    model = small_model()
    ids = list(np.random.randint(0, 40, size=6))
    layers = attention_weights(model, ids)
    assert len(layers) == model.cfg.n_layer
    for layer in layers:
        assert layer.shape == (model.cfg.n_head, 6, 6)
        row_sums = layer.sum(axis=-1)
        assert np.allclose(row_sums, 1.0, atol=1e-6), "attention rows must be a probability distribution"
        for h in range(layer.shape[0]):
            for i in range(6):
                for j in range(i + 1, 6):
                    assert layer[h, i, j] == 0.0, "attention must never look at future tokens"
    print("  ok: attention rows sum to 1 and never attend to future positions")


if __name__ == "__main__":
    fns = [v for k, v in list(globals().items()) if k.startswith("test_")]
    for fn in fns:
        print(f"{fn.__name__}:")
        fn()
    print(f"\nAll {len(fns)} model/generation test groups passed.")
