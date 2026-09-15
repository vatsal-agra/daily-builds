# Causeway

A from-scratch **reliable transport protocol over raw UDP** — real
sequence numbers and cumulative ACKs, Jacobson/Karels adaptive
retransmission timeouts, TCP-Reno-style congestion control (slow start,
congestion avoidance, fast retransmit/fast recovery, timeout collapse),
and receiver-driven flow control genuinely decoupled from congestion
control — all running over an actual lossy, reordering, duplicating,
jittery network, not a mocked channel. See [PLAN.md](PLAN.md) for the full
design and [REVIEW.md](REVIEW.md) for the adversarial review (10 findings
across every phase of the build, 8 real bugs fixed and 2 documented scope
limitations).

## What it is

Every packet-switched network is, underneath, best-effort: packets get
dropped, reordered, duplicated, and delayed unpredictably. TCP's entire
practical value is a thin layer of bookkeeping that turns that chaos into
something an application can treat as a reliable, ordered, flow-controlled
pipe. Causeway builds that layer from scratch: a `Connection` engine
implementing a real 3-way handshake, in-order reassembly with an
out-of-order buffer, RFC 1071 checksums, and a graceful FIN/FIN-ACK/
TIME_WAIT-style close that survives a lost final ACK — the same engine
driving both a fast, seeded, deterministic in-process simulation (for
fuzzing and unit tests) and a real two-process file transfer over real UDP
sockets, through a real userspace "bad network in a box" relay process
that actually drops, delays, duplicates, and reorders live datagrams.

## Why I chose this today

Every prior "from scratch" build in this repo has been a distributed
system, a language runtime, a data structure, or a renderer — always
something that *assumes* a working network underneath it and focuses on
the logic running on top. Causeway is the first build to go one layer
down and implement the transport itself: the part everything else quietly
depends on, and one this repo had never actually built despite building
several things that *use* one (Concord's SSE relay, Vein's P2P gossip,
Matchbook and Beacon's local demos). It's also the first build here where
correctness is inseparable from *performance under adversity* — a
transport that never loses a byte but stalls for a minute on one dropped
packet is exactly as broken as one that corrupts data — so its own testing
had to attack both axes at once, using a real lossy network rather than a
canned scenario.

## How to run it

```bash
# Full verification walkthrough (everything below, narrated):
./demo.sh

# Fast, seeded, in-process simulated transfer (milliseconds of wall time,
# hundreds of seconds of *simulated* network time under real loss/dup/reorder):
python3 -m causeway.cli demo --bytes 200000 --loss 0.1 --dup 0.05 --reorder 0.1

# The same, with an interactive visualizer of what happened:
python3 -m causeway.cli demo --bytes 200000 --loss 0.08 --log-json log.json
python3 -m causeway.cli viz --log-json log.json --out viz.html   # open viz.html in a browser

# Real two-process transfer over real UDP, through a real lossy proxy:
python3 -m causeway.cli recv --bind 127.0.0.1:9091 --out received.bin &
python3 -m causeway.cli proxy --listen 127.0.0.1:9090 --target 127.0.0.1:9091 \
    --loss 0.1 --dup 0.05 --reorder 0.1 --delay-ms 10 --jitter-ms 15 &
python3 -m causeway.cli send myfile.bin --peer 127.0.0.1:9090

# Unit + integration test suite (38 tests):
python3 -m unittest discover -s tests
```

No dependencies beyond the Python 3 standard library for the protocol
itself; the visualizer is self-contained HTML/CSS/vanilla-JS with no
external libraries or build step.

## Full feature list

**Required:**

1. **Reliable, ordered, exactly-once delivery over an unreliable
   channel** — sequence numbers, cumulative ACKs, RFC 1071 checksums,
   retransmission on timeout, duplicate suppression, out-of-order
   buffering with in-order reassembly on delivery. Proven with a real
   byte-exact file transfer through a real lossy/reordering/duplicating
   UDP proxy, verified by SHA-256, plus a 110+ scenario seeded fuzz suite.
2. **Adaptive retransmission timeout** — Jacobson/Karels SRTT/RTTVAR
   estimation (RFC 6298), with a specific fix for a real ambiguity in
   non-SACK cumulative-ACK RTT sampling (see REVIEW.md finding #2).
3. **TCP-Reno-style congestion control** — slow start, congestion
   avoidance, fast retransmit + fast recovery on 3 duplicate ACKs
   (with a NewReno-style partial-ack refinement), and timeout-triggered
   slow-start restart with ssthresh halving. Reproduces the classic
   congestion-window sawtooth, directly verified (not just "it finished").
4. **Flow control independent of congestion control** — a
   receiver-advertised window based on real free buffer space, throttling
   a fast sender even at zero loss and an unbounded cwnd, plus a
   zero-window persist-timer that avoids the classic silent deadlock.

**Stretch:**

5. **Interactive visualizer** (`causeway viz`) — a self-contained
   HTML/canvas dashboard (cwnd/ssthresh sawtooth with event markers,
   RTT/RTO, in-flight-vs-window, cumulative throughput) built from the
   validated dataviz palette, with a hover crosshair+tooltip, light/dark
   theming, and mobile-width responsiveness, rendered from a real captured
   connection event log and headless-Chromium verified.
6. **Robust connection lifecycle + live 3-process capstone** — graceful
   close that survives a lost final ACK (the peer's own un-acked FIN
   simply retransmits like any other segment), plus a real
   `causeway send` / `causeway proxy` / `causeway recv` demo: two
   independent OS processes moving a real file over real UDP sockets
   through a real lossy relay process.

Plus the supporting infrastructure: a from-scratch discrete-event network
simulator (`SimulatedLink`) sharing one virtual clock with a `VirtualClock`/
`RealClock` abstraction so the exact same `Connection` code drives both the
instant, seeded simulation and the real-time socket path; a real userspace
lossy/delaying/duplicating/reordering UDP relay (`causeway proxy`) as an
actual man-in-the-middle process, not a fake channel; and a CLI (`demo`,
`send`, `recv`, `proxy`, `viz`) with clean, non-traceback input validation.

## Testing

`demo.sh` runs the full walkthrough: the 38-test unit/integration suite
(segment codec, RTT estimator, Reno congestion control, flow control,
reassembly, teardown robustness, a 110+ scenario fuzz suite, adversarial
regressions), a 4-scenario CLI demo matrix, a real direct two-process
transfer, the real three-process lossy-proxy capstone, the visualizer +
headless-browser check, and the adversarial regression checks. All 6
sections green.

## Adversarial review

[REVIEW.md](REVIEW.md) documents all 10 findings from adversarial review across
every phase of this build, including two that were genuinely severe:
retransmitted SYN-ACK/FIN segments silently dropping their ACK flag
(a permanent handshake/close deadlock under loss), and a fixed 1-second
TIME_WAIT that could expire before a peer's own retried FIN got another
chance to be acknowledged (found by verification under sustained 40%
loss, not by inspection) — plus RTT-sample contamination, missing input
validation across the CLI, a dead CLI flag, a visualizer label-clipping
bug, and a latent thread-safety issue in the lossy proxy. Every fixed bug
has a regression test; the two remaining findings are deliberate,
documented scope limitations (a receiver buffer cap not enforced against
a non-compliant sender, and one `Connection` per peer) rather than bugs.

## Where a human could take this next

- **Selective ACK (SACK)** — the single biggest real-world upgrade: it
  would eliminate the RTT-sampling ambiguity this project had to work
  around (finding #2) and let the sender recover multiple losses in one
  window without waiting on cumulative ACKs alone, closing much of the
  performance gap seen under heavy loss (Reno without SACK is
  timeout-dominated at high loss rates, exactly as observed).
- **Multiplexed streams over one connection** (mini-QUIC-style) — several
  independent byte-streams sharing one congestion-controlled connection,
  each with its own flow control, without head-of-line blocking between
  streams.
- **Connection migration** — let a `Connection` survive its peer's IP/port
  changing mid-transfer (what QUIC's connection IDs solve), instead of
  today's one-peer-per-`Connection` lock-on.
- **A pluggable congestion control interface** — Reno's sawtooth is one
  point in a large design space; swapping in Cubic or a BBR-style
  model-based controller behind the same `Connection` API would make for
  a great head-to-head comparison, especially visualized side-by-side in
  the existing dashboard.
- **Path MTU discovery** instead of a fixed configured MSS.
