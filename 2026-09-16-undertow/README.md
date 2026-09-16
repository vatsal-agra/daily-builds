# Undertow

A TCP-shaped reliable transport protocol, built entirely from scratch on
raw UDP sockets — the layer every prior "from scratch, real protocol"
build in this repo's history has quietly assumed already exists. Real
packet checksums, a real 3-way handshake, wraparound-safe sequence-number
arithmetic, Jacobson/Karels RTO estimation with Karn's algorithm,
selective ACKs, and genuine TCP Reno-style congestion control (slow start
→ congestion avoidance → fast retransmit → fast recovery) — demonstrated
live over a real lossy/reordering/duplicating/bottlenecked network relay,
not asserted about one.

## What it is

Two Python processes talking over real UDP sockets, with a real hostile
network sitting between them, reliably and efficiently moving a byte
stream that arrives corrupted, out of order, duplicated, and sometimes not
at all. `undertow/connection.py` is the actual protocol state machine;
everything above it (`socket_api.py`, `transfer.py`) is just an
application using that protocol to move files.

## How to run it

```bash
# a full lossy-link transfer, verified byte-exact end to end
python3 transfer.py demo --size 500000 --loss 0.05 --dup 0.02 --reorder 0.05

# Reno vs. Vegas, same seeded run, same real bottleneck link
python3 transfer.py compare

# a real file between two processes
python3 transfer.py serve 5000 out.bin --peer-port 5001 &
python3 transfer.py send 127.0.0.1 5000 some_file.bin --bind-port 5001

# the trace visualizer (cwnd, RTO, packet timeline)
python3 transfer.py compare --trace-out /tmp/cmp
# then open viz/index.html in a browser and drop in
# /tmp/cmp.reno.json and /tmp/cmp.vegas.json

# tests
python3 -m unittest discover -s tests   # 63 unit + integration tests
./demo.sh                                # 12 end-to-end checks through the real CLI
```

No third-party dependencies anywhere in the protocol, the CLI, or the
tests — pure Python 3 stdlib (`socket`, `struct`, `threading`, `heapq`).
The visualizer is a single dependency-free HTML/CSS/JS file.

## Full feature list

**Required (all 4 shipped, no stubs):**

1. **Wire protocol + 3-way handshake + graceful teardown.** A real header
   (seq/ack/flags/window/checksum + optional SACK blocks), a real RFC 1071
   one's-complement checksum, SYN→SYN-ACK→ACK, FIN/ACK teardown with a
   linger period for straggler retransmissions — all driven over actual
   `socket.socket` UDP endpoints.
2. **Reliable, in-order, exactly-once delivery over a lossy link.**
   Sliding-window transmission, genuine receiver-side out-of-order
   buffering with real selective-ACK generation (verified directly against
   internal state, not just inferred from a successful transfer),
   retransmission on timeout, and correct behavior across 32-bit
   sequence-number wraparound.
3. **RTO estimation with Karn's algorithm.** Jacobson/Karels SRTT/RTTVAR
   (RFC 6298), a single per-connection retransmission timer tied to
   `send_una` (not "whichever segment looks oldest"), exponential backoff
   on repeated timeout, backoff reset on any cleanly-sampled RTT.
4. **Reno-style congestion control.** Slow start, additive-increase
   congestion avoidance, fast retransmit on 3 duplicate ACKs, fast
   recovery — real cwnd traces showing the textbook ramp and sawtooth,
   captured from actual runs, not scripted.

**Stretch (both shipped):**

5. **Interactive HTML trace visualizer** (`viz/index.html`) — cwnd-vs-time
   (color-coded by congestion-control state), an RTO-estimate chart, and a
   packet-event timeline (sent/retransmit/RTO-timeout/fast-retransmit/
   persist-probe/window-update/ACK), rendered from a real recorded trace.
   Verified with zero console errors in headless Chromium.
6. **A second, delay-based congestion controller (simplified TCP Vegas)**
   plus `transfer.py compare`, which runs the *same* payload over the
   *same* real bottleneck link once with each controller and reports the
   difference. On the default settings this is an 11-38x speed difference
   in Vegas's favor — not narrated, measured from two independent live
   transfers, because Vegas backs off from a forming queue *before* it
   overflows, while Reno (without SACK-based recovery) only finds out
   after a burst of packets is already gone and has to recover them one
   RTO at a time. See `REVIEW.md`'s Phase 4 section for the full trace of
   how that difference was found and confirmed real, not a bug in either
   controller.

Beyond the plan's floor: real defensive receive-window enforcement, a
zero-window deadlock fix (both the receiver-side proactive window-update
*and* the sender-side persist-probe half, because either alone can be
lost), a real `abort()`/RST path, and a real bottleneck-queue network
model (rate + buffer + tail-drop, not just independent random loss) used
by the Reno/Vegas comparison.

## Why I chose this today

This repo has, at this point, built almost every *layer above* the
transport: an OS scheduler (Quantum), a blockchain's P2P gossip over raw
TCP sockets without ever questioning what TCP does for it (Vein), a CRDT
editor assuming a working byte pipe (Concord), a market matching engine, a
SLAM simulator, nine-plus language runtimes. Nothing had gone one layer
lower and asked what actually turns an unreliable, unordered, duplicate-
happy datagram service into the reliable stream all of that quietly
depends on. It's also one of the few domains in this repo's history where
the two obvious "does it work" checks — is the data correct, and does the
sender behave well under contention — are genuinely different questions
requiring genuinely different verification, and where "looks like it
works" and "is provably correct" diverge hardest: the real bugs (see
`REVIEW.md`) all lived exactly in the conditions a single happy-path
demo never hits — out-of-order arrival, a duplicate ACK racing its own
retransmission, a window that reopens with nothing to announce it, a
sequence number crossing 2^32.

## Where a human could take this next

- **SACK-based multi-segment recovery.** Undertow already generates real
  SACK blocks on the receive side; the sender doesn't yet use them to
  recover more than one lost segment per RTT. This is the literal reason
  real TCP eventually got SACK/NewReno, and REVIEW.md's Phase 4 finding
  shows exactly the pathology (classic Reno needing one full RTO per lost
  segment in a burst) that acting on those SACK blocks would fix.
- **Window scaling.** The advertised window is capped at 16 bits (65535
  bytes) like un-extended TCP; a real high-bandwidth-delay-product link
  would want RFC 1323-style scaling.
- **A third congestion controller (BBR-lite)** modeling bandwidth and
  min-RTT directly instead of a cwnd-based signal, compared against both
  Reno and Vegas in the same harness.
- **NAT-less multi-client rendezvous.** Undertow is deliberately
  point-to-point (both peers' addresses known up front, like the
  `NetworkSimulator` relay); a listener that can accept many distinct
  clients on one bound port (demultiplexing by source address, like real
  UDP servers) is a natural next step for the `serve` CLI.
- **Congestion-controller pluggability at the CLI/socket-API layer** is
  already there (`congestion_controller_factory`); a REPL or live-tunable
  parameter set (alpha/beta/gamma for Vegas, the AIMD constants for Reno)
  would make the comparison tooling useful for teaching, not just for
  this repo's own verification.
