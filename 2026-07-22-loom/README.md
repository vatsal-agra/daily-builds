# Loom

*A tiny transformer language model, built from scratch — no PyTorch, no TensorFlow.*

**Status: Phase 1 (Plan) complete.** See [PLAN.md](./PLAN.md) for the full
architecture and feature list. Implementation starts next.

## What it will be

Loom trains and runs a small GPT-style decoder-only transformer using a
hand-built NumPy tensor autograd engine, a from-scratch BPE tokenizer, and
a from-scratch Adam optimizer — the whole stack, no ML framework.

More to come as each phase lands.
