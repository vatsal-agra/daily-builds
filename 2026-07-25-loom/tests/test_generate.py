"""
Generation correctness:
- same seed -> same sampled sequence (determinism)
- KV-cache path produces IDENTICAL tokens to the naive path (cache is a
  speed optimization, not a different model)
- top_k=1 is greedy regardless of temperature
- exceeding the KV-cache's n_ctx budget raises instead of corrupting output
"""
import os
import sys

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from loom.generate import generate_cached, generate_naive, sample_from_logits
from loom.model import GPT, GPTConfig


def make_model():
    cfg = GPTConfig(vocab_size=40, n_ctx=16, n_embd=32, n_head=4, n_layer=2)
    return GPT(cfg, seed=0), cfg


def test_sampling_determinism():
    model, cfg = make_model()
    idx = np.array([[1, 2, 3]])
    out1 = generate_naive(model, idx, 6, cfg.n_ctx, temperature=0.8, top_k=10,
                           rng=np.random.default_rng(42))
    out2 = generate_naive(model, idx, 6, cfg.n_ctx, temperature=0.8, top_k=10,
                           rng=np.random.default_rng(42))
    assert np.array_equal(out1, out2), "same seed must give same generated tokens"
    print("  sampling determinism: OK")


def test_cache_matches_naive():
    model, cfg = make_model()
    idx = np.array([[5, 1, 9, 2]])
    n_new = cfg.n_ctx - idx.shape[1]
    out_naive = generate_naive(model, idx, n_new, cfg.n_ctx, temperature=0.7, top_k=15,
                                rng=np.random.default_rng(7))
    out_cached = generate_cached(model, idx, n_new, cfg.n_ctx, temperature=0.7, top_k=15,
                                  rng=np.random.default_rng(7))
    assert np.array_equal(out_naive, out_cached), (
        f"cache/naive mismatch:\n naive ={out_naive}\n cached={out_cached}"
    )
    print("  KV-cache output parity with naive path: OK")


def test_greedy_top_k1_ignores_temperature():
    model, cfg = make_model()
    idx = np.array([[3, 4]])
    out_hot = generate_naive(model, idx, 5, cfg.n_ctx, temperature=5.0, top_k=1,
                              rng=np.random.default_rng(1))
    out_cold = generate_naive(model, idx, 5, cfg.n_ctx, temperature=0.01, top_k=1,
                               rng=np.random.default_rng(99))
    assert np.array_equal(out_hot, out_cold), "top_k=1 must be deterministic regardless of temperature/seed"
    print("  top_k=1 greedy: temperature/seed-invariant, OK")


def test_cache_budget_enforced():
    model, cfg = make_model()
    idx = np.array([[1, 2, 3]])
    try:
        generate_cached(model, idx, cfg.n_ctx, cfg.n_ctx, rng=np.random.default_rng(0))
        raised = False
    except ValueError:
        raised = True
    assert raised, "exceeding KV-cache n_ctx budget must raise, not silently corrupt output"
    print("  KV-cache overflow guard: raises ValueError as documented")


def test_sample_from_logits_top_p_valid_distribution():
    rng = np.random.default_rng(0)
    logits = rng.normal(size=(1, 20))
    counts = np.zeros(20)
    for i in range(500):
        tok = sample_from_logits(logits, temperature=1.0, top_k=None, top_p=0.9,
                                  rng=np.random.default_rng(i))
        counts[tok[0]] += 1
    assert counts.sum() == 500 and (counts > 0).sum() >= 2, "top-p sampling collapsed unexpectedly"
    print("  top-p sampling: produces a valid, non-degenerate distribution")


if __name__ == "__main__":
    test_sampling_determinism()
    test_cache_matches_naive()
    test_greedy_top_k1_ignores_temperature()
    test_cache_budget_enforced()
    test_sample_from_logits_top_p_valid_distribution()
    print("ALL GENERATE TESTS PASSED")
