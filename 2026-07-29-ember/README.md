# Ember

A from-scratch JIT compiler: a small C-like language compiled directly to
real x86-64 machine code, executed on the real CPU via `mmap(PROT_EXEC)` +
`ctypes` — no bytecode layer, no interpreter loop in the hot path.

**Status: Phase 1 (planning) complete.** See [PLAN.md](PLAN.md) for the
full design. Implementation in progress — this README will be filled in
with usage instructions, the full feature list, and results as each phase
lands.
