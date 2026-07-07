# Loom

A tiny LLM built entirely from scratch: a hand-written reverse-mode
autograd engine, a byte-level BPE tokenizer, a decoder-only Transformer,
and a real training loop — no PyTorch/TensorFlow/JAX/`transformers`, no
autograd library. NumPy is used only as an array/BLAS substrate.

**Status: Phase 3 (adversarial review) complete.** See [PLAN.md](PLAN.md) for
the full architecture and feature list, and [REVIEW.md](REVIEW.md) for the
adversarial review: 8 independent review passes found 8 real bugs (a
`Dataset` off-by-one, a silently-broken `top_k=0`, a wrong-gradient bug in
`Tensor.transpose` for negative axes, missing checkpoint validation, a raw
`KeyError` from bad tokenizer input, and more) plus a deeper architectural
fix (a `no_grad()` inference mode - 4x less peak memory, ~20% faster
generation, byte-for-byte identical output) - all fixed, all with regression
tests. Test suite: **63/63 passing** (was 44 before this phase).

Built and verified:
- `loom/tensor.py` — reverse-mode autograd engine (add/mul/matmul/pow/exp/
  log/tanh/sum/mean/reshape/transpose/getitem/cat, broadcasting-aware),
  verified against central-difference numerical gradient checks (17 tests).
- `loom/tokenizer.py` — byte-level BPE tokenizer, exact round-trip on
  arbitrary text including unseen Unicode/punctuation (verified).
- `loom/nn.py` — GPT-style decoder-only Transformer (multi-head causal
  self-attention, LayerNorm, GELU MLP, weight-tied output head) built
  entirely from `Tensor` ops.
- `loom/optim.py` — Adam + warmup/cosine LR schedule + grad clipping.
- `loom/train.py`, `loom/generate.py`, `loom/pca.py`, `loom/viz.py`,
  `loom/cli.py` — training loop, sampling (greedy/temperature/top-k/top-p),
  from-scratch PCA, interactive HTML visualizer, `loom` CLI.
- Correctness gates passing: gradient checks, an overfit-tiny-batch test
  (loss 200x lower after 200 steps - proves forward+backward+optimizer are
  wired correctly), causal-mask leakage tests, checkpoint round-trip, plus
  19 regression tests from the Phase 3 adversarial review - 63 tests total.

**Real training run complete**, `checkpoints/shakespeare/` (4 layers, 4
heads, 96-dim, ~506K params, vocab 512, 2000 steps on Tiny Shakespeare,
~1.1MB public domain corpus):

| step | train loss | val loss | val perplexity |
|---|---|---|---|
| 0 | 6.27 | 6.27 | 528.9 |
| 500 | 3.42 | 3.46 | 31.7 |
| 1000 | 3.20 | 3.22 | 25.1 |
| 1999 | 2.96 | 3.12 | 22.6 |

An **untrained** (random-init) model sampled the same way produces
byte-garbage with no word boundaries (`con<?>bletheylaprentastbl...`). The
**trained** checkpoint produces real structure it was never told about:
`NAME:`-then-newline speaker headers, capitalization, word-spacing,
archaic pronouns (thou/thee), and verse-like punctuation - e.g.:

```
First Citizen:
We then hest of race unfre strery and, your mouble desance;
Where death the and have thy do mam, thee.

FAUTESE:
And, my aty with nevery all man now at with the
```

Not memorized, real Shakespeare (2000 steps on a 506K-param model doesn't
get there) - but unmistakably *learned*, which is the actual gate.
