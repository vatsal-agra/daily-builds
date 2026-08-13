# Braid

*Status: Phase 4 complete — all 3 planned stretch features (character
attribution, causal undo/redo, convergence-hash indicator) were already
built during core development; this phase added polish (favicon, log-panel
scroll fix, disabled-state UX, edge-case hardening for empty docs / large
pastes / single-peer removal). 16/16 tests passing. Final verification and
ship writeup still to come.*

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
