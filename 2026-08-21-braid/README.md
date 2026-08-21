# Braid

A CRDT-based real-time collaborative editing engine, built entirely from
scratch — no `websockets`, no `automerge`/`yjs`, no consensus library.

**Status: Phase 4 (stretch + polish) complete.** All 4 required features
plus both planned stretch features are implemented and demonstrably
working end-to-end. 9 real issues found by attacking the build as a
hostile reviewer are fixed — see [`REVIEW.md`](./REVIEW.md), including
two *self-caught regressions* introduced mid-review by earlier fixes
(caught only by re-running the existing suite, not just testing what was
new) and one *self-correction* of an originally-documented CRDT
limitation that turned out to be false for this implementation's
algorithm — verified experimentally in both directions rather than left
as an assumption. See [`PLAN.md`](./PLAN.md) for the full concept and
architecture.

**Stretch features shipped:**
- **Multi-type nested document CRDT** (`crdt/document.py`) — an OR-Map
  container mixing `RGA` text fields, `PNCounter`, `ORSet`, and a new
  `LWWRegister`, each a genuinely different CRDT strategy (op-based vs.
  state-based) composed behind one `state()`/`merge()` interface. 150/150
  randomized convergence trials across all four field types at once; the
  OR-Set's "add-wins" claim is verified with an actual concurrent
  add-vs-remove race, not just asserted.
- **CRDT-aware undo/redo** (`crdt/undo.py` + JS port in
  `server/static/rga.js`) — undo generates and applies the *inverse* of
  your own most recent local op against the *current* document state
  (never a snapshot revert), so undoing your own edit after a
  concurrent remote edit landed never touches the other peer's work.
  Real `Ctrl/Cmd+Z` / `Ctrl/Cmd+Shift+Z` in the live editor, verified in
  a real browser including the exact "undo composes with concurrent
  remote edit" case.

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
