# Throttle

A from-scratch **TCP transport-protocol and congestion-control simulator**.
A packet-level discrete-event network — a bandwidth-limited bottleneck
link with propagation delay, a real drop-tail buffer, and configurable
loss/reordering — carries a real TCP implementation: a 3-way handshake,
byte-stream sliding-window flow control with out-of-order reassembly,
cumulative/duplicate ACKs, Jacobson/Karels RTT estimation with Karn's
algorithm, RTO backoff, and pluggable Reno/Tahoe/CUBIC congestion control
with optional RFC 2018 SACK. Multiple flows can share one bottleneck, so
fairness, RTT bias, and algorithm differences *emerge* from real packet
collisions in a shared buffer rather than being scripted.

## Why this, today

Every prior build in this repo that has touched "the network" has stayed
at the application/consensus layer (a Raft cluster, an exchange matching
engine, a robot's sensor model) or skipped it entirely. None has gone one
layer down to the actual transport protocol carrying every one of those
byte streams across a real, lossy, bandwidth-limited wire. TCP congestion
control is also one of the most consequential pieces of applied control
theory ever deployed — a fully decentralized algorithm, with no
coordination between senders, that keeps the entire internet from
collapsing under its own load. And unlike a lot of "does this look
plausible" simulation work, its behavior is *falsifiable* against
textbook predictions this build checks itself against: slow start should
double `cwnd` roughly every RTT; congestion avoidance should grow it
~1 MSS/RTT; equal-RTT flows should converge to equal shares; different-RTT
flows should split unevenly in a specific, predictable direction; Tahoe
should lose to Reno under loss; CUBIC should win on high bandwidth-delay
paths; SACK should recover from multi-segment loss faster than plain
Reno. Every one of those claims is measured by this codebase's own
instrumentation and asserted on in its test suite — not eyeballed.

## How to run it

```bash
cd 2026-09-06-throttle

# run the test suite
python3 -m pytest -q                        # 67 tests

# transfer a byte stream over a simulated link
python3 -m throttle.cli run --bytes 1000000 --cc reno --loss 0.01

# run one of the canned multi-flow experiments
python3 -m throttle.cli experiment fairness-equal-rtt
python3 -m throttle.cli experiment rtt-unfairness
python3 -m throttle.cli experiment reno-vs-tahoe
python3 -m throttle.cli experiment reno-vs-cubic     # comparison: 2 independent runs
python3 -m throttle.cli experiment reno-vs-sack      # comparison: 2 independent runs

# generate the full interactive HTML report (all 8 experiments)
python3 -m throttle.cli viz report.html

# run everything and print a summary
python3 -m throttle.cli demo

# full end-to-end verification (23 checks: every feature, every CLI path,
# invalid-input handling, a headless-browser check on the report)
./demo.sh
```

`throttle run --help` and `throttle experiment --help` list every knob
(bandwidth, buffer size, propagation delay, loss/reorder probability,
receive window, congestion-control algorithm, SACK, random seed, time
cap).

## Full feature list

**Required (all 4 shipped, end-to-end, no stubs):**

1. **Packet-level discrete-event network** (`network.py`) — a heap-based
   event clock; a shared bottleneck `Link` with finite bandwidth (real
   serialization delay), fixed propagation delay, a finite drop-tail FIFO
   buffer (packets actually dropped on overflow, not a probability
   standing in for it), and independent random loss/reordering; a
   per-flow `AccessLink` for a dumbbell topology so competing flows can
   have different RTTs.
2. **Full TCP protocol state machine** (`tcp.py`) — 3-way handshake with
   random ISNs (and a real fix for a lost-final-ACK deadlock — see
   `REVIEW.md`), a byte-stream (not packet-count) sliding window, a
   receiver-side out-of-order reassembly buffer, cumulative and duplicate
   ACKs, advertised receive-window flow control, and FIN/ACK teardown.
3. **Real congestion control** (`congestion.py`, `rtt.py`) — Reno (slow
   start, congestion avoidance, fast retransmit on 3 dup ACKs, fast
   recovery with window inflation/deflation), Jacobson/Karels RTT
   estimation (RFC 6298) with Karn's algorithm and exponential RTO
   backoff.
4. **Multi-flow fairness experiments** (`experiment.py`) — several TCP
   flows (mixed algorithms, mixed RTT via the dumbbell topology) sharing
   one bottleneck, producing *measured* throughput, completion time,
   retransmission counts, and a Jain fairness index.

**Stretch (all 3 shipped):**

5. **TCP Tahoe and a simplified but real CUBIC** (`congestion.py`) —
   independent congestion-control implementations enabling genuine
   algorithm-vs-algorithm comparisons (`reno-vs-tahoe`, `reno-vs-cubic`).
6. **Interactive HTML visualizer** (`viz.py`) — per-experiment cwnd
   sawtooth, shared-queue occupancy, and smoothed-RTT time series as
   hand-rolled inline SVG, theme-aware (light/dark), no build step, zero
   external dependencies, verified with a headless-Chromium
   zero-console-error check.
7. **RFC 2018 SACK** (`tcp.py`) — the receiver reports up to 3 specific
   out-of-order byte ranges it already holds; the sender retransmits
   precisely the outstanding holes the scoreboard says are still missing,
   instead of one segment per RTO timeout. This directly fixes the
   Reno-without-SACK slow-recovery limitation found during the adversarial
   review (`REVIEW.md`) — a stretch feature that patches a real, earlier
   finding rather than an unrelated add-on.

**Verification:** 67 pytest unit/integration tests, 600+ randomized fuzz
runs across single- and multi-flow scenarios (0 crashes, 0 reassembly
mismatches), and `demo.sh`'s 23-check end-to-end run.

## Deliberate simplifications (all documented in code, not hidden)

- Sequence numbers are unbounded Python ints — no 32-bit wraparound.
- One-directional bulk transfer (sender → receiver; only ACKs flow back),
  like the response side of an HTTP GET.
- No delayed-ACK coalescing — every segment is ACKed immediately, for
  exact RTT sampling and dup-ACK counting.
- Fast recovery is classic Reno, not NewReno (a real, named Reno
  limitation, not a shortcut).
- CUBIC omits Linux's "TCP-friendly region" blend, implementing the actual
  cubic growth function that gives the algorithm its name without the
  full production heuristic.
- SACK's sender-side hole-retransmission is a real but simplified
  scoreboard mechanism, not RFC 6675's full pipe/rescue-retransmission
  accounting.

See `REVIEW.md` for the adversarial-review process: two critical bugs
(a crash on a lost/timed-out SYN, and a deadlock on a lost final handshake
ACK) plus a subtle bug in the review tooling itself (a `Simulator.run()`
fix that silently corrupted every duration/throughput figure) were found
by fuzzing and manual review, fixed, and covered by regression tests.

## Where a human could take this next

- **NewReno / RFC 6675 SACK-aware loss recovery** — proper partial-ACK
  handling and pipe/rescue-retransmission accounting instead of this
  build's simplified scoreboard.
- **BBR** — a genuinely different (model-based, not loss-based) congestion
  control paradigm; the `CongestionControl` interface here is already
  built to make that a self-contained addition.
- **ECN** (Explicit Congestion Notification) — let the bottleneck `Link`
  mark packets instead of only dropping them, and have congestion control
  react to marks as an earlier, lossless signal.
- **Real 32-bit sequence-number wraparound** and PAWS (Protection Against
  Wrapped Sequences) — currently out of scope by design, but a natural
  "harden it for real deployment" follow-up.
- **A live packet-flow animation** in the HTML report (the current
  visualizer shows time-series charts; an animated packet-by-packet replay
  over the topology, in the spirit of Beacon's or Matchbook's replay
  viewers, would make the queueing/loss dynamics even more legible).
- **Multi-bottleneck topologies** (more than one shared link in series) to
  study how congestion signals compose across hops.
