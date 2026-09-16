# Undertow

A TCP-shaped reliable transport protocol, built from scratch on raw UDP
sockets: real packet checksums, a 3-way handshake, wraparound-safe sequence
numbers, Jacobson/Karels RTO estimation with Karn's algorithm, selective
ACKs, and genuine Reno-style congestion control (slow start → congestion
avoidance → fast retransmit → fast recovery).

**Status: Phase 2 (core build) complete.** All 4 required features are
implemented and demonstrably work end-to-end over real UDP sockets and a
real lossy/reordering/duplicating network relay — see below.

## What's here so far

- `undertow/seqmath.py` — RFC 1982 wraparound-safe sequence-number arithmetic.
- `undertow/packet.py` — wire format + RFC 1071 checksum.
- `undertow/rto.py` — Jacobson/Karels RTO estimator + Karn's algorithm.
- `undertow/congestion.py` — Reno congestion controller (slow start, AIMD,
  fast retransmit, fast recovery).
- `undertow/connection.py` — the actual protocol state machine: handshake,
  sliding window, retransmission, graceful teardown.
- `undertow/netsim.py` — a real UDP relay that drops/duplicates/reorders/
  delays datagrams under a seeded RNG.
- `undertow/socket_api.py` — the public `UndertowSocket` API.
- `transfer.py` — a file-transfer CLI and demo harness.
- `tests/` — unit + integration tests (50 passing).

## Try it

```
python3 transfer.py demo --size 500000 --loss 0.05 --dup 0.02 --reorder 0.05
```

Runs a real send/receive of random bytes through a real lossy simulated
network in one process and verifies the received file is SHA-256-identical
to what was sent.

```
python3 -m unittest discover -s tests
```

## Next

Phase 3 (adversarial review), Phase 4 (stretch features — HTML visualizer,
a second congestion controller), Phase 5 (full verification), Phase 6
(ship).
