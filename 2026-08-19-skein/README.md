# Skein

A from-scratch CRDT (Conflict-free Replicated Data Type) for real-time
collaborative text editing — the algorithm family behind Google Docs
(historically OT) and modern tools like Yjs/Automerge (CRDTs) — with a
simulated unreliable network, a multi-site concurrent-edit simulator, a
randomized convergence-proof harness, and (coming) an interactive
playground.

**Status: Phase 2 (core build) complete.** All 4 required features work
end-to-end:

```
python3 -m skein.cli demo            # narrated walkthrough of every core feature
python3 -m skein.cli sim             # one chaos simulation, full transcript
python3 -m skein.cli chaos --trials 300      # randomized convergence-proof sweep
python3 -m skein.cli shuffle-proof --trials 300  # order-independence proof
```

See [PLAN.md](./PLAN.md) for the architecture and full feature list.
Tests, the adversarial review, stretch features, and the final README
land in later phases.
