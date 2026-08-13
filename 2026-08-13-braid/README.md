# Braid

*Status: Phase 5 complete — full verification pass. Writing the end-to-end
browser demo script surfaced 2 more real bugs beyond Phase 3's review (a
join-snapshot gap and a partition-label mismatch, both HIGH severity — see
[REVIEW.md](./REVIEW.md)), now fixed. 18/18 unit tests + 14/14 live-browser
checks passing, stable across repeated runs. Ship writeup still to come.*

A from-scratch CRDT (Replicated Growable Array) collaborative text editor
with an adversarial network simulator, built entirely in vanilla JS with
zero dependencies. See [PLAN.md](./PLAN.md) for the full concept and
feature list.

## Quick look

```
npm test        # 18 tests: RGA unit tests, a 100-scenario randomized
                 # convergence proof (latency, reordering, loss, partitions),
                 # and regression tests for 5 real bugs found in review
./demo.sh        # npm test + a real-browser end-to-end smoke test
                 # (multi-peer UI, partitions, attribution, undo/redo)
python3 -m http.server 8000   # then open index.html in a browser
```

Open the page, type in any peer's pane, watch it merge into the others.
Split peers into partition groups and edit both sides, then heal — the
histories merge deterministically. Toggle "Attribution view" to see who
wrote each character; undo is causal (only ever undoes your own edit).

Full usage instructions and feature list will be finalized in Phase 6.
