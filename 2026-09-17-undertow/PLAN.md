# Undertow — a from-scratch TCP congestion-control simulator

## Concept

Every "distributed systems" build in this repo so far (Quorum's Raft,
Concord's RGA CRDT, Vein's Nakamoto consensus, Matchbook's matching engine)
has modeled the *coordination* layer — who agrees on what. None has modeled
the layer directly underneath: the transport protocol that decides, packet
by packet, how fast one machine is allowed to push bytes at another without
melting the network in between. That's TCP congestion control, and it is
one of the few areas of applied computer science with genuinely
counter-intuitive, textbook-verifiable ground truth you can reproduce in a
simulator rather than take on faith:

- Two competing flows with **additive-increase / multiplicative-decrease**
  (AIMD) converge to a fair bandwidth split from *any* starting point
  (Chiu & Jain, 1989) — provably, not empirically.
- Classic loss-based Reno is **RTT-unfair**: a flow with half the round-trip
  time of another gets *more than double* its share of a shared bottleneck,
  because its congestion window grows once per RTT and it simply gets more
  RTTs per second.
- CUBIC (RFC 8312, the Linux default since 2.6.19) was explicitly designed
  to fix that: its window growth is a cubic function of *wall-clock time*
  since the last loss, not of ACKs-per-RTT, so two CUBIC flows with very
  different RTTs converge far more fairly than two Reno flows do.
- A deep drop-tail queue causes **bufferbloat**: a bulk Reno flow will
  happily fill any buffer it's given, so a second, latency-sensitive flow
  sharing that queue suffers multi-second RTTs even though the link itself
  is fast. Active Queue Management (RED) fixes this by dropping packets
  *before* the queue fills, giving loss-based senders a congestion signal
  early.
- BBR (2016, Google) sidesteps loss-based control entirely: it estimates
  the bottleneck bandwidth and minimum RTT directly and paces to the
  bandwidth-delay product, so it can hold a shallow queue instead of
  filling it.

This project builds a real packet-level (not just cwnd-formula) network
simulator — discrete-event, with actual packets, actual queues, actual
propagation + transmission delay, actual ACK clocking — and wires three
real congestion-control algorithms into it, then uses the simulator to
*reproduce* every one of the five phenomena above as an automated,
assertion-checked test, not just a pretty chart.

## Why it's interesting

Nothing in this repo has modeled a **shared, contended physical resource**
under **cooperative-but-selfish** multi-agent dynamics before. Matchbook's
order book is contended but coordinated by a matching algorithm; Concord's
CRDT never contends at all (every write just merges). Undertow's senders
are mutually unaware, unable to communicate, and only ever see an implicit,
noisy signal (loss, or bandwidth/RTT estimates) about the resource they're
fighting over — closer in spirit to Beacon's uncertain-sensor SLAM problem
than to any of the consensus builds, but for a completely different
resource (bandwidth, not agreement).

It's also unusually well-suited to *this* repo's review discipline: the
"is it actually simulating physics or just faking a chart" trap is exactly
what happened with Quantum's thrashing model on 2026-09-12 (a version
without a real finite-capacity bottleneck only ever showed monotonic
decline, never the real collapse curve) — so this build is deliberately
architected around one single shared, real, capacity-bounded bottleneck
queue that every flow's packets must actually pass through in simulated
time, with no shortcut formulas standing in for the send/queue/drain path.

## Architecture

```
src/
  packet.py          Packet dataclass (flow id, seq, size, timestamps)
  network.py          Discrete-event core: EventQueue (heapq), Link
                       (propagation delay + bandwidth → serialization time),
                       Bottleneck (single shared FIFO queue feeding one
                       egress link, drop-tail or RED admission), Endpoint
                       wiring for forward (data) and reverse (ACK) paths
  flow.py              Sender (owns a congestion-control strategy, tracks
                       cwnd/ssthresh/in-flight packets, SRTT/RTTVAR à la
                       Jacobson/Karels, retransmission timeout, dup-ACK
                       fast-retransmit) and Receiver (cumulative ACK
                       generation)
  congestion/
    base.py            CongestionControl interface (on_ack, on_loss,
                       on_timeout, cwnd property)
    reno.py            Slow start + AIMD congestion avoidance + fast
                       retransmit/recovery
    cubic.py           RFC 8312 cubic growth function + TCP-friendly
                       region, real Wmax/K/beta bookkeeping
    bbr.py             BBR-lite: STARTUP/DRAIN/PROBE_BW/PROBE_RTT state
                       machine over a windowed max-bandwidth + min-RTT
                       filter
  metrics.py           Jain's fairness index, throughput/goodput,
                       queueing-delay stats
  experiments.py       Scenario builders (single flow, same-RTT fairness,
                       RTT-unfairness, bufferbloat + RED, BBR vs loss-based)
  cli.py               Run an experiment, export JSON + a text summary
visualizer/
  index.html           Self-contained HTML/Canvas/vanilla-JS: cwnd(t)
                       sawtooth per flow, throughput bars, queue occupancy
                       and RTT-over-time for the bufferbloat scenario,
                       fairness-index-over-time chart
tests/                 pytest: one test file per phenomenon above, plus
                       simulator invariants (packet conservation, cwnd
                       never below 1, queue never negative/over capacity)
demo.sh                Runs the full test suite + every experiment +
                       builds the visualizer bundle + a headless-browser
                       smoke test
```

## Feature list

**Required (4):**

1. **Packet-level discrete-event network core** — real `Packet`s traveling
   over real `Link`s (propagation delay + finite bandwidth ⇒ real
   serialization time) through a single shared `Bottleneck` queue with
   drop-tail admission control. ACKs are cumulative and travel a real
   (uncongested) reverse path, so RTT is a real measured quantity, not a
   parameter.
2. **TCP Reno** wired into the simulator end-to-end: slow start, AIMD
   congestion avoidance, triple-dup-ACK fast retransmit + fast recovery,
   RTO-based timeout retransmission with exponential backoff.
3. **TCP CUBIC** wired into the same simulator: the real RFC 8312 cubic
   growth function (`W(t) = C(t-K)³ + Wmax`) plus the TCP-friendly region,
   with its own loss response (`Wmax = cwnd`, multiplicative decrease by
   β=0.7).
4. **Fairness experiment harness**: run N concurrent flows over one shared
   bottleneck and compute Jain's fairness index over time, reproducing (a)
   AIMD convergence to fairness for two identical-RTT Reno flows and (b)
   Reno's RTT unfairness for two different-RTT flows on the same
   bottleneck — as assertion-checked automated tests, not eyeballed charts.

**Stretch (2, ≥1 required to ship):**

5. **BBR-lite**: a real bandwidth-delay-product congestion controller
   (STARTUP/DRAIN/PROBE_BW/PROBE_RTT) that holds a shallow queue instead of
   filling it, compared head-to-head against Reno/CUBIC on the same
   bottleneck.
6. **Bufferbloat + RED demo and interactive HTML visualizer**: a bulk Reno
   flow sharing a deep drop-tail queue with a latency-sensitive flow (RTT
   balloons), the same scenario replayed with RED active queue management
   (RTT stays bounded), rendered as cwnd/queue/RTT-over-time charts in a
   dependency-free HTML page.

## Ground truth this build is checked against

- Packet conservation: every packet a flow sends is exactly one of
  {delivered, dropped, still in flight} at the end of a run.
- cwnd ≥ 1 MSS at all times for every algorithm (never zero or negative).
- Two identical-RTT Reno flows: Jain's fairness index → ≥0.98 within the
  run.
- Reno, RTT ratio 4:1: throughput ratio between the two flows is
  substantially more skewed than 1:1 (classic RTT unfairness).
- CUBIC, same RTT ratio, same bottleneck: throughput ratio measurably
  closer to 1:1 than Reno's (CUBIC's documented fairness improvement).
- Drop-tail with a deep queue: measured queueing delay under sustained
  load is many multiples of the link's base propagation delay
  (bufferbloat); RED on the identical scenario keeps it bounded.
