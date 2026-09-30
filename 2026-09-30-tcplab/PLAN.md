# PLAN — tcplab

## Concept
**tcplab** is a from-scratch implementation of TCP in Rust (zero dependencies): the real wire format
(20-byte header, options, Internet checksum with IPv4 pseudo-header), the RFC 793 eleven-state
connection machine, RFC 6298 retransmission timers, receive-side reassembly, sliding-window flow
control with zero-window probing, and pluggable congestion control (Tahoe, Reno, NewReno, CUBIC).
It runs over a **deterministic, seeded network simulator** whose bottleneck link can drop, corrupt,
duplicate, reorder and delay packets, so every behaviour (a fast retransmit, an RTO backoff, a
sawtooth) is exactly reproducible from a seed. It emits tcpdump-style packet traces and a
self-contained HTML report with cwnd/ssthresh, time-sequence (tcptrace-style) and RTT/RTO charts.

## Why it's interesting
The repo already has SAT solvers, VCS, CRDTs, DHTs, P2P (Swarm), Raft… but never the protocol
everything else rides on. TCP is a famously subtle piece of engineering: 32-bit sequence wraparound,
Karn's algorithm, fast-recovery inflation/deflation, silly-window avoidance, simultaneous open,
TIME_WAIT. Getting all of it right *and provably so* (byte-exact transfer under 10% loss + reorder +
duplication + corruption) is a satisfying correctness puzzle, and the congestion-control sawtooth is
beautiful to watch.

## Architecture
```
src/
  rng.rs      splitmix64 PRNG (seeded, deterministic)
  segment.rs  TCP segment codec: header, options (MSS, WScale), checksum, seq-number arithmetic
  link.rs     unidirectional link model: rate, delay, jitter, drop-tail queue, loss, corruption,
              duplication, reordering, scripted drops
  cc.rs       congestion control: Tahoe / Reno / NewReno / CUBIC
  tcp.rs      the TCB: state machine, send/recv buffers, RTO, dupacks, flow control, persist probes
  sim.rs      discrete-event simulator wiring two TCBs through two links + app-level driver
  report.rs   text tables + standalone HTML/SVG report generator
  units.rs    parsing of "10mbit", "50ms", "2%", "1MB"
  main.rs     CLI: run | compare | handshake | scenarios
tests/        integration tests (end-to-end transfers under every fault model)
```
Simulation loop: pick the earliest of {link delivery, TCB timer (RTO / TIME_WAIT / app read tick)},
advance virtual time, dispatch. No wall clock, no threads → fully deterministic.

## Features
| # | Feature | Tier |
|---|---------|------|
| 1 | **Wire codec** — real TCP header + MSS/WScale options, ones'-complement checksum w/ pseudo-header, malformed-input rejection, wrap-safe sequence arithmetic | **required** |
| 2 | **Connection state machine** — 3-way handshake, simultaneous open, graceful 4-way close, simultaneous close, TIME_WAIT, RST / connection-refused, SYN retry & timeout | **required** |
| 3 | **Reliable in-order byte stream** — cumulative ACKs, RFC 6298 RTO (Karn, backoff), fast retransmit, out-of-order reassembly, dup/corrupt/reorder tolerance, seq wraparound | **required** |
| 4 | **Congestion + flow control** — slow start, congestion avoidance, Tahoe/Reno/NewReno, receiver window with scaling, SWS avoidance, zero-window persist probes | **required** |
| 5 | **CUBIC** congestion control (RFC 8312: cubic growth curve, TCP-friendly region, fast convergence) | stretch |
| 6 | **HTML report** — cwnd/ssthresh sawtooth, tcptrace-style time-sequence graph, RTT/RTO chart, algorithm comparison | stretch |
| 7 | **tcpdump-style packet trace** + scripted fault injection (`--drop 20,21`) | stretch |
| 8 | Scenario presets (lossy, bottleneck, satellite, slow reader) + `compare` command | stretch |

Required = 1-4. Stretch = 5-8 (goal: ship at least 5 and 6, likely all).
