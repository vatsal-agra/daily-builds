# Loom

*Status: Phase 1 complete (planning). Core build in progress.*

A transformer language model — the architecture behind modern LLMs — built
entirely from scratch: a reverse-mode tensor autodiff engine (no PyTorch,
no TensorFlow, no JAX, no autograd of any kind), a GPT-style decoder-only
transformer on top of it, a real training loop, and autoregressive text
generation.

See [PLAN.md](./PLAN.md) for the full architecture and feature list.
This README will be filled in with usage instructions as each phase lands.
