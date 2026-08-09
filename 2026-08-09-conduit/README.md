# Conduit

*Status: Phase 3 — adversarial review complete, 4 real bugs found and
fixed (see [REVIEW.md](REVIEW.md)), 62/62 tests green.*

A TCP-like reliable transport protocol built entirely from scratch on raw
UDP sockets, exercised under active packet loss/reorder/duplication by a
from-scratch network simulator, carrying a from-scratch HTTP/1.1 server
that interoperates end-to-end with the box's real `curl` binary — through
the lossy simulator.

See [PLAN.md](PLAN.md) for the full design, architecture, and feature
list.

## What's built so far

1. **Reliable transport core** (`conduit/transport.py`) — a real TCP-style
   client/server handshake and close state machine, byte-stream sequence
   numbers with wraparound-safe (RFC 1982) arithmetic, cumulative ACKs
   with out-of-order reassembly, an Internet checksum (RFC 1071) on every
   segment, and Jacobson/Karels RTO-driven retransmission.
2. **Reno congestion control** (`conduit/congestion.py`) — slow start,
   AIMD congestion avoidance, fast retransmit on 3 duplicate ACKs, fast
   recovery, plus receiver-advertised flow-control windows
   (`conduit/rto.py` for the RTT estimator).
3. **NetworkSimulator** (`conduit/netsim.py`) — a seeded UDP middlebox
   injecting configurable loss/duplication/reordering/jitter that every
   integration test runs through.
4. **HTTP/1.1 over Conduit** (`httpd/`) — a from-scratch request/response
   server (keep-alive, HEAD/GET/POST, static files, path-traversal
   guarded) running entirely over `ConduitSocket`, reachable by the box's
   real `curl` through a TCP↔Conduit bridge (`conduit/bridge.py`) —
   including *through* the lossy simulator.

Try it:

```bash
cd 2026-08-09-conduit
python3 -m unittest discover -s tests -v   # 62 tests, ~20-60s depending on scheduling
```

See [REVIEW.md](REVIEW.md) for the adversarial-review findings (4 real
bugs found and fixed, plus honestly-documented known limitations).

Next: stretch features (trace visualizer, `conduit-cp`), polish, and a
runnable demo script.
