# Conduit — Plan

## Concept

Every protocol built by this repo's history has stopped at the application
or algorithm layer — languages, databases, renderers, solvers, models. None
of them has gone down into the **transport layer**: the actual mechanism by
which two computers turn an unreliable, unordered, lossy packet network into
something an application can treat as a reliable byte stream.

Conduit is a TCP-like reliable transport protocol, built entirely from
scratch on raw UDP sockets — no `socket.SOCK_STREAM` anywhere in the
implementation. It reimplements, for real, the mechanisms that make TCP
work:

- A three-way handshake and four-way teardown.
- Byte-stream sequence numbers, cumulative ACKs, and out-of-order
  reassembly.
- RTT estimation (Jacobson/Karels) driving an adaptive retransmission
  timeout.
- Reno-style congestion control: slow start, congestion avoidance (AIMD),
  fast retransmit on triple duplicate ACK, fast recovery.
- Receiver-advertised flow-control windows.
- An Internet checksum (RFC 1071) over every segment.

To prove it is real and not just self-consistent, Conduit is placed under
conditions no toy implementation survives: a **network simulator**
("netsim") that sits between every pair of endpoints and actively injects
configurable packet loss, reordering, duplication, and jitpath delay. Every
integration test runs *through* this simulator, not around it.

The protocol then carries real application traffic: a from-scratch
HTTP/1.1 server. And — the sharpest oracle available — a small
TCP↔Conduit bridge lets the box's **real, unmodified `curl` binary** open
an HTTP connection whose bytes actually travel over Conduit, through the
lossy simulator, to the Conduit-backed HTTP server and back. `curl` has
zero knowledge that it isn't talking to a normal TCP stack; if the response
it prints is byte-correct while the simulator is dropping and reordering a
double-digit percentage of packets, the reliability layer is doing its job
for real, not for show.

## Why it's interesting

1. **A genuinely new domain.** Compilers, interpreters, VMs, VCS, search
   engines, physics, ML, crypto, and renderers are all deeply represented
   in this repo. Networking — the layer every one of those *would* need to
   talk to another machine — has never been touched.
2. **Adversarial-by-construction.** The interesting part of TCP isn't the
   happy path, it's what happens when the network misbehaves. Building the
   fault injector is as important as building the protocol; without it,
   "reliable transport" is an unfalsifiable claim.
3. **An oracle no prior build has had:** a real, independent, unmodified
   third-party binary (`curl`) as the client, with no code shared with the
   implementation, exercising the full stack end-to-end.
4. **Directly observable trade-offs.** Congestion-window sawtooth under
   loss, RTT inflation under jitter, throughput collapse under
   reordering — these are the actual graphs that explain *why* the modern
   internet behaves the way it does, and Conduit can produce all of them
   from its own real traffic traces.

## Architecture

```
 Application (HTTP server/client, conduit-cp file transfer)
        │  send()/recv()/connect()/accept()   (socket-like API)
 ┌──────▼───────────────────────────────────────────────┐
 │                  conduit.transport                    │
 │  ConduitSocket: handshake, teardown, sliding-window   │
 │  sender + receiver, retransmission timers, ACK logic  │
 ├────────────────────────────────────────────────────────┤
 │  conduit.congestion   Reno state machine (cwnd/ssthresh)│
 │  conduit.rto          Jacobson/Karels RTT → RTO         │
 │  conduit.segment      wire header pack/unpack, flags    │
 │  conduit.checksum     RFC 1071 Internet checksum        │
 └──────────────────────┬─────────────────────────────────┘
                         │ raw UDP datagrams
                ┌────────▼─────────┐
                │  conduit.netsim   │   loss / delay / jitter /
                │  (the middlebox)  │   reorder / duplication
                └────────┬─────────┘
                         │ raw UDP datagrams
                (peer ConduitSocket, same stack)
```

`conduit.bridge` adds a real TCP listener on one side that relays raw bytes
into/out of a Conduit connection — this is what lets `curl` (a real TCP
client) reach a Conduit-backed server through the lossy simulator.

## Feature list

**Required (4):**

1. **Reliable transport core** — handshake/teardown, byte-stream sequence
   numbers, cumulative ACKs with out-of-order reassembly, checksummed
   segments, adaptive retransmission (Jacobson/Karels RTO), verified to
   deliver byte-perfect data over a lossy/reordering/duplicating simulated
   network.
2. **Reno congestion control + flow control** — slow start, AIMD congestion
   avoidance, fast retransmit on 3 duplicate ACKs, fast recovery, timeout
   handling (ssthresh/cwnd resets), plus receiver-advertised windows
   actually throttling the sender.
3. **Network simulator ("netsim")** — a seeded, configurable middlebox
   (loss %, delay/jitter, reorder %, duplicate %) that every integration
   test runs through; the seed makes loss/reorder/duplicate *rates*
   reproducible, though delivery itself runs on real threads against the
   real clock rather than a scripted discrete-event clock, so it is a
   genuinely unpredictable network, not a byte-exact replay.
4. **From-scratch HTTP/1.1 server + client running entirely over Conduit**
   (not OS TCP), interoperable end-to-end with the box's real `curl`
   binary via a TCP↔Conduit bridge, through the lossy simulator.

**Stretch (2+):**

5. **Trace visualizer** — a self-contained interactive HTML page replaying
   a real captured transfer: cwnd/ssthresh sawtooth, RTT samples, and a
   sequence/ACK timeline (packet-loss and retransmission events marked).
6. **`conduit-cp`** — a reliable file-transfer CLI that moves a real file
   over a simulated lossy link end-to-end, with a live throughput/progress
   report and post-transfer checksum verification.

## Verification strategy

- Unit tests: checksum against RFC 1071's worked example, segment
  (en/de)codes symmetrically, RTO math against hand-computed values,
  congestion-control state transitions against the textbook Reno FSM.
- Integration tests: real client/server ConduitSockets, real OS UDP
  sockets (loopback), routed through netsim at several loss/reorder/dup
  settings, asserting byte-perfect delivery of multi-megabyte payloads and
  observing that retransmissions/fast-retransmits actually fire.
- External oracle: real `curl` process, through the TCP↔Conduit bridge,
  through netsim configured with real loss, hitting the from-scratch
  HTTP server — response bytes diffed against what a stdlib
  `http.client` request to the same handler (over a direct, lossless
  loopback) returns.
