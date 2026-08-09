# Conduit

*Status: Phase 5 — verification complete. `./demo.sh` runs the full test
suite, the end-to-end CLI demo, the conduit-cp smoke test, and CLI
input-validation checks in one shot: all green.*

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
python3 -m unittest discover -s tests -v   # 67 tests, ~20-60s depending on scheduling

# The full end-to-end showcase — real curl through a lossy netsim at 3
# loss levels, plus a conduit-cp file transfer — with an HTML trace report:
python3 -m conduit.cli demo --report /tmp/conduit-demo.html

# Serve a directory for real curl/browsers to hit (through a real TCP
# bridge into Conduit), optionally through a simulated lossy network:
python3 -m conduit.cli serve examples/site --loss 0.08 --reorder 0.05

# A standalone reliable file-transfer tool, single-process demo:
python3 -m tools.conduit_cp demo <file> <out_dir> --loss 0.07 --report trace.html
```

See [REVIEW.md](REVIEW.md) for the adversarial-review findings (4 real
bugs found and fixed, plus honestly-documented known limitations).

**Stretch features shipped:**
- `viz/` — an interactive, self-contained HTML trace visualizer (cwnd/
  ssthresh sawtooth, RTT/RTO over time, a sequence/retransmit/drop
  timeline, hoverable tooltips, dark theme) rendered from a live-captured
  event log — no external JS/CSS.
- `tools/conduit_cp.py` — a real reliable file-transfer CLI (`send`/
  `recv`/`demo` subcommands) built directly on `ConduitSocket`, with
  progress reporting and end-to-end SHA-256 verification independent of
  Conduit's own per-segment checksums.

Next: verification (tests + a runnable demo script) and shipping.
