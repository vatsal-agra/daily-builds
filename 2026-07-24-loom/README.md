# Loom

A GPT-style language model built entirely from scratch: a hand-derived
reverse-mode autodiff engine, a from-scratch byte-pair-encoding tokenizer, a
decoder-only transformer, and an Adam optimizer — trained on the public
domain Tiny Shakespeare corpus, with a live web UI for generation and
attention visualization.

**Status: Phase 2 (core build) in progress.** All four required features
are implemented and unit/integration tested; the real training run
(3000 steps on the full corpus) is in progress in the background. See
[PLAN.md](PLAN.md) for the architecture and feature list.

## What's implemented so far

- `loom/engine.py` — reverse-mode autodiff `Tensor` (add/mul/matmul/etc,
  softmax, layernorm, embedding, dropout, cross-entropy), every op checked
  against finite-difference numerical gradients in `tests/test_engine.py`.
- `loom/tokenizer.py` — from-scratch BPE tokenizer, word-frequency-weighted
  merge training, byte fallback for any unseen input.
- `loom/model.py` — GPT-style causal transformer built from `engine.py`
  primitives only.
- `loom/optim.py` — Adam optimizer.
- `loom/generate.py` — temperature / top-k / top-p sampling, plus a real
  attention-weight extraction function for visualization.
- `loom/train.py`, `loom/checkpoint.py`, `loom/server.py`, `loom/cli.py`,
  `static/` — training loop, checkpointing, web API + UI, and a unified CLI.

Run `tests/test_engine.py`, `tests/test_tokenizer.py`, `tests/test_model.py`,
and `tests/test_integration.py` directly (or via `demo.sh` once training
finishes) to see everything pass.
