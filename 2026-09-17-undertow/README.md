# Undertow

A from-scratch, packet-level network simulator implementing real TCP
congestion-control algorithms — Reno, CUBIC, and a BBR-lite — to
*reproduce* textbook-verifiable phenomena as automated, assertion-checked
experiments rather than hand-waved charts: AIMD fairness convergence
(Chiu & Jain, 1989), Reno's RTT unfairness and CUBIC's documented fix for
it (RFC 8312), bufferbloat under drop-tail queueing and RED's fix for
that, and BBR's shallow-queue property versus loss-based control.

Every number in this README came out of an actual run of the simulator
(`python3 -m src.cli ...`), not an illustration.

## Why this, today

Every prior "distributed systems" build in this repo (Raft, an RGA CRDT,
Nakamoto consensus, an exchange matching engine) modeled the
*coordination* layer — who agrees on what, or who gets to trade at what
price. None has modeled the layer directly underneath: the transport
protocol deciding, packet by packet, how fast one machine may push bytes
at another without melting the shared link in between. Congestion control
is one of the few corners of applied CS with genuinely counter-intuitive,
textbook-provable ground truth you can reproduce in a simulator instead
of taking on faith — and reproducing it requires modeling a **shared,
contended physical resource** under **cooperative-but-selfish** dynamics,
which nothing in this repo has done before (closest precedent is Beacon's
uncertain-sensor SLAM, but that's single-agent).

It also turned out to be an unusually good stress test of this repo's own
review discipline: getting the simulator's *physics* right (a real FIFO
queue, real serialization delay, real cumulative ACKs) was the easy part.
Getting the demonstrations to reliably show the textbook result, instead
of an artifact of simulating without real-world noise, took a real
adversarial pass — see [REVIEW.md](./REVIEW.md).

## How to run it

```bash
# full test suite
python3 -m pytest tests/ -q

# every feature, one command each — or just run the whole thing:
./demo.sh

# individual scenarios:
python3 -m src.cli single --algo reno --duration 20
python3 -m src.cli single --algo cubic --duration 20
python3 -m src.cli single --algo bbr --duration 20
python3 -m src.cli fairness --algo reno --duration 40 --flows 2
python3 -m src.cli rtt-unfairness --algo cubic --duration 60
python3 -m src.cli bufferbloat --algo reno --duration 30          # drop-tail
python3 -m src.cli bufferbloat --algo reno --duration 30 --red    # RED
python3 -m src.cli bbr-vs-loss --algo cubic --duration 30
python3 -m src.cli single --algo reno --duration 20 --out result.json  # export JSON

# regenerate the visualizer's data and open it in a browser:
python3 scripts/make_visualizer_data.py
open visualizer/index.html   # or just double-click it — no server needed
```

No dependencies beyond the Python 3 standard library for the simulator
itself; `pytest` for the test suite; a browser (no build step, no server)
for the visualizer.

## Feature list

**Required (all 4 shipped, working end-to-end):**

1. **Packet-level discrete-event network core** (`src/network.py`) — real
   `Packet`s traveling over real links (propagation delay + finite
   bandwidth ⇒ real serialization time) through a single shared
   `Bottleneck` FIFO queue with drop-tail *or* RED admission control.
   Every physical transmission is tracked to a network-wide conservation
   invariant (delivered, dropped, or still in flight — never anything
   else), checked by `tests/test_invariants.py`.
2. **TCP Reno** (`src/congestion/reno.py` + the shared loss-recovery
   machinery in `src/flow.py`) — slow start, AIMD congestion avoidance,
   NewReno-style (RFC 6582) triple-dup-ACK fast retransmit and fast
   recovery, RFC 6298 Jacobson/Karels RTO estimation with exponential
   backoff. On a 2 Mbps link: **94–100% utilization**.
3. **TCP CUBIC** (`src/congestion/cubic.py`) — the real RFC 8312 cubic
   growth function `W(t) = C(t-K)³ + Wmax` plus the TCP-friendly region,
   sharing the same loss-recovery machinery. On the same link:
   **98–100% utilization**.
4. **Fairness experiment harness** (`src/experiments.py`) — runs N
   concurrent flows over one shared bottleneck and measures Jain's
   fairness index and pooled throughput ratios as *outcomes* of the
   simulation:
   - Two identical-RTT Reno flows converge to a fair split: **Jain's
     index ≈0.99** over the full run (`test_fairness.py`).
   - Reno, RTT ratio 4:1: short-RTT flow gets a pooled **~1.1–1.5x**
     share (RTT unfairness, reproduced, pooled over 15 trials to smooth
     out single-run RTO-timing noise — see REVIEW.md #3).
   - CUBIC on the *identical* topology: pooled ratio **~0.9–1.1x** —
     measurably fairer than Reno, exactly as RFC 8312 intends.

**Stretch (both shipped):**

5. **BBR-lite** (`src/congestion/bbr.py`) — a real bandwidth-delay-product
   controller (STARTUP/DRAIN/PROBE_BW/PROBE_RTT state machine over
   windowed bandwidth/RTT filters). Head-to-head against CUBIC on an
   identically generously-buffered bottleneck, both near 100%
   utilization: **BBR holds a ~6-packet mean queue; CUBIC fills the
   buffer to ~100+ packets.** This is BBR's entire reason for existing,
   reproduced end-to-end (`tests/test_bbr.py`).
6. **Bufferbloat + RED demo, with an interactive HTML visualizer**
   (`visualizer/index.html`) — a bulk Reno flow sharing a deep drop-tail
   queue with a latency-sensitive "ping" flow: the ping flow's RTT
   balloons to **26x** its base RTT. RED on the identical scenario cuts
   that to **~11x** while keeping >98% utilization. The visualizer (dark
   dashboard, five panels, zero dependencies, no build step, no server —
   just open the file) renders all five headline results from real
   exported simulator data; smoke-tested with headless Chromium for zero
   console errors and correct rendering on both desktop and 390px mobile
   viewports.

## Adversarial review

Six real bugs were found and fixed during Phase 3 — including a runaway
congestion-window bug that could stall a flow indefinitely, and a
determinism artifact in the network simulator itself that could let one
flow permanently starve another regardless of which congestion-control
algorithm was under test. Full writeup, root causes, and fixes in
[REVIEW.md](./REVIEW.md).

## Known, deliberate simplifications

Documented in code and in REVIEW.md's "known, deliberate simplifications"
section: no SACK (classic cumulative-ACK recovery only — the historically
accurate choice, and the reason a multi-segment loss burst is expensive
to recover from), BBR is intentionally "-lite" (cwnd-based rather than
independently rate-paced, a shortened PROBE_BW gain cycle), CUBIC omits
HyStart. None of these are accidental — each is called out where it
matters, with the real-world context for why it's a reasonable line to
draw for this build.

## Where a human could take this next

- **Add SACK.** This is the single highest-leverage next step: with
  selective acknowledgment, a sender can repair every lost segment in one
  round trip instead of one per RTT, which would change (and make far
  less fragile) exactly the multi-segment-loss scenarios that Phase 3's
  hardest bugs came from.
- **Real rate pacing.** BBR-lite controls cwnd because this simulator's
  senders are window-clocked; a real pacer (send at a target rate,
  independent of the ACK clock) would let BBR (and a paced CUBIC) behave
  more like their real-world counterparts, and would open the door to
  studying ACK-compression and pacing-related bugs that are a real
  source of production incidents.
- **Multi-hop topologies.** Everything here is a single dumbbell
  bottleneck; a real topology (multiple hops, multiple simultaneously
  contended links, cross-traffic) would let the fairness/RTT-unfairness
  experiments generalize past the two-flow case (the n_flows=3 case was
  tried during this build and hit exactly the kind of buffer/fairness
  sensitivity documented in REVIEW.md — a richer topology and larger
  buffers sized to the actual aggregate BDP would be the natural fix).
- **A live/interactive mode for the visualizer.** Right now it renders a
  pre-generated snapshot; wiring it to a WebSocket feed from a live
  Python simulation (à la Quantum's or Beacon's replay visualizers, but
  streaming instead of static) would make it a real teaching tool for
  watching the AIMD sawtooth and BBR's probe cycles happen live.
- **Explicit Congestion Notification (ECN).** A natural complement to
  RED: instead of dropping a packet as the early-warning signal, mark it
  and let the sender react without a retransmission at all — directly
  extends the bufferbloat/RED experiment already in place.
