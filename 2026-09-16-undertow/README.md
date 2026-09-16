# Undertow

A TCP-shaped reliable transport protocol, built from scratch on raw UDP
sockets: real packet checksums, a 3-way handshake, wraparound-safe sequence
numbers, Jacobson/Karels RTO estimation with Karn's algorithm, selective
ACKs, and genuine Reno-style congestion control (slow start → congestion
avoidance → fast retransmit → fast recovery).

**Status: Phase 5 (verification) complete — `./demo.sh` passes 12/12.** All 4 required features
work end-to-end over real UDP sockets and a real lossy/reordering/
duplicating network relay. Both stretch features shipped: an interactive
HTML trace visualizer, and a second (delay-based) congestion controller
with a real head-to-head comparison against Reno over a genuine bottleneck
link. See [PLAN.md](PLAN.md) for the design and [REVIEW.md](REVIEW.md) for
everything the adversarial review and polish pass found and fixed —
including two connection-breaking bugs (a handshake that never completed
on a perfectly clean link, and a cascading RTO-backoff bug that stalled
bulk transfers under loss), a zero-window deadlock, and a real, well-known
Reno limitation (recovering multiple losses in one window without SACK)
that the Reno/Vegas comparison surfaces live rather than just describing.

## What's here so far

- `undertow/seqmath.py` — RFC 1982 wraparound-safe sequence-number arithmetic.
- `undertow/packet.py` — wire format + RFC 1071 checksum.
- `undertow/rto.py` — Jacobson/Karels RTO estimator + Karn's algorithm.
- `undertow/congestion.py` — Reno congestion controller (slow start, AIMD,
  fast retransmit, fast recovery).
- `undertow/vegas.py` — a delay-based congestion controller (simplified
  TCP Vegas).
- `undertow/connection.py` — the actual protocol state machine: handshake,
  sliding window, retransmission, zero-window recovery, graceful teardown.
- `undertow/netsim.py` — a real UDP relay that drops/duplicates/reorders/
  delays datagrams under a seeded RNG, plus an optional real bottleneck
  queue model (rate + buffer, real queueing delay and tail-drop).
- `undertow/socket_api.py` — the public `UndertowSocket` API.
- `transfer.py` — CLI: `send`/`serve` a real file between two processes,
  `demo` (single lossy-link transfer), `compare` (Reno vs. Vegas head to
  head over the same bottleneck).
- `viz/index.html` — a dependency-free interactive trace visualizer
  (cwnd-over-time, RTO estimate, packet timeline) for `--trace-out` output.
- `tests/` — unit + integration tests, including regressions for every
  Phase 3/4 finding (63 passing).

## Try it

```
python3 transfer.py demo --size 500000 --loss 0.05 --dup 0.02 --reorder 0.05
python3 transfer.py compare                       # Reno vs. Vegas, same real bottleneck
python3 transfer.py compare --trace-out /tmp/cmp   # then open viz/index.html and load
                                                    # /tmp/cmp.reno.json + /tmp/cmp.vegas.json
python3 -m unittest discover -s tests
```

## Verify

```
./demo.sh
```

Runs the full test suite plus 8 more end-to-end checks through the real
CLI: a clean-link transfer, a lossy-link transfer, sequence-number
wraparound, the Reno/Vegas bottleneck comparison, a real two-*process*
`send`/`serve` file transfer over actual OS sockets, CLI error-handling
on realistic mistakes, an empty transfer, and a headless-browser check
that the trace visualizer renders a real trace with zero console errors.

## Next

Phase 6 (ship).
