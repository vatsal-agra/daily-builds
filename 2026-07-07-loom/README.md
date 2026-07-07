# Loom

A tiny LLM built entirely from scratch: a hand-written reverse-mode
autograd engine, a byte-level BPE tokenizer, a decoder-only Transformer,
and a real training loop — no PyTorch/TensorFlow/JAX/`transformers`, no
autograd library. NumPy is used only as an array/BLAS substrate.

**Status: Phase 2 (core build) in progress.** See [PLAN.md](PLAN.md) for the
full architecture and feature list.

Built and verified so far:
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
  wired correctly), causal-mask leakage tests, checkpoint round-trip, 44
  tests total.

A full training run on Tiny Shakespeare (~1.1MB, public domain) is in
progress at `checkpoints/shakespeare/` to produce the final checkpoint for
generation and the HTML visualizer.
