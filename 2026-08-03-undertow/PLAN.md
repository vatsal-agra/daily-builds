# Undertow — a reliable transport protocol built from scratch, on top of lossy UDP

## Concept

Every prior "networking-shaped" build in this repo has stayed one layer above
the wire: HTTP servers backing an interactive UI (Formulate, Gambit, Sift,
Trove, Glean...), a distributed-systems *simulation* over an in-process
discrete-event clock (Quorum's Raft), but nothing has touched the actual
transport layer — the thing TCP does. Undertow builds a real reliable,
ordered, congestion-controlled byte-stream protocol ("MiniTCP") from raw UDP
datagrams, and proves it by shoving a file through a genuinely lossy,
reordering, jittery simulated network and getting every byte back intact.

This is a new domain for the repo: not "here's an algorithm on data I already
have," but "here's an unreliable channel, build reliability on top of it,"
which is the actual problem TCP/IP solves. It has extremely strong ground
truth (the file either round-trips byte-for-byte and SHA-256-identical or it
doesn't; the congestion window either produces the textbook Reno sawtooth
under sustained loss or it doesn't) and it's testable in a completely
self-contained way — no internet access, no real peers, just real UDP
sockets on loopback with a real relay in between that actually drops, delays,
reorders, and duplicates real datagrams (not a mocked "pretend this was
lost" flag — the packet genuinely never gets forwarded).

## Why it's interesting

- Forces implementing the actual mechanics behind "reliable delivery":
  sequence numbers, cumulative + selective ACKs, retransmission timeout
  estimation (Jacobson/Karels — the real algorithm BSD TCP uses), fast
  retransmit on triple duplicate ACK, and a real connection state machine
  (handshake / established / teardown) — not a toy request-response RPC.
- Congestion control (slow start → congestion avoidance → multiplicative
  decrease → fast recovery) is one of the most-cited "beautiful algorithm"
  stories in CS and this repo has never implemented it. Its correctness is
  visually falsifiable: plot cwnd over time under steady loss and you either
  see the sawtooth or you don't.
- The "network" in the middle is real: independent UDP sockets, real
  `time.monotonic()`-scheduled delayed delivery via a background thread, real
  `random`-driven drop/dup/reorder decisions applied to real datagrams in
  flight between two real ports. Nothing about packet loss is simulated at
  the application layer — it happens at the socket layer, exactly like a
  flaky real network would do it.

## Architecture

```
 sender app                         receiver app
     |                                   |
 MiniTCPSocket (stream API)         MiniTCPSocket (stream API)
     |  segments (SYN/ACK/FIN/PSH,      |
     |   seq/ack/win/SACK, checksum)    |
     v                                   ^
 UDP socket  ---->  NetSim relay  ---->  UDP socket
                 (real UDP relay process:
                  drop%, delay+jitter,
                  reorder%, dup%, all
                  applied to real datagrams
                  via a time-ordered
                  delivery queue on a
                  background thread)
```

- `undertow/segment.py` — wire format: header (seq, ack, flags, window,
  checksum, SACK block) pack/unpack, checksum verification.
- `undertow/rto.py` — Jacobson/Karels SRTT/RTTVAR retransmission-timeout
  estimator.
- `undertow/congestion.py` — Reno congestion control state machine (slow
  start, congestion avoidance, multiplicative decrease, fast recovery).
- `undertow/socket_.py` — `MiniTCPSocket`: 3-way handshake, sliding-window
  sender with retransmit queue + fast retransmit, out-of-order receive
  buffer + SACK, 4-way graceful close, byte-stream `send()`/`recv()` API.
- `undertow/netsim.py` — real UDP relay applying configurable loss/delay
  jitter/reorder/duplication to real datagrams in flight.
- `undertow/eventlog.py` — records real protocol events (segment sent,
  acked, lost, retransmitted, cwnd changes) to JSON for the visualizer.
- `undertow/fileapp.py` — file-transfer app over `MiniTCPSocket` with
  SHA-256 end-to-end integrity verification.
- `undertow/httpapp.py` — minimal HTTP/1.0 request/response exchanged over
  `MiniTCPSocket`, proving it's a general transport, not a file-copy hack.
- `bin/undertow-demo` — CLI: spins up relay + receiver + sender, transfers a
  file through configurable network conditions, verifies integrity, prints a
  stats report (loss injected, retransmissions, final cwnd, throughput).
- `viz/generate_report.py` — turns a recorded event log into a self-contained
  interactive HTML visualizer (packet timeline swimlane + cwnd/ssthresh
  sawtooth chart + throughput chart).

## Feature list

**Required (core, must fully work end-to-end):**

1. **Reliable, ordered, in-order byte-stream delivery over a genuinely lossy
   UDP network** — 3-way handshake, sequence numbers, cumulative ACKs,
   retransmission via a real Jacobson/Karels RTO estimator, fast retransmit
   on triple duplicate ACK. Data survives real packet loss/reorder/duplication
   injected by the netsim relay and arrives byte-identical.
2. **Reno-style congestion control** — slow start (exponential cwnd growth
   to ssthresh), congestion avoidance (linear growth), multiplicative
   decrease + fast recovery on loss detected via dup-ACKs, cwnd reset to 1
   MSS + ssthresh halving on a full retransmit timeout. Live cwnd/ssthresh
   trace recorded every event.
3. **Graceful connection teardown** — 4-way FIN/ACK close with a real
   connection state machine (CLOSED → SYN_SENT/SYN_RCVD → ESTABLISHED →
   FIN_WAIT/CLOSE_WAIT → TIME_WAIT → CLOSED), including handling a FIN lost
   in transit.
4. **End-to-end file transfer application** proving correctness under
   adversarial network conditions — a real file, chunked and streamed
   through `MiniTCPSocket`, through the netsim relay with configurable
   loss/delay/reorder/dup, SHA-256-verified byte-identical on arrival, with
   a printed transfer report (bytes, retransmissions, duration, throughput).

**Stretch:**

5. **Selective ACK (SACK) blocks** — receiver reports which out-of-order
   segments it already holds so the sender doesn't blindly retransmit data
   already received, reducing redundant retransmission under reordering.
6. **Interactive HTML visualizer** generated from a real recorded transfer's
   event log — packet timeline swimlane (sent/acked/lost/retransmitted),
   cwnd/ssthresh sawtooth chart, and a throughput-over-time chart.
7. **Minimal HTTP/1.0 request/response exchange over `MiniTCPSocket`** —
   demonstrates Undertow as a general-purpose reliable substrate, not a
   file-copy-only tool.

## Ground truth / verification strategy

- Byte-for-byte + SHA-256 equality between sent and received file, under
  multiple real loss/reorder/duplication/delay profiles (0%, 5%, 20%, 40%
  loss; reordering enabled; duplication enabled).
- Segment checksum correctness cross-checked with an independent
  re-computation.
- RTO estimator and congestion-control state transitions checked against
  the textbook Jacobson/Karels and Reno formulas with hand-computed
  expected sequences.
- A run with zero loss must complete with zero retransmissions (proves the
  protocol doesn't retransmit spuriously).
- A run with high sustained loss must show cwnd actually collapsing and
  regrowing (the sawtooth), not just "eventually finishes."
