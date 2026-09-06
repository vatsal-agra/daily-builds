# Throttle — a from-scratch TCP transport-protocol & congestion-control simulator

## Concept

Every prior build in this repo that touches "the network" has stayed at the
application/consensus layer (Quorum's Raft cluster, Matchbook's exchange,
Beacon's robot) or skipped the network entirely. None has gone one layer
down to the actual **transport protocol** that carries every one of those
byte streams across a real, lossy, bandwidth-limited wire. Throttle builds
that layer from first principles: a packet-level discrete-event network
(bottleneck link with finite bandwidth, propagation delay, a real drop-tail
buffer, loss and reordering) carrying a real TCP implementation — three-way
handshake, byte-stream sliding-window flow control with out-of-order
reassembly, cumulative/duplicate ACKs, Jacobson/Karels RTT estimation with
Karn's algorithm, RTO with exponential backoff, and pluggable congestion
control (Reno, Tahoe, and a simplified CUBIC) — with multiple competing
flows sharing one bottleneck so that fairness, RTT bias, and algorithm
differences *emerge* from packet collisions in a shared buffer instead of
being asserted.

## Why it's interesting

TCP congestion control is one of the most consequential pieces of applied
control theory ever deployed — a decentralized, no-coordination algorithm
that keeps the entire internet from collapsing under its own load, purely
by having every sender probe for capacity and back off on loss. Its
correctness is *empirically checkable* against textbook predictions that
don't require trusting "it looks plausible":

- Slow start must double `cwnd` roughly every RTT until `ssthresh`.
- Congestion avoidance must grow `cwnd` by ~1 MSS per RTT (AIMD sawtooth).
- Two Reno flows with equal RTT sharing a bottleneck must converge to
  roughly equal throughput (the classic AIMD fairness result).
- Two Reno flows with *different* RTT must split throughput roughly
  inversely proportional to RTT (well-known TCP RTT-unfairness) — the
  window in congestion avoidance is a *per-RTT* increment, so more RTTs
  per second means faster growth.
- Reno vs. Tahoe after a loss: Tahoe collapses to slow start (cwnd→1 MSS),
  Reno fast-recovers (cwnd→ssthresh) — Reno must finish transfers faster
  under light loss.
- CUBIC vs. Reno on a high bandwidth-delay-product link: CUBIC's cubic
  window-growth function must achieve higher steady-state utilization than
  Reno's linear growth — the actual historical reason CUBIC replaced Reno
  as Linux's default.

Every one of those is a falsifiable, measurable claim this build can be
checked against with its own instrumentation, not just "looks like a nice
sawtooth graph."

## Architecture

```
throttle/
  packet.py       Segment (TCP header fields) + Packet (network-layer envelope)
  network.py      Simulator (heap-based discrete-event loop), Link (bandwidth +
                   propagation delay + drop-tail buffer + loss/reorder),
                   AccessLink (per-flow propagation-delay-only leg), Topology
                   (dumbbell: N per-flow access legs -> 1 shared bottleneck)
  rtt.py          RttEstimator: Jacobson/Karels SRTT/RTTVAR/RTO (RFC 6298),
                   Karn's algorithm (no RTT sample from a retransmitted segment),
                   exponential RTO backoff on repeated timeout of the same segment
  congestion.py   CongestionControl ABC + Reno, Tahoe, Cubic implementations
                   (slow start, congestion avoidance, fast retransmit/recovery,
                   timeout response) as pluggable strategies
  tcp.py          TcpSender (byte-stream send buffer, cwnd/rwnd-limited sliding
                   window, retransmission queue, RTO timer, dup-ACK counting) and
                   TcpReceiver (out-of-order reassembly buffer, cumulative ACK
                   generation, advertised receive window) + TcpConnection wiring
                   both ends through a Topology with a full SYN/SYN-ACK/ACK
                   handshake and FIN teardown
  experiment.py   Multi-flow experiment harness: builds a topology + N flows,
                   runs the simulator to completion, records per-flow time
                   series (cwnd, RTT, in-flight bytes) and summary statistics
                   (throughput, completion time, retransmissions, timeouts,
                   Jain's fairness index), plus canned experiments 1-5 below
  viz.py          Self-contained interactive HTML report: cwnd sawtooth +
                   queue-occupancy + throughput + RTT time series per
                   experiment (inline SVG, no JS dependency, theme-aware)
  cli.py          `throttle` CLI: run / experiment / viz / demo
tests/            unit + property tests for every module above
demo.sh           end-to-end script exercising every feature, must exit 0
```

## Feature list

**Required (core, must work end-to-end with zero stubs):**

1. **Packet-level discrete-event network** — a real event-driven simulator
   (heapq-based clock), a shared bottleneck `Link` modeling finite
   bandwidth (serialization delay), a fixed propagation delay, a
   finite drop-tail FIFO buffer (packets dropped on overflow, not
   probability-faked), and independently configurable random loss and
   reordering probabilities.
2. **Full TCP protocol state machine** — real 3-way handshake (SYN /
   SYN-ACK / ACK) with random ISNs, a byte-stream (not packet-count)
   sliding window with a receiver-side out-of-order reassembly buffer,
   cumulative ACKs, duplicate-ACK generation on gaps, advertised receive
   window (`rwnd`) flow control, and FIN/ACK teardown.
3. **Real congestion control** — Reno (slow start, congestion avoidance,
   fast retransmit on 3 dup ACKs, fast recovery with window inflation),
   Jacobson/Karels RTT estimation (SRTT/RTTVAR → RTO per RFC 6298) with
   Karn's algorithm and exponential RTO backoff on repeated timeouts.
4. **Multi-flow fairness experiments** — several TCP flows (mixed
   algorithms, mixed per-flow RTT via a dumbbell topology) sharing one
   bottleneck link, producing measured (not scripted) throughput,
   completion time, retransmission counts, and a Jain fairness index.

**Stretch (2+, at least 1 shipped):**

5. TCP **Tahoe** and a simplified but real **CUBIC** window-growth function,
   so experiments 3 and 4 above (Reno-vs-Tahoe, Reno-vs-CUBIC) are real
   comparisons between distinct, independently implemented algorithms.
6. An interactive, self-contained **HTML visualizer** — per-flow cwnd
   sawtooth, shared-queue occupancy, aggregate throughput, and RTT/RTO
   time series, rendered as inline SVG with a legend and hover tooltips,
   theme-aware (light/dark), no build step, no external JS.
7. **SACK** (Selective Acknowledgment, RFC 2018) as an optional receiver
   capability, letting the sender retransmit only the specific missing
   ranges a receiver reports instead of just the oldest unacked byte.

## Success gates

- Every required feature demonstrated end-to-end against a real
  measurable prediction (not eyeballed): slow-start doubling rate,
  AIMD sawtooth shape, fairness convergence, RTT-bias ratio, drop-tail
  loss under overflow, retransmission after real timeout/dup-ACK
  triggers, handshake and teardown completing correctly, byte-for-byte
  correct reassembly of the full transferred payload at the receiver
  (checksummed) even with reordering and loss injected.
