# Undertow — a reliable transport protocol from scratch, over raw UDP

## Concept

Every prior "from scratch, real protocol" build in this repo's history has
picked a fixed point *above* or *beside* the transport layer: Vein gossips
over real TCP sockets but never questions what TCP gives it for free; Concord
assumes a working byte pipe (SSE) between browser tabs; Quorum's Raft runs
over a deterministic in-memory network with no packet format at all. Nothing
in this repo has built the layer underneath all of them — the part of the
Internet stack that turns an unreliable, unordered, duplicate-happy packet
service (UDP, or IP itself) into the reliable, in-order, congestion-aware
byte stream every higher protocol quietly assumes exists.

Undertow is that layer: a TCP-shaped reliable transport protocol, implemented
from scratch on top of raw UDP sockets — real segments, a real 16-bit
one's-complement checksum, a real 3-way handshake, sequence-number
arithmetic that is correct across 32-bit wraparound, a Jacobson/Karels RTO
estimator with Karn's algorithm, selective acknowledgment, and a genuine
Reno-style congestion controller (slow start → congestion avoidance → fast
retransmit → fast recovery) whose window trace is not scripted but is the
literal output of running the algorithm against a lossy, reordering,
duplicating, latency-jittered simulated network link.

## Why it's interesting

Reliable delivery over an unreliable channel is one of the few areas of
systems software where "it looks like it works" and "it is actually correct"
diverge hardest — bugs hide in exactly the conditions a happy-path demo never
hits: packets that arrive out of order, a duplicate ACK arriving after its
own retransmission already succeeded, a timer firing during a window-full
condition, a sequence number wrapping past 2^32-1 mid-transfer. And the
congestion-control half has a second kind of correctness that plain
distributed-systems builds in this repo (Quorum, Concord, Vein) never had to
answer: not just "is the data correct" (it must be, always) but "does the
sender behave well under contention" — cwnd must provably grow like TCP
Reno's textbook sawtooth, not just "seem to send stuff".

## Architecture

```
undertow/
  seqmath.py     RFC-1982 serial-number arithmetic (wraparound-safe seq
                 comparison/distance) — the foundation every other module
                 trusts for "is A before B" once seq numbers wrap.
  packet.py      Wire format: struct-packed header (seq, ack, flags,
                 window, checksum, optional SACK blocks) + payload;
                 encode/decode/checksum, all round-trip and corruption
                 tested.
  rto.py         Jacobson/Karels SRTT/RTTVAR RTO estimator + Karn's
                 algorithm (never sample RTT from a retransmitted segment)
                 + exponential backoff on repeated timeout.
  congestion.py  Pluggable congestion controllers: Reno (slow start, AIMD
                 congestion avoidance, fast retransmit on 3 dup-ACKs, fast
                 recovery) and a stretch delay-based controller (Vegas-lite)
                 that reacts to rising RTT instead of only to loss.
  connection.py  The actual protocol state machine: 3-way handshake,
                 sliding-window send/receive over a byte stream, receiver
                 out-of-order buffering + SACK generation, retransmission
                 on RTO, graceful FIN/ACK teardown. Talks to any object with
                 .send_packet()/.recv_packet() — real UDP socket or the
                 simulator.
  netsim.py      NetworkSimulator: an actual relay sitting between two real
                 UDP sockets that independently drops / duplicates /
                 reorders / delays datagrams under a seeded RNG, so every
                 property below is demonstrated against a real link, not
                 asserted about one.
  socket_api.py  UndertowSocket: connect()/listen()/accept()/send()/recv()/
                 close() wrapping connection.py over real socket.socket
                 UDP endpoints — the public API applications use.
transfer.py      File-transfer CLI built on socket_api: undertow send/recv,
                 SHA-256 of the file verified equal on both ends after a
                 transfer across the lossy simulator.
viz/             trace.py (records every packet/RTT/cwnd event during a
                 real run to JSON) + index.html (self-contained visualizer:
                 cwnd-over-time graph, packet timeline, RTT samples).
tests/           unit + property + end-to-end tests.
```

## Features

**Required (core, must work end-to-end, no stubs):**

1. **Wire protocol + 3-way handshake + graceful teardown.** Real UDP
   datagrams with a real header (seq/ack/flags/window/checksum), a genuine
   SYN → SYN-ACK → ACK handshake establishing per-direction initial sequence
   numbers, and FIN/ACK teardown — driven over actual `socket.socket`
   UDP sockets between two independent Python processes.
2. **Reliable, in-order, exactly-once byte-stream delivery over a lossy
   link.** Sliding-window transmission, receiver out-of-order buffering,
   cumulative + selective ACKs, retransmission on timeout — proven by
   transferring a real multi-megabyte file across `NetworkSimulator` with
   nontrivial loss/duplicate/reorder/jitter and diffing SHA-256 before and
   after. Sequence-number wraparound is handled correctly (tested by
   starting a connection's ISN deliberately near 2^32-1).
3. **RTO estimation with Karn's algorithm.** Jacobson/Karels SRTT/RTTVAR,
   never sampling RTT from a retransmitted segment (proven by a test that
   would mis-estimate RTO if Karn's algorithm were skipped), exponential
   backoff on repeated timeouts.
4. **Reno-style congestion control.** Slow start (exponential cwnd growth
   to ssthresh), congestion avoidance (linear AIMD growth), fast retransmit
   on 3 duplicate ACKs, fast recovery — with the resulting cwnd trace from
   a real run showing the textbook slow-start ramp and congestion-avoidance
   sawtooth, not asserted but rendered from real trace data.

**Stretch (2+):**

5. **Interactive HTML visualizer** rendering a real transfer's recorded
   trace: cwnd-vs-time graph (slow start ramp + AIMD sawtooth + fast-recovery
   dips clearly visible), a packet timeline (sent/ACKed/lost/retransmitted,
   color-coded), and an RTT/RTO chart.
6. **A second, delay-based congestion controller (Vegas-lite)** selectable
   alongside Reno, plus a head-to-head comparison mode that runs the same
   file transfer under both controllers over the *same seeded network
   trace* and reports throughput/retransmit-count/loss-triggered-vs-delay-
   triggered backoff differences — a real A/B, not a narrated one.

## Verification strategy

Every claim above gets an independent check: checksum against a hand-rolled
reference implementation of the RFC 1071 algorithm; sequence-arithmetic
wraparound tested at the exact 2^32 boundary; sliding-window correctness
fuzzed against randomized loss/dup/reorder profiles with byte-exact output
checked every time; RTO math checked against hand-computed SRTT/RTTVAR
sequences; congestion-window growth checked against the textbook Reno
formulas (cwnd doubles per RTT in slow start, +MSS²/cwnd per ACK in
congestion avoidance, halves on loss) rather than just eyeballing a chart.
