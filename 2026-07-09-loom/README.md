# Loom

A from-scratch tensor autograd engine, a GPT-style Transformer built
directly on top of it, a hand-coded Adam optimizer, and a training/
generation pipeline that turns a bundled text corpus into a small
language model that writes new text — no PyTorch/TensorFlow/JAX anywhere.
NumPy is used strictly as a raw array/BLAS library; every gradient in the
system is derived and coded by hand in `loom/tensor.py`.

**Status: Phase 4 (stretch + polish) complete.** All 4 required features
plus both stretch features (interactive attention visualizer,
configurable model presets + checkpointing) work end to end and have
survived a hostile adversarial pass (see [REVIEW.md](REVIEW.md)). See
[PLAN.md](PLAN.md) for the full architecture and feature list. A full
automated test suite (Phase 5) is still in progress.

## Requirements

```
pip install numpy
```

Nothing else. Pure Python 3 stdlib + NumPy.

## Quickstart

```bash
cd 2026-07-09-loom

# Prove the autograd engine is correct (finite-difference gradient check
# of every primitive op, plus a full GPT forward/backward pass):
./loom_cli gradcheck

# See the bundled corpora and model size presets:
./loom_cli info

# Train a tiny GPT on the bundled fantasy-chronicle corpus
# (~165ms/step on the "tiny" preset at batch_size=16 on a single CPU core —
# this is a from-scratch pure-NumPy autograd engine, not cuDNN, so a few
# thousand steps genuinely takes a few minutes; --preset quickstart trains
# in seconds if you just want to see the pipeline run):
./loom_cli train --corpus all --preset tiny --steps 1500

# Generate text from the trained checkpoint:
./loom_cli generate --ckpt checkpoints/model.npz --prompt "Mira" --temperature 0.8 --top-k 20

# Talk to it interactively:
./loom_cli chat --ckpt checkpoints/model.npz

# Export a self-contained, interactive attention-weight visualizer
# (real per-layer/per-head heatmaps over your prompt's real tokens, plus
# the real training loss curve -- open the resulting HTML file directly,
# no server needed):
./loom_cli viz --ckpt checkpoints/model.npz --prompt "Mira Ashgrove kept every wrong map"
```

## What's implemented so far

- `loom/tensor.py` — reverse-mode autograd `Tensor` over NumPy arrays,
  with correct broadcasting-aware gradients for every op it supports.
- `loom/nn.py` — a GPT-style decoder-only Transformer (multi-head causal
  self-attention, GELU MLP, pre-LN residual blocks, weight-tied output
  head) built entirely out of `Tensor` operations.
- `loom/optim.py` — Adam, hand-coded from the original update rule.
- `loom/tokenizer.py`, `loom/data.py` — character-level tokenizer and
  batching over the bundled corpora.
- `loom/train.py` — training loop (LR warmup + cosine decay, gradient
  clipping, checkpointing) and `loom/generate.py` — temperature/top-k/
  top-p autoregressive sampling plus an interactive chat loop.
- `loom/gradcheck.py` — finite-difference correctness proof for every
  primitive op and for a full model end to end.
- `loom/attention_trace.py` + `viz/attention_template.html` — captures
  real attention weights from a forward pass and renders them into a
  self-contained, interactive HTML visualizer (per-layer/per-head
  heatmaps with hover tooltips, plus the real train/val loss curve).
- `loom/cli.py` — the `loom_cli` command-line entry point:
  `gradcheck` / `info` / `train` / `generate` / `chat` / `viz` / `demo`.
- `checkpoints/model.npz` — a model trained on the bundled corpus (800
  steps, train loss 4.03 → 1.25) and `viz/attention.html` — a real
  visualizer export from it, both checked in as working examples.

Still to come: a full automated test suite (Phase 5).
