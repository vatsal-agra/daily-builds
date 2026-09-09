# Concord

> A real-time collaborative text editor built on a from-scratch CRDT (RGA).
> No leader, no locking, no merge-conflict dialog — independent replicas
> that mathematically converge.

**Status: Phase 2 (Core build) complete.** All 4 required features and both
stretch features are implemented and verified end-to-end against the real
server, real engine, and a real headless browser. See [PLAN.md](PLAN.md) for
the concept and architecture. This README fills in as later phases land;
Phase 6 will have the final, complete version.

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
NODE_PATH=/opt/node22/lib/node_modules node tests/test_browser.js
                                       # two real headless-Chromium tabs driving
                                       # the actual app UI end-to-end
```

More formal verification (Phase 5) and the adversarial review (Phase 3)
still to come.
