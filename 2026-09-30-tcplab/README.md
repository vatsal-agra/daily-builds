# tcplab — TCP from scratch, over a network you can break on purpose

A zero-dependency **Rust** implementation of TCP — real wire format, the RFC 793 state machine, RFC 6298
timers, reassembly, flow control and four congestion-control algorithms — running over a **deterministic
simulated network** (seeded, virtual time, no threads) whose links can drop, corrupt, duplicate, reorder and
delay packets. Every behaviour (a fast retransmit, an RTO backoff, a sawtooth) is exactly reproducible.

```
cargo run --release -- handshake                          # annotated SYN → data → FIN trace with state changes
cargo run --release -- run --scenario lossy --dump 40     # tcpdump-style packet trace
cargo run --release -- compare --scenario bottleneck --html report.html
./demo.sh                                                 # runs every feature end to end, then the tests
```

## How to run
Needs only a Rust toolchain. `cargo build --release`, then `target/release/tcplab <run|compare|handshake|scenarios>`.
Options (`tcplab --help`): `--scenario clean|lossy|bottleneck|satellite|slowreader|chaos`, `--algo tahoe|reno|newreno|cubic`,
`--bytes 2MB`, `--rate 10mbit`, `--delay 50ms`, `--queue 30`, `--loss 1%`, `--corrupt/--dup/--reorder P`, `--jitter T`,
`--drop 20,21` (drop specific data packets), `--rcv-buf 16KB`, `--reader-rate 1mbit`, `--iss N`, `--seed N`, `--dump`, `--html FILE`.
Exit status: 0 = transfer byte-exact, 1 = failed, 2 = usage error.

## Features shipped
**Required**
1. **Wire codec** — 20-byte header, MSS + window-scale options, ones'-complement checksum over the IPv4 pseudo-header
   (every single-bit flip is detected — exhaustively tested), malformed-option rejection, wrap-safe sequence arithmetic.
2. **Connection state machine** — all 11 states: 3-way handshake, simultaneous open, graceful close, simultaneous close,
   TIME_WAIT (2·MSL, retransmitted-FIN handling, RFC 1337 RST hardening), RST / connection refused, blind-RST resistance,
   SYN retransmission with backoff and timeout.
3. **Reliable in-order stream** — cumulative ACKs, RFC 6298 RTO with Karn sampling and exponential backoff, fast retransmit,
   out-of-order reassembly, duplicate/corrupt/reordered-packet tolerance, 32-bit sequence wraparound, bidirectional data.
4. **Congestion + flow control** — slow start, congestion avoidance, Tahoe / Reno / NewReno (partial-ACK recovery),
   receive window with scaling, receiver- and sender-side silly-window avoidance, zero-window persist probes.

**Stretch (all four shipped)**
5. **CUBIC** (RFC 8312: cubic curve, TCP-friendly region, fast convergence) — wins on the long-fat-pipe preset.
6. **HTML report** — self-contained inline-SVG page: cwnd/ssthresh sawtooth with RTO/fast-retransmit markers, tcptrace-style
   time-sequence graph with drops, RTT/RTO estimator, flight-vs-receiver-window, plus a side-by-side algorithm comparison. Dark mode aware.
7. **Packet trace + fault injection** — tcpdump-style lines with state transitions, scripted drops.
8. **Scenario presets + `compare`** — six presets, one command to race all four algorithms on the same seed.

## Verification
`cargo test` (debug build, so 32-bit overflow traps are live): 33 unit + 42 end-to-end + 6 CLI + 3 fuzz tests.
Highlights: byte-exact delivery under 8 % loss + reorder + duplication + corruption for 4 algorithms × 12 seeds;
NewReno survives 3 losses in one window with no RTO while Reno does not; exponential RTO backoff asserted event by event;
flow control never overruns the receive buffer; a fuzzer throws 36 000 hostile segments at connections in every state.
[REVIEW.md](REVIEW.md) lists the 11 issues the adversarial pass found (including a persist-timer deadlock and a regression
I introduced myself), each with a regression test verified to fail without its fix.

## Why I chose this today
The repo has SAT solvers, VCS, CRDTs, Raft, a DHT, BitTorrent… but never the protocol they all quietly assume. TCP is
a compact masterpiece of adaptive engineering — and a great puzzle: prove it correct, then *watch* it (the sawtooth is beautiful).
Determinism makes a normally flaky domain (timers, loss) fully testable.

## Honest limitations
No SACK, timestamps, Limited Transmit, delayed ACK or Nagle; one connection per simulation; no idle-restart of cwnd.
Consequences: tail losses need an RTO, heavy jitter causes spurious fast retransmits, and CUBIC (no HyStart, no pacing)
overshoots badly on the shallow-buffered `bottleneck` preset — it loses to Reno there, as it would in real life.

## Where a human could take this next
* SACK + RACK-TLP loss detection (the scoreboard is the natural next feature); timestamps/PAWS; DSACK undo.
* BBR (the simulator already exposes bottleneck rate and queue), HyStart++, pacing.
* Many connections through one bottleneck to study fairness (needs port demux + a shared queue).
* Delayed ACKs + Nagle, ECN, path-MTU discovery.
* A real backend: bind the TCB to a TUN device or raw socket and talk to the Linux stack.
* An interactive web player that scrubs the simulation and highlights the segment under the cursor.
