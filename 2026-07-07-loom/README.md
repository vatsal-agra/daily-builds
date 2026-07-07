# Loom

A tiny LLM built entirely from scratch: a hand-written reverse-mode
autograd engine, a byte-level BPE tokenizer, a decoder-only Transformer,
and a real training loop — no PyTorch/TensorFlow/JAX/`transformers`, no
autograd library. NumPy is used only as an array/BLAS substrate.

**Status: Phase 1 (plan) complete.** See [PLAN.md](PLAN.md) for the full
architecture and feature list. Implementation in progress.
