# Undertow

*Status: PHASE 4 complete — all 3 stretch features shipped (SACK-based
loss recovery, an interactive HTML visualizer, and an HTTP/1.0 demo app),
plus polish: CLI input validation with clean error messages, and an HTTP
handler that returns a real 400 for malformed requests instead of silently
pretending they're "GET /". See [`REVIEW.md`](./REVIEW.md) for the Phase 3
adversarial review (11 real bugs found and fixed). Verification next.*

A reliable, ordered, congestion-controlled byte-stream transport protocol
("MiniTCP") built entirely from scratch on top of raw, lossy UDP — the same
problem TCP/IP solves, proven by streaming a real file through a real relay
that drops, delays, reorders, and duplicates real datagrams, and getting
every byte back identical.

See [`PLAN.md`](./PLAN.md) for the full architecture and feature list.

## Try it

```
python3 bin/undertow-demo --size 100000 --loss 0.1 --dup 0.02 --reorder 0.05 \
    --delay-min 5 --delay-max 20 --report /tmp/undertow_report.html
```

Runs the tests:

```
python3 -m unittest discover -s tests
```

## What's implemented so far

- `undertow/segment.py` — wire format + CRC32 checksum verification
- `undertow/rto.py` — Jacobson/Karels RTO estimator
- `undertow/congestion.py` — Reno congestion control (slow start / congestion
  avoidance / fast recovery)
- `undertow/socket_.py` — `MiniTCPSocket`: 3-way handshake, sliding-window
  reliable delivery, fast retransmit, SACK, 4-way graceful close
- `undertow/netsim.py` — real UDP relay with configurable loss/delay/
  jitter/reorder/duplication
- `undertow/fileapp.py` — SHA-256-verified file transfer over MiniTCPSocket
- `undertow/httpapp.py` — minimal HTTP/1.0 request/response over MiniTCPSocket
- `viz/generate_report.py` — interactive HTML report (cwnd sawtooth,
  throughput, packet timeline) from a real recorded run
- `bin/undertow-demo` — CLI driving a full transfer through a lossy network
- `tests/` — 46 tests covering wire format, RTO, congestion control, the
  netsim's actual loss behavior, handshake/teardown (including concurrent
  close and source-spoofing rejection), reliable transfer under loss/dup/
  reorder, SACK, and the HTTP demo app (including malformed-request 400s)

More detail (full feature list, "why this today", results) lands in later
phases per `PLAN.md`.
