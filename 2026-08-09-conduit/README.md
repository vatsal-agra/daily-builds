# Conduit

A TCP-like reliable transport protocol, built entirely from scratch on
raw UDP sockets — no `socket.SOCK_STREAM` anywhere in the implementation —
proven under active packet loss, reordering, and duplication injected by
a from-scratch network simulator, carrying a from-scratch HTTP/1.1 server
that the box's real, unmodified `curl` binary can fetch from end-to-end
*through* that lossy simulator.

Every prior build in this repo's history stopped at the application or
algorithm layer: languages, databases, renderers, solvers, models,
compression, crypto. None of them went down into the transport layer —
the actual mechanism that turns an unreliable, unordered, lossy packet
network into something an application can treat as a reliable byte
stream. Conduit does: a real 3-way handshake, real TCP-shaped connection
teardown, cumulative ACKs with out-of-order reassembly, Jacobson/Karels
RTT-driven retransmission, and Reno-style congestion control (slow start,
AIMD, fast retransmit, fast recovery) — the actual mechanisms, not a
simulation of them.

See [PLAN.md](PLAN.md) for the original design rationale and
[REVIEW.md](REVIEW.md) for the adversarial-review findings (4 real bugs
found and fixed while building this, including one that made a 50KB
transfer take 18 seconds — a genuinely interesting bug, documented in
detail).

## How to run it

```bash
cd 2026-08-09-conduit

# Everything in one shot: the full test suite, the end-to-end CLI demo,
# a conduit-cp smoke test, and CLI validation checks. ~70 seconds.
./demo.sh

# The 67-test suite on its own:
python3 -m unittest discover -s tests -v

# The end-to-end showcase: real curl fetching from a Conduit-backed HTTP
# server through 3 netsim scenarios (clean / moderate loss / harsh),
# plus a conduit-cp file transfer — with an interactive HTML trace report:
python3 -m conduit.cli demo --report /tmp/conduit-demo.html

# Serve a real directory for curl/a browser to hit, through a real TCP
# bridge into Conduit, optionally through a simulated lossy network:
python3 -m conduit.cli serve examples/site --loss 0.08 --reorder 0.05 --port 8080
curl http://127.0.0.1:8080/

# A standalone reliable file-transfer tool built directly on ConduitSocket:
python3 -m tools.conduit_cp send myfile.bin <host> <port>     # on the sender
python3 -m tools.conduit_cp recv 0.0.0.0 <port> ./incoming/   # on the receiver
python3 -m tools.conduit_cp demo myfile.bin ./out/ --loss 0.07 --report trace.html  # one-process demo
```

Open any generated `--report`/`trace.html` in a browser — it's a single
self-contained file (cwnd/ssthresh sawtooth, RTT/RTO over time, a
sequence/retransmit/drop timeline, hoverable tooltips).

## Feature list

**Required (all 4 shipped, demonstrable end-to-end):**

1. **Reliable transport core** (`conduit/transport.py`, `segment.py`,
   `checksum.py`, `seqmath.py`, `rto.py`) — a real TCP-shaped 3-way
   handshake and connection-close state machine (`FIN_WAIT_1`/`_2`,
   `CLOSING`, `CLOSE_WAIT`, `LAST_ACK`, `TIME_WAIT`, matching real TCP's
   FSM including the simultaneous-close case), byte-stream sequence
   numbers with 32-bit serial (RFC 1982, wraparound-safe) arithmetic,
   cumulative ACKs with out-of-order reassembly, an RFC 1071 Internet
   checksum on every segment, and Jacobson/Karels (RFC 6298) RTO-driven
   retransmission with Karn's algorithm (no RTT sample from a
   retransmitted segment).
2. **Reno congestion control** (`conduit/congestion.py`) — slow start,
   AIMD congestion avoidance, fast retransmit on 3 duplicate ACKs, fast
   recovery with partial-ACK inflation, plus a receiver-advertised
   flow-control window that actually throttles the sender.
3. **NetworkSimulator** (`conduit/netsim.py`) — a seeded UDP middlebox
   (a tiny NAT gateway, one dedicated server-facing socket per client
   flow so the server still demuxes distinct clients) injecting
   configurable loss, duplication, reordering, and delay/jitter. Every
   integration test and the curl oracle run *through* it, not around it.
4. **HTTP/1.1 over Conduit** (`httpd/`) — a from-scratch request/response
   server (keep-alive, GET/HEAD/POST, static files with a path-traversal
   guard, a pluggable handler for dynamic routes) running entirely over
   `ConduitSocket`. Reachable by the box's real `curl` through a
   TCP↔Conduit byte-relay bridge (`conduit/bridge.py`) — including
   *through* the lossy simulator, verified byte-for-byte against the
   source file at up to 15% configured loss.

**Stretch (2 shipped):**

5. **Interactive HTML trace visualizer** (`viz/`) — `TraceRecorder`
   captures every protocol event (send/recv/ack/dup-ack/retransmit/
   timeout/fast-retransmit/rtt-sample/cwnd-change, plus the simulator's
   drop/dup/reorder decisions) with timestamps; `render_html` turns that
   into a single self-contained, dark-themed HTML file with three charts
   (cwnd/ssthresh sawtooth, RTT/RTO over time, a sequence timeline with
   retransmit/drop/reorder markers) and hoverable tooltips — no external
   JS/CSS, screenshot-verified in headless Chromium with zero JS errors.
6. **`conduit-cp`** (`tools/conduit_cp.py`) — a real reliable
   file-transfer CLI built directly on `ConduitSocket` (not HTTP): a
   small length-prefixed wire format, throttled progress reporting, and
   an end-to-end SHA-256 check independent of Conduit's own per-segment
   checksums (it verifies the whole application pipe — framing,
   buffering, disk I/O — not just that no segment was corrupted in
   transit). Includes a path-traversal guard on received filenames and a
   deliberately-corrupted-checksum test proving the check actually fires.

## Why I chose this today

Every "language" or "runtime" build in this repo's history — Coil's
bytecode VM, Kiln's WASM interpreter, Ember's JIT, nine from-scratch
transformers — assumed a single machine. None of them ever had to get
bytes from one process to another over a network that might drop, delay,
reorder, or duplicate them. That's a real, foundational gap: it's the
layer every one of those systems would eventually need if it had to talk
to anything else. TCP is also one of the most-cited "everyone knows
roughly how it works, almost no one has built one" pieces of software
infrastructure — a perfect target for a from-scratch build with a hard,
falsifiable correctness bar (byte-perfect delivery under actual, injected
chaos) rather than "looks plausible."

## Where a human could take this next

- **Selective ACKs (SACK).** Conduit's Reno-style recovery is
  Go-Back-N-like under multiple losses in one window — REVIEW.md
  documents exactly the pathological case (RTO climbing to 30 seconds
  under compounded loss+duplication) that real SACK TCP exists to fix.
  Adding a SACK option to the segment header and letting the sender
  retransmit precisely the missing ranges would be the single highest-
  leverage next feature.
- **BBR or CUBIC** instead of Reno — a genuinely different congestion
  control philosophy (model the bottleneck instead of reacting to loss)
  would be a great compare-and-contrast against the existing trace
  visualizer.
- **TLS-over-Conduit.** Layer a real handshake (even a toy Diffie-Hellman
  + AEAD, reusing primitives from this repo's own Cryptex/Ironkey builds)
  on top of the byte stream, the same way TLS layers on top of TCP.
- **Multiplexed streams**, QUIC-style, over one Conduit connection —
  would also sidestep HTTP/1.1 head-of-line blocking at the application
  layer.
- **A real second machine.** Everything here runs over loopback; the
  netsim and bridge are both address-agnostic, so pointing them at a
  real LAN (or two containers with `tc netem` for *additional*,
  kernel-level chaos on top of Conduit's own) would be a strong next
  proof point.
