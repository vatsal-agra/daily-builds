# Undertow

A reliable, ordered, congestion-controlled byte-stream transport protocol —
a small but real "TCP" (**MiniTCP**) — built entirely from scratch on top of
raw, lossy UDP. Proven by streaming a real file through a real relay that
drops, delays, reorders, and duplicates real datagrams, and getting every
byte back identical, with a live-recorded congestion-window sawtooth to
show it.

## What it is

Every prior networking-adjacent build in this repo's history stayed one
layer above the wire — HTTP servers backing an interactive UI, or a
distributed-systems *simulation* over an in-process clock. Nothing had
touched the transport layer itself: the actual problem TCP/IP solves of
turning an unreliable packet channel into a reliable byte stream. Undertow
does that from first principles:

- **`MiniTCPSocket`** — a 3-way handshake, sliding-window reliable delivery
  with cumulative + selective ACKs, a real Jacobson/Karels RTO estimator,
  fast retransmit on triple duplicate ACK, and a 4-way graceful close, all
  over raw UDP datagrams with a CRC32-checksummed wire format.
- **Reno congestion control** — slow start, congestion avoidance,
  multiplicative-decrease + fast recovery, with every state transition
  recorded so it can be plotted.
- **`NetSim`** — a genuinely unreliable UDP relay: real sockets, real
  `random`-driven drop/duplicate/reorder decisions applied to real
  datagrams in flight, real wall-clock-scheduled delay via a background
  thread. A "lost" packet here is simply never handed to `sendto()` again —
  not a mocked flag the application checks.
- **Two demo apps riding on top** — a SHA-256-verified file transfer, and a
  minimal HTTP/1.0 request/response server, proving `MiniTCPSocket` is a
  general-purpose substrate rather than a one-off hack.
- **A live HTML report** — cwnd/ssthresh sawtooth, packet timeline, and
  throughput charts generated from a real recorded run, not synthesized
  data.

## How to run it

```bash
# A full transfer through a lossy network, with a live report:
python3 bin/undertow-demo --size 100000 --loss 0.1 --dup 0.02 --reorder 0.05 \
    --delay-min 5 --delay-max 20 --report /tmp/undertow_report.html

# Full verification: 46 unit/integration tests + 5 live end-to-end
# scenarios (lossy transfer, congestion-control reaction, the
# zero-spurious-retransmit invariant, graceful close + file transfer,
# HTML visualizer + HTTP demo). Exits non-zero on any failure.
./demo.sh

# Just the test suite:
python3 -m unittest discover -s tests
```

`bin/undertow-demo --help` lists every knob (payload size or a real
`--file`, loss/dup/reorder probabilities, delay range, RNG seed for
reproducible runs, overall timeout, and `--report` to write the HTML
visualizer). All inputs are validated with clear error messages — bad
values (`--loss 1.5`, `--delay-min` greater than `--delay-max`, a missing
`--file`, `--size 0`) fail fast instead of misbehaving silently.

No external dependencies: pure Python 3 stdlib throughout (`socket`,
`threading`, `struct`, `zlib`, `hashlib`, `heapq`, `argparse`). Real UDP
sockets on loopback — no mocked network layer anywhere.

## Full feature list

**Required:**

1. **Reliable, ordered, in-order byte-stream delivery over a genuinely
   lossy UDP network.** Sequence numbers, cumulative ACKs, a real
   Jacobson/Karels RTO estimator (with Karn's algorithm — no RTT sample is
   ever taken from a retransmitted or head-of-line-blocked segment), and
   fast retransmit on a triple duplicate ACK. Verified byte-exact under
   0–25%+ real packet loss, duplication, and reordering.
2. **Reno-style congestion control** — slow start (exponential growth to
   ssthresh), congestion avoidance (linear growth), multiplicative decrease
   + fast recovery on 3 dup-ACKs, full reset to 1 MSS on an RTO timeout.
   Every cwnd/ssthresh transition is recorded and renders as the textbook
   sawtooth under sustained loss (see the HTML report).
3. **Graceful 4-way connection teardown** — a full state machine (`CLOSED →
   SYN_SENT/SYN_RCVD → ESTABLISHED → FIN_WAIT/CLOSE_WAIT → TIME_WAIT →
   CLOSED`) that correctly handles a FIN piggybacked on the final handshake
   ACK, a FIN reordered ahead of it, and concurrent `close()` calls from
   two threads converging on the same teardown instead of sending a second,
   doomed FIN.
4. **End-to-end file transfer application** — a real file, chunked and
   streamed through `MiniTCPSocket`, SHA-256-verified byte-identical on
   arrival, with a printed report (bytes, retransmissions, elapsed time,
   throughput, final cwnd).

**Stretch (all three implemented, not just the required one):**

5. **Selective ACK (SACK)** — the receiver reports which out-of-order byte
   ranges it already holds; the sender uses that to retransmit every
   currently-missing segment in one recovery burst instead of one segment
   per round trip (verified directly: this alone took an 80KB/20%-loss
   transfer from 76 seconds pinned at 1-MSS cwnd to single-digit seconds).
6. **Interactive HTML visualizer** (`viz/generate_report.py`) — a
   self-contained report with a cwnd/ssthresh sawtooth chart, a
   throughput-over-time chart, and a packet-timeline swimlane, all drawn
   from a real recorded run's event log via inline SVG (no chart library).
7. **HTTP/1.0 demo app** (`undertow/httpapp.py`) — a real GET
   request/response exchange over `MiniTCPSocket`, including a real 400
   Bad Request for a malformed request line rather than silently treating
   garbage as `GET /`.

**Also shipped:** source-address validation (a segment from anywhere other
than the established peer is dropped, not accepted, the way a real socket
filters on the connection tuple), and a RST sent when retransmits are
exhausted so the peer learns the connection died instead of hanging until
its own timeout.

## Why I chose this today

Scanning the ledger, this repo has built SAT solvers five times, path
tracers four times, search engines four times, version control systems
three times, and a transformer language model nine separate times — every
classic "algorithm on data I already have" project has multiple entries.
Networking — the actual mechanics of turning an unreliable channel into a
reliable one — had never been touched. It also has unusually strong,
binary ground truth for a from-scratch build: a transfer is either
byte-for-byte and SHA-256-identical or it isn't, and congestion control's
correctness is *visually* falsifiable — you either see the sawtooth under
sustained loss or you don't. Building it forced real concurrency (reader
thread, retransmission-timer thread, and a UDP relay thread all racing for
real), and along the way surfaced real, subtle bugs that only show up under
genuine timing pressure — see `REVIEW.md` for eleven of them, including one
that would have shipped as an intermittent hang (a state-observability race
between `accept()`/`connect()` and a connection that raced through
`ESTABLISHED` into `CLOSE_WAIT` before the waiting thread ever saw it).
That's a different, and in some ways harder, kind of correctness than "does
this algorithm produce the right output for this input" — there's no
canonical answer key, just "does it survive contact with a network that's
actively trying to break it."

## Where a human could take this next

- **RFC 6675-style full SACK-based loss recovery** (a real scoreboard,
  not just "retransmit everything not yet SACKed") — throughput under
  sustained 20%+ loss is currently honest-but-slow (single-digit KB/s),
  matching real classic-Reno-without-full-SACK behavior; a proper
  scoreboard would meaningfully close that gap.
- **Window scaling** — the window field is a 16-bit byte count (matching
  pre-RFC-1323 classic TCP), capping the maximum useful cwnd at 64KB; a
  scale-factor option would remove that ceiling for large transfers.
- **Real network testing** — everything here runs on loopback by design
  (self-contained, no internet dependency); pointing `MiniTCPSocket` at two
  machines across a real LAN/WAN would be the natural next integration
  test.
- **CUBIC or BBR** instead of Reno — Reno was chosen for how well-understood
  and visually verifiable its sawtooth is, but a modern congestion
  controller would be a natural follow-up comparison, plotted on the same
  visualizer.
- **Multiplexing** — one `MiniTCPSocket` currently handles exactly one
  connection per bound port; a real `listen()` backlog accepting multiple
  concurrent clients would make it usable as an actual server framework.
- **NAT/relay traversal beyond loopback** — the `NetSim` relay pattern here
  is a simplified two-party pinhole; extending it to a real STUN-like
  traversal scheme would be a natural bridge to real-world deployment.

## Repo layout

```
undertow/
  segment.py       wire format + CRC32 checksum
  rto.py           Jacobson/Karels RTO estimator
  congestion.py    Reno congestion control
  socket_.py       MiniTCPSocket — the transport itself
  netsim.py        real lossy/reordering/duplicating UDP relay
  eventlog.py      records real protocol events for the visualizer
  fileapp.py       SHA-256-verified file transfer demo app
  httpapp.py       HTTP/1.0 demo app
bin/undertow-demo  CLI: end-to-end transfer through a lossy network
viz/generate_report.py   real-run -> interactive HTML report
tests/             46 unit + integration tests
demo.sh            full verification: tests + 5 live end-to-end scenarios
PLAN.md            architecture + feature list (written before the build)
REVIEW.md          adversarial review: 11 real bugs found, fixed, tested
```
