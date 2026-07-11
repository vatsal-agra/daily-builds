# Loom

*Status: Phase 1 (plan) complete. Build in progress.*

A Transformer language model trained on a from-scratch tensor autodiff
engine — no PyTorch, no JAX, no `autograd`. `numpy` is used only as a fast
array container and matmul; every gradient is hand-derived and verified by
finite-difference checking.

See [`PLAN.md`](./PLAN.md) for the full architecture and feature list.
This README will be filled in with usage instructions as the build
progresses through its phases.
