# Loom

A GPT-style decoder-only Transformer language model, built entirely from
scratch — tokenizer, self-attention, hand-derived backpropagation, and the
training loop — in Python + NumPy. No `torch`, `jax`, `transformers`, or
autograd library anywhere in this project.

**Status: Phase 2 (core build) in progress.** All four required features are
implemented and unit-tested — from-scratch BPE tokenizer, transformer layers
with hand-derived backward passes (verified against numerical gradients),
AdamW + LR schedule, and sampling (temperature/top-k/top-p) — and a full
training run on the real corpus is underway to confirm end-to-end quality
before Phase 3. See [`PLAN.md`](PLAN.md) for the full architecture and
feature list.

## What's implemented so far

- `loom/tokenizer.py` — byte-level BPE, trained from scratch on the corpus.
- `loom/layers.py`, `loom/model.py` — GPT (embedding, causal multi-head
  self-attention, LayerNorm, GELU MLP, tied output head), every layer with
  a hand-written `backward()`.
- `loom/optimizer.py` — AdamW, global-norm grad clipping, warmup+cosine LR.
- `loom/generate.py` — naive + KV-cached autoregressive sampling.
- `loom/train.py`, `loom/cli.py` — training loop and `loom train|generate|bench|viz` CLI.
- `viz/visualizer.html` — attention-heatmap + generation step-through viewer.
- `tests/` — gradient checks, tokenizer round-trip, causal-mask leakage
  check, overfit sanity check, and generation parity/determinism checks —
  all passing.

Next: finish the real training run on `corpus/fables.txt`, confirm sample
quality, then Phase 3 (adversarial review) and Phase 4 (KV-cache stretch +
polish).
