# Braid

*Status: Phase 3 complete — adversarial review found and fixed 4 real bugs,
including one genuine CRDT-correctness bug in the merge algorithm itself
(see [REVIEW.md](./REVIEW.md)). 16/16 tests passing. Stretch features and
final polish still to come.*

A from-scratch CRDT (Replicated Growable Array) collaborative text editor
with an adversarial network simulator, built entirely in vanilla JS with
zero dependencies. See [PLAN.md](./PLAN.md) for the full concept and
feature list.

## Quick look

```
npm test        # 16 tests: RGA unit tests, a 100-scenario randomized
                 # convergence proof (latency, reordering, loss, partitions),
                 # and regression tests for 3 real bugs found in review
python3 -m http.server 8000   # then open index.html in a browser
```

Open the page, type in any peer's pane, watch it merge into the others.
Split peers into partition groups and edit both sides, then heal — the
histories merge deterministically. Toggle "Attribution view" to see who
wrote each character; undo is causal (only ever undoes your own edit).

Full usage instructions and feature list will be finalized in Phase 6.
