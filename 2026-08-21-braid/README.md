# Braid

A CRDT-based real-time collaborative editing engine, built entirely from
scratch — no `websockets`, no `automerge`/`yjs`, no consensus library.

**Status: Phase 3 (adversarial review) complete.** All 4 required
features are implemented and demonstrably working end-to-end; 7 real
issues found by attacking the build as a hostile reviewer are fixed —
see [`REVIEW.md`](./REVIEW.md), including one *self-correction* (an
originally-documented CRDT limitation that turned out to be false for
this implementation's algorithm, verified experimentally in both
directions) and one *self-caught regression* (a fix for issue #3 that
broke the partition demo, caught by re-running the existing test suite
before moving on). See [`PLAN.md`](./PLAN.md) for the full concept and
architecture.

## What's built so far

1. **RGA sequence CRDT** (`crdt/rga.py`) — unique `(lamport_counter, peer_id)`
   node ids, tombstone deletion, causal-order-independent convergence.
   Verified against 300+ randomized concurrent-editing scenarios (all
   converge to byte-identical text regardless of delivery order) and
   differentially cross-checked against a faithful JavaScript port
   (`server/static/rga.js`) across 30 more randomized scenarios — same
   ops, same result, in both languages.
2. **Chaos network simulator** (`network/sim_network.py`) — seeded,
   deterministic latency/reorder/duplication/loss/partition-and-heal.
3. **Convergence verification harness** (`verify/convergence.py`) —
   150/150 Strong Eventual Consistency trials pass under reorder +
   duplication + partition/heal; a lossy-network tier *without* repair
   is shown to genuinely diverge (honestly, on purpose); the same tier
   *with* periodic anti-entropy resync converges 40/40.
4. **Real-time multiplayer editor** (`server/braid_server.py` +
   `server/ws.py` + `server/static/`) — a hand-rolled RFC 6455 WebSocket
   server (raw sockets, no `websockets` library — verified with its own
   frame-codec smoke test covering 7/16/64-bit payload lengths, masked
   client frames, ping/pong) serving a real browser editor with a live
   network-chaos control panel. Verified in real headless Chromium via
   Playwright: two tabs typing converge; two tabs typing *concurrently at
   the same position* converge; partitioning a tab, editing on both sides,
   then healing reconverges both tabs to the same text.

## How to run it

```bash
cd 2026-08-21-braid
python3 -m server.braid_server --port 8765
# open http://127.0.0.1:8765/?room=demo in two+ browser tabs
```

Offline verification (no browser needed):

```bash
python3 -m verify.convergence
```

## Coming next

Phase 3 (adversarial review), Phase 4 (nested multi-type CRDT document +
CRDT-aware undo/redo), Phase 5 (full test suite), Phase 6 (ship).
