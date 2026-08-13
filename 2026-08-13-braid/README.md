# Braid

*Status: Phase 2 complete — core CRDT, network simulator, live multi-peer
editor UI, and randomized convergence test harness are all built and
verified working end-to-end. Adversarial review and polish still to come.*

A from-scratch CRDT (Replicated Growable Array) collaborative text editor
with an adversarial network simulator, built entirely in vanilla JS with
zero dependencies. See [PLAN.md](./PLAN.md) for the full concept and
feature list.

## Quick look

```
npm test        # 13 tests: RGA unit tests + a 100-scenario randomized
                 # convergence proof (latency, reordering, loss, partitions)
python3 -m http.server 8000   # then open index.html in a browser
```

Open the page, type in any peer's pane, watch it merge into the others.
Split peers into partition groups and edit both sides, then heal — the
histories merge deterministically. Toggle "Attribution view" to see who
wrote each character; undo is causal (only ever undoes your own edit).

Full usage instructions and feature list will be finalized in Phase 6.
