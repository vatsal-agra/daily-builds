import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import numpy as np

from loom.nn import LoomModel
from loom.autograd import cross_entropy
from loom.generate import generate, sample_from_logits
from loom.checkpoint import save_checkpoint, load_checkpoint
from loom.tokenizer import BPETokenizer


def _tiny_model(seed=0, vocab=64, dim=16, layers=2, heads=2, seqlen=16):
    return LoomModel(vocab_size=vocab, dim=dim, n_layers=layers, n_heads=heads, max_seq_len=seqlen, seed=seed)


def test_forward_shapes_and_all_params_get_gradient():
    model = _tiny_model()
    B, T = 3, 10
    rng = np.random.default_rng(0)
    ids = rng.integers(0, 64, size=(B, T))
    targets = rng.integers(0, 64, size=(B, T))
    logits, attn = model.forward(ids)
    assert logits.shape == (B, T, 64)
    assert len(attn) == 2
    assert attn[0].data.shape == (B, 2, T, T)

    loss = cross_entropy(logits.reshape(B * T, 64), targets.reshape(-1))
    loss.backward()
    for p in model.parameters():
        assert p.grad is not None
        assert np.isfinite(p.grad).all(), "non-finite gradient found"
    return True


def test_causal_mask_blocks_future_tokens():
    # Changing a future token must not change any earlier position's logits.
    model = _tiny_model()
    rng = np.random.default_rng(1)
    ids = rng.integers(0, 64, size=(1, 8))
    logits_a, _ = model.forward(ids)

    ids2 = ids.copy()
    ids2[0, -1] = (ids2[0, -1] + 1) % 64  # perturb only the last token
    logits_b, _ = model.forward(ids2)

    # positions 0..6 must be byte-for-byte identical; only position 7 may differ
    assert np.allclose(logits_a.data[:, :-1, :], logits_b.data[:, :-1, :]), \
        "a future token leaked into an earlier position's prediction"
    assert not np.allclose(logits_a.data[:, -1, :], logits_b.data[:, -1, :]), \
        "perturbing the last token should change its own logits"
    return True


def test_attention_rows_are_causal_and_sum_to_one():
    model = _tiny_model()
    rng = np.random.default_rng(2)
    ids = rng.integers(0, 64, size=(1, 8))
    _, attn = model.forward(ids)
    for layer_attn in attn:
        w = layer_attn.data[0]  # (H, T, T)
        # every row sums to 1 (it's a softmax distribution)
        assert np.allclose(w.sum(axis=-1), 1.0, atol=1e-6)
        # strictly-upper-triangular entries (future positions) must be exactly 0
        T = w.shape[-1]
        future_mask = np.triu(np.ones((T, T), dtype=bool), k=1)
        assert np.allclose(w[:, future_mask], 0.0)
    return True


def test_kv_cache_matches_full_recompute_under_greedy_decoding():
    tok = BPETokenizer()
    tok.train("the quick brown fox jumps over the lazy dog. " * 20, vocab_size=256)
    model = _tiny_model(vocab=tok.vocab_size, seqlen=32)
    _, ids_cached = generate(model, tok, "the quick", 20, temperature=1.0, top_k=1,
                              rng=np.random.default_rng(0), use_cache=True)
    _, ids_full = generate(model, tok, "the quick", 20, temperature=1.0, top_k=1,
                            rng=np.random.default_rng(0), use_cache=False)
    assert ids_cached == ids_full, "KV-cache generation diverged from full-recompute generation"
    return True


def test_weight_tying_shares_the_same_array():
    model = _tiny_model()
    # the output head is literally tok_emb.weight.T inside forward(); verify
    # a change to the embedding table changes the logits computed from it.
    # NOTE: a *uniform* per-row perturbation is a bad test here -- an
    # untrained LayerNorm has gamma=1, beta=0, so its output rows are
    # exactly zero-mean, and dot(zero_mean_vector, constant_vector) == 0
    # regardless of tying. Use a non-uniform (random) perturbation instead.
    rng = np.random.default_rng(7)
    ids = np.array([[1, 2, 3]])
    logits_before, _ = model.forward(ids)
    model.tok_emb.weight.data[5, :] += rng.normal(0, 10, size=model.dim)
    logits_after, _ = model.forward(ids)
    assert not np.allclose(logits_before.data[..., 5], logits_after.data[..., 5]), \
        "output logits did not change after mutating the tied embedding table"
    assert np.allclose(logits_before.data[..., :5], logits_after.data[..., :5]), \
        "mutating row 5 of the embedding table should only affect logit column 5"
    return True


def test_checkpoint_roundtrip_reproduces_identical_logits():
    tok = BPETokenizer()
    tok.train("a small corpus for checkpoint testing, nothing more.", vocab_size=270)
    model = _tiny_model(vocab=tok.vocab_size, dim=24, layers=2, heads=2, seqlen=20)
    config = dict(vocab_size=tok.vocab_size, dim=24, n_layers=2, n_heads=2, max_seq_len=20, seed=0)
    path = "/tmp/loom_ckpt_test"
    save_checkpoint(path, model, tok, config)
    model2, tok2, config2, extra = load_checkpoint(path)

    ids = np.array([[1, 2, 3, 4, 5]])
    logits1, _ = model.forward(ids)
    logits2, _ = model2.forward(ids)
    assert np.allclose(logits1.data, logits2.data), "checkpoint round-trip changed model outputs"
    assert tok.merges_list == tok2.merges_list
    os.remove(path + ".npz")
    os.remove(path + ".json")
    return True


def test_sampling_respects_top_k():
    rng = np.random.default_rng(0)
    logits = np.array([10.0, 0.0, -5.0, 8.0, -1.0])
    draws = {sample_from_logits(logits, rng, temperature=1.0, top_k=2) for _ in range(200)}
    # only indices 0 and 3 (the top-2 logits) should ever be drawn
    assert draws <= {0, 3}, f"top_k=2 leaked into other indices: {draws}"
    return True


def test_sampling_temperature_zero_like_is_near_greedy():
    rng = np.random.default_rng(0)
    logits = np.array([1.0, 5.0, 2.0])
    draws = [sample_from_logits(logits, rng, temperature=0.01) for _ in range(50)]
    assert all(d == 1 for d in draws), "very low temperature should collapse to the argmax"
    return True


def test_generate_with_prompt_longer_than_context_window():
    # Regression test: a prompt at/over max_seq_len used to make the cached
    # path generate zero new tokens and the non-cached path generate
    # exactly one token before stopping early -- silently diverging
    # instead of erroring or handling it consistently. Both paths must now
    # truncate the prompt to the window and behave identically.
    tok = BPETokenizer()
    tok.train("the quick brown fox jumps over the lazy dog and then runs home again quickly. " * 20,
              vocab_size=256)
    model = _tiny_model(vocab=tok.vocab_size, seqlen=20)
    long_prompt = "the quick brown fox jumps over the lazy dog and then runs home"
    assert len(tok.encode(long_prompt)) > 20

    _, ids_cached = generate(model, tok, long_prompt, 15, temperature=1.0, top_k=1,
                              rng=np.random.default_rng(0), use_cache=True)
    _, ids_full = generate(model, tok, long_prompt, 15, temperature=1.0, top_k=1,
                            rng=np.random.default_rng(0), use_cache=False)
    assert ids_cached == ids_full
    assert len(ids_cached) == 20, "generation should fill the context window, not stop after 0 or 1 tokens"
    return True


def test_generate_on_empty_prompt_does_not_crash():
    tok = BPETokenizer()
    tok.train("hello world, this is a small corpus. " * 10, vocab_size=256)
    model = _tiny_model(vocab=tok.vocab_size)
    text, ids = generate(model, tok, "", 10, rng=np.random.default_rng(0))
    assert isinstance(text, str)
    assert len(ids) > 1
    return True


ALL_TESTS = [
    test_forward_shapes_and_all_params_get_gradient,
    test_causal_mask_blocks_future_tokens,
    test_attention_rows_are_causal_and_sum_to_one,
    test_kv_cache_matches_full_recompute_under_greedy_decoding,
    test_generate_with_prompt_longer_than_context_window,
    test_weight_tying_shares_the_same_array,
    test_checkpoint_roundtrip_reproduces_identical_logits,
    test_sampling_respects_top_k,
    test_sampling_temperature_zero_like_is_near_greedy,
    test_generate_on_empty_prompt_does_not_crash,
]


def run_all():
    ok = True
    for t in ALL_TESTS:
        try:
            t()
            print(f"[OK] {t.__name__}")
        except Exception as e:
            ok = False
            print(f"[FAIL] {t.__name__}: {e}")
    return ok


if __name__ == "__main__":
    sys.exit(0 if run_all() else 1)
