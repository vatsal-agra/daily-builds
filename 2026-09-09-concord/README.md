# Concord

> A real-time collaborative text editor built on a from-scratch CRDT (RGA).
> No leader, no locking, no merge-conflict dialog — independent replicas
> that mathematically converge.

**Status: Phase 4 (Stretch + polish) complete.** All 4 required features and
both stretch features (live multi-cursor presence, the CRDT internals
inspector) are implemented and verified end-to-end against the real server,
real engine, and a real headless browser. A hostile-reviewer pass (Phase 3)
found and fixed 10 real issues, including a critical replica-divergence bug
in the core algorithm, a crash, a data-corruption bug, an XSS hole, and an
O(n²) performance bug — full writeup in [REVIEW.md](REVIEW.md). Phase 4 then
redesigned the UI from a functional-but-plain baseline into something
actually worth using, and caught one more real bug in the process (a CSS
specificity issue that made the offline banner render even while hidden —
also in REVIEW.md). See [PLAN.md](PLAN.md) for the concept and architecture.
This README fills in as later phases land; Phase 6 will have the final,
complete version.

## What it looks like

A warm paper-toned editor with a gradient accent bar, live-updating peer
avatars, colored remote carets with name flags, and a technical "CRDT
internals" side panel that shows the actual replicated data structure —
fully theme-aware (light/dark), not the browser's default form-control
styling.

## Quickstart

```
python3 server/relay.py            # starts the relay on http://127.0.0.1:8420
```
Then open `http://127.0.0.1:8420/?doc=demo` in two separate browser
tabs/windows and start typing in either one.

Or see it work without a browser at all:
```
node examples/two_clients_demo.js  # narrated walkthrough, spins up its own server
```

## Tests so far

```
node tests/fuzz_convergence.js 2000   # property fuzzer: thousands of randomized
                                       # concurrent-edit trials against every
                                       # possible delivery order; asserts every
                                       # replica converges to identical text
node tests/test_integration.js        # real relay.py + two real RGA replicas
                                       # over real HTTP/SSE: live sync + offline/
                                       # merge-on-reconnect
python3 -m unittest tests.test_relay -v
                                       # relay HTTP API: validation, atomic
                                       # batches, SSE backlog/live replay
NODE_PATH=/opt/node22/lib/node_modules node tests/test_browser.js
                                       # two real headless-Chromium tabs driving
                                       # the actual app UI end-to-end, incl. a
                                       # security regression test
```

See [REVIEW.md](REVIEW.md) for the full adversarial review writeup. More
formal verification (Phase 5) and stretch/polish (Phase 4) still to come.
