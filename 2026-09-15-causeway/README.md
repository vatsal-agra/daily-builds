# Causeway

A from-scratch reliable transport protocol over raw UDP — TCP-Reno-style
congestion control, Jacobson/Karels adaptive retransmission, decoupled
flow control, and real byte-exact file transfer through a real lossy
network proxy. See [PLAN.md](PLAN.md) for the full concept and design.

**Status: Phase 5 (Verification) complete.** `./demo.sh` runs the full
narrated walkthrough — 38 unit tests, a 4-scenario CLI demo matrix, a real
direct two-process transfer, the real three-process lossy-proxy capstone,
the visualizer + headless-browser check, and the adversarial regression
checks — all 6 green. Verification itself caught one more real bug (see
REVIEW.md finding #9): under sustained 40% loss, a fixed 1-second TIME_WAIT
could expire before the peer's own retried FIN got another chance to be
acknowledged, permanently orphaning it. Fixed by scaling TIME_WAIT with the
connection's own `max_rto` instead of a disconnected magic constant.

All 4 required features are implemented and demonstrably working
end-to-end:

1. **Reliable, ordered, exactly-once delivery** — proven both by a fuzz
   suite (`tests/test_fuzz_transfer.py`) running ~110+ seeded scenarios
   across sizes/loss/duplication/reordering, and by a real two-process
   transfer over real UDP sockets through the real lossy `causeway proxy`
   (see below), with a byte-exact SHA-256 match every time.
2. **Adaptive RTO (Jacobson/Karels)** — `causeway/connection.py`'s
   `RttEstimator`, unit-tested against hand-computed values.
3. **TCP-Reno congestion control** — slow start, congestion avoidance,
   fast retransmit/fast recovery, timeout collapse, all exercised directly
   in `tests/test_congestion_control.py` with deliberately engineered loss
   scenarios (not just "it finished eventually").
4. **Flow control independent of congestion control** — a tiny receiver
   buffer throttles a fast sender even with zero loss and an enormous
   cwnd, and a full zero-window/persist-timer cycle is exercised without
   deadlocking (`tests/test_flow_control.py`).

Both stretch features are shipped:

5. **Interactive visualizer** (`causeway viz`) — a self-contained
   HTML/canvas dashboard (cwnd/ssthresh sawtooth with fast-retransmit and
   timeout markers, RTT/RTO, in-flight-vs-window, cumulative throughput)
   rendered from a real captured event log, with a hover crosshair +
   tooltip, light/dark theming, and mobile-width responsiveness —
   headless-Chromium verified with zero console errors
   (`tests/browser_smoke_test.js`). One real bug was caught purely by
   looking at a rendered screenshot rather than any automated test: the
   y-axis labels for larger values (like "168.0 KB") were being clipped
   against the canvas edge by a fixed left padding, corrupting the leading
   digit; fixed by sizing the padding to the actual widest label.
6. **Robust connection lifecycle + live two-process capstone** — graceful
   FIN/FIN-ACK/TIME_WAIT-style close that survives a lost final ACK
   (`tests/test_reassembly_and_teardown.py`), plus a real `causeway send` /
   `causeway proxy` / `causeway recv` three-process demo: two independent
   OS processes moving a real file over real UDP sockets through a real
   lossy/reordering/duplicating relay process, byte-exact every time.

See [REVIEW.md](REVIEW.md) for every bug found during adversarial review
(2 during core build, 4 more from a dedicated hostile-reviewer pass, plus
the visualizer clipping bug above) and how each was fixed, with regression
tests pinning all of them. 37 unit/integration tests green.

## Quick start

```bash
# Fast, seeded, in-process simulated transfer (milliseconds of wall time,
# hundreds of seconds of *simulated* network time):
python3 -m causeway.cli demo --bytes 200000 --loss 0.1 --dup 0.05 --reorder 0.1

# The same, with an interactive visualizer of what happened:
python3 -m causeway.cli demo --bytes 200000 --loss 0.08 --log-json log.json
python3 -m causeway.cli viz --log-json log.json --out viz.html   # open viz.html

# Real two-process transfer over real UDP, through a real lossy proxy:
python3 -m causeway.cli recv --bind 127.0.0.1:9091 --out received.bin &
python3 -m causeway.cli proxy --listen 127.0.0.1:9090 --target 127.0.0.1:9091 \
    --loss 0.1 --dup 0.05 --reorder 0.1 --delay-ms 10 --jitter-ms 15 &
python3 -m causeway.cli send myfile.bin --peer 127.0.0.1:9090
```

## Tests

```bash
python3 -m unittest discover -s tests
```

Or run `./demo.sh` for the full narrated walkthrough (unit suite, fuzz
suite, real two-process transfer, real lossy-proxy transfer, visualizer +
headless-browser check, and the adversarial-regression checks) — this is
what Phase 5 verification runs.

Remaining phase (ship: full README, LEDGER.md entry) follows in the final
commit.
