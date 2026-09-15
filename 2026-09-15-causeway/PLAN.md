# Causeway — a from-scratch reliable transport protocol

## Concept

Every packet-switched network is, underneath, a best-effort service: packets
get dropped, reordered, duplicated, and delayed unpredictably. The entire
practical value of TCP (and QUIC after it) is a thin layer of bookkeeping that
turns that chaos into something an application can pretend is a reliable,
ordered, flow-controlled pipe. Causeway builds that layer from scratch on top
of raw UDP: real sequence numbers and acknowledgments, real retransmission
timers driven by a live RTT estimator, a real TCP-Reno-style congestion
controller, and real receiver-side flow control — all running over an
actual lossy, reordering, jittery network (real OS UDP sockets forwarded
through a hand-written "lossy proxy" process, not a mocked channel).

## Why it's interesting

This repo has built distributed systems before (Quorum's Raft, Concord's
CRDT editor, Vein's blockchain, Matchbook's matching engine, Beacon's SLAM),
but every one of them assumed a transport layer already existed underneath
it and focused on the logic running *on top* of the network. Causeway is
the first build to go one layer down and implement the transport itself —
the part everything else quietly depends on. It's also the first build in
this repo where "correctness" is inseparable from *performance under
adversity*: a transport that never loses a byte but stalls for a minute on
a single dropped packet is exactly as much a failure as one that corrupts
data, so this project's own adversarial testing has to attack it on both
axes at once (byte-exact correctness AND throughput/latency behavior) using
a real lossy network, not a canned scenario.

## Architecture

```
Application (file bytes in / bytes out)
        |
   Connection  (per-connection state machine: SYN/SYN-ACK/ACK handshake,
        |        ESTABLISHED data phase, FIN/FIN-ACK/TIME-WAIT close)
        |
   SendBuffer + RetransmitQueue      RecvBuffer + Reassembly
        |   (cwnd, ssthresh,                |  (out-of-order buffer,
        |    Reno state machine,            |   cumulative ACK,
        |    RTO timer per segment)         |   advertised window)
        |__________________________________|
                        |
                Segment codec (header: seq, ack, flags, window,
                checksum, payload) <-> bytes
                        |
        Wire  (a Socket-like interface: either an in-process
        DeterministicNet for fast seeded unit tests/benchmarks,
        or a real UDP socket talking through causeway.proxy —
        a standalone process that forwards real UDP datagrams
        between two ports while dropping / delaying / reordering /
        duplicating a configurable fraction of them)
```

Two wire implementations share one `Connection` engine, so the exact same
protocol code that gets fuzz-tested deterministically in-process is the code
that drives the real two-process, real-socket file transfer demo — no
reimplementation gap between "what's tested" and "what runs."

## Feature list

**Required (4):**

1. **Reliable, ordered, exactly-once delivery over an unreliable channel.**
   Sequence numbers + cumulative ACKs + checksums, retransmission on timeout,
   duplicate suppression, out-of-order buffering with in-order reassembly on
   delivery to the application. Proven with a real byte-exact file transfer
   through a real lossy/reordering/duplicating UDP proxy, verified by
   SHA-256 checksum.

2. **Adaptive retransmission timeout (Jacobson/Karels RTT estimation).**
   SRTT/RTTVAR-driven RTO that tracks a simulated link's actual delay and
   jitter, shown to avoid both a retransmit storm (RTO set too low) and
   multi-second stalls (RTO set too high) across a range of simulated
   latencies.

3. **TCP-Reno-style congestion control.** Slow start, congestion avoidance,
   fast retransmit + fast recovery on 3 duplicate ACKs, and timeout-triggered
   slow-start restart with ssthresh halving — demonstrated by reproducing the
   classic congestion-window sawtooth under simulated packet loss.

4. **Flow control independent of congestion control.** A receiver-advertised
   window (based on actual free buffer space) that throttles a fast sender
   even at zero loss and an unbounded congestion window, proving the two
   control loops are genuinely decoupled rather than one masquerading as
   both.

**Stretch (2+):**

5. **Interactive visualizer.** A self-contained HTML/canvas timeline
   (cwnd, ssthresh, RTT/RTO, in-flight bytes, throughput) rendered from a
   real captured event log of an actual transfer run, headless-browser
   verified with zero console errors.

6. **Robust connection lifecycle + live two-process capstone demo.**
   Graceful FIN/FIN-ACK/TIME-WAIT-style half-close that survives a lost FIN
   (retransmission-safe teardown, no half-open leaks), plus a real
   `causeway send` / `causeway recv` CLI pair — two independent OS processes
   talking real UDP through the lossy proxy process — transferring an
   arbitrary file end-to-end with a live progress readout and a final
   checksum verification.

## Stack

Pure Python 3 stdlib only (`socket`, `threading`, `hashlib`, `struct`,
`argparse`) — no networking framework, no asyncio-based transport helpers on
the protocol path. Self-contained HTML/CSS/vanilla-JS visualizer, no build
step. Playwright/Chromium (pre-installed) for a headless-browser smoke test
of the visualizer only. `unittest` for the test suite.
