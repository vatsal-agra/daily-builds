# Causeway

A from-scratch reliable transport protocol over raw UDP — TCP-Reno-style
congestion control, Jacobson/Karels adaptive retransmission, decoupled
flow control, and real byte-exact file transfer through a real lossy
network proxy. See [PLAN.md](PLAN.md) for the full concept and design.

**Status: Phase 2 (Core build) complete.** All 4 required features are
implemented and demonstrably working end-to-end:

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

## Quick start

```bash
# Fast, seeded, in-process simulated transfer (milliseconds of wall time,
# hundreds of seconds of *simulated* network time):
python3 -m causeway.cli demo --bytes 200000 --loss 0.1 --dup 0.05 --reorder 0.1

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

Remaining phases (adversarial review, stretch features/polish, verification,
ship) follow in subsequent commits.
