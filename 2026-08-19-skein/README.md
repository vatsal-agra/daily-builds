# Skein

A from-scratch CRDT (Conflict-free Replicated Data Type) for real-time
collaborative text editing — the algorithm family behind Google Docs
(historically OT) and modern tools like Yjs/Automerge (CRDTs) — with a
simulated unreliable network, a multi-site concurrent-edit simulator, a
randomized convergence-proof harness, and (coming) an interactive
playground.

**Status: Phase 5 (verification) complete.** All 4 required features
plus both planned stretch features are shipped, with an 83-test unit
suite and `demo.sh` (unit suite + every CLI feature + a live HTTP
smoke test of the playground, including regression checks for every
bug in REVIEW.md) all green:

```
python3 -m skein.cli demo                        # narrated walkthrough of every core feature
python3 -m skein.cli sim                         # one chaos simulation, full transcript
python3 -m skein.cli chaos --trials 300          # randomized convergence-proof sweep
python3 -m skein.cli shuffle-proof --trials 300  # order-independence proof
python3 -m skein.cli serve                       # interactive multi-user playground → http://127.0.0.1:8765/
```

In the playground: type in any of the three panes and watch the other
two catch up as the simulated network delivers your edit; use the
Disconnect/Reconnect buttons to partition a site and watch it keep
editing offline, then converge on reconnect; drag the drop/duplicate/
latency sliders to make the network actively hostile; Undo/Redo on any
pane undoes *that pane's own* last edit specifically, even if remote
edits landed in between.

See [PLAN.md](./PLAN.md) for the architecture and full feature list,
and [REVIEW.md](./REVIEW.md) for the adversarial review — 4 real bugs
found and fixed across Phases 3–4, including a `RecursionError` a
straight-typed document delivered in reverse order would reliably
trigger, a network-partition isolation leak, and a non-atomic delete
API that silently wiped every replica's document on a "failed" call.

Run the checks yourself:

```
python3 -m unittest discover -s tests -q   # 83 tests
./demo.sh                                  # full end-to-end walkthrough, exits non-zero on any failure
```

The final ship-ready README lands in Phase 6.
