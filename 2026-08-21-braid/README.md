# Braid

A CRDT-based real-time collaborative editing engine, built entirely from
scratch — no `websockets`, no `automerge`/`yjs`, no consensus library,
no third-party dependency of any kind.

There is no leader, no quorum, no consensus round. Every peer accepts
every edit it receives, immediately and locally, and the mathematical
structure of the data type — not a vote — guarantees that once two
peers have seen the same set of edits, they hold bit-identical state, no
matter what order those edits arrived in, how many times a message was
duplicated, or how long two peers were partitioned from each other. This
is **Strong Eventual Consistency**, and this build proves it rather than
asserting it: 150/150 randomized chaos scenarios converge in the offline
verifier, cross-checked against a second, independent JavaScript
implementation, and demonstrated live in a real multiplayer editor over
a hand-rolled WebSocket server.

## How to run it

```bash
cd 2026-08-21-braid

# the full test suite + offline verification report + a live server
# smoke test + the document-CRDT demo, all in one script:
./demo.sh

# or just the live multiplayer editor:
python3 -m server.braid_server --port 8765
# then open http://127.0.0.1:8765/?room=demo in two or more browser tabs
```

No `pip install` needed anywhere — every module is pure Python 3
stdlib, and the browser client is vanilla HTML/CSS/JS with zero build
step. `python3 -m unittest discover -s tests -t .` runs the 56-test
suite on its own; `python3 -m verify.convergence` runs just the
randomized SEC report; `python3 demo_document.py` runs just the nested
multi-type document demo.

## Feature list

**Required (all four fully implemented, verified against real running
code, not mocked):**

1. **RGA sequence CRDT** (`crdt/rga.py`) — unique `(lamport_counter,
   peer_id)` node ids, tombstone deletion (now a proper LWW-register per
   node, not a one-way flag — see undo below), causal-order-independent
   convergence via subtree-skip tie-breaking. Verified across 200+
   randomized concurrent-editing trials in `tests/test_rga.py` and
   differentially cross-checked, op-for-op, against a faithful
   JavaScript port (`server/static/rga.js`) via `tests/test_js_parity.py`.
2. **Chaos network simulator** (`network/sim_network.py`) — seeded,
   deterministic latency/reorder/duplication/loss/partition-and-heal
   over a discrete-tick event queue; the *same class* is used by the
   offline verifier and the live multiplayer server's real chaos-control
   panel, not two different implementations pretending to be one.
3. **Convergence verification harness** (`verify/convergence.py`) —
   150/150 SEC trials under reorder + duplication + partition/heal;
   a lossy-network tier *without* anti-entropy is shown to genuinely
   diverge (honestly, on purpose, not hidden); the same tier *with*
   periodic anti-entropy resync converges 40/40.
4. **Real-time multiplayer editor** (`server/braid_server.py` +
   `server/ws.py` + `server/static/`) — a hand-rolled RFC 6455
   WebSocket server (raw sockets, no `websockets` library — its own
   frame codec is unit-tested against masked/unmasked frames, 7/16/64-bit
   payload lengths, ping/pong, and fragmentation rejection) serving a
   real browser editor with a live network-chaos control panel. Verified
   in real headless Chromium via Playwright: concurrent typing converges;
   partitioning a tab, editing on both sides, then healing reconverges
   both tabs; a client backed up under heavy simulated loss recovers via
   live anti-entropy with **no reconnect**.

**Stretch (both shipped):**

5. **Multi-type nested document CRDT** (`crdt/document.py`,
   `crdt/counter.py`, `crdt/orset.py`) — an OR-Map container mixing four
   genuinely different CRDT strategies behind one `state()`/`merge()`
   interface: `RGA` text (op-based), `PNCounter` (state-based),
   `ORSet` (state-based, verified "add-wins" against an actual
   concurrent add-vs-remove race, not just asserted), and a new
   `LWWRegister` (op-based). `demo_document.py` runs the exact "shared
   outline" scenario this was scoped around: a title, a view counter, a
   tag set, and a body of text, edited concurrently by three offline
   peers and gossip-converged over the real chaos network.
6. **CRDT-aware undo/redo** (`crdt/undo.py` + a JS port in
   `server/static/rga.js`, differentially verified against each other)
   — undo generates and applies the *inverse* of your own most recent
   local op against the *current* document state, never a snapshot
   revert, so undoing your own edit after a concurrent remote edit
   landed never touches the other peer's work. Wired to real
   `Ctrl/Cmd+Z` / `Ctrl/Cmd+Shift+Z` in the live editor, verified in a
   real browser through the exact "undo composes with a concurrent
   remote edit" case, not just single-user undo.

## Why this, today

Every prior "distributed systems" build in this repo (Quorum, the Raft
simulator) was about *agreement* — a cluster converging on one
leader-arbitrated, totally-ordered log. CRDTs are the other branch:
*agreement-free convergence*, correct by algebra rather than by vote.
No build in this ledger's ~50-project history had touched a replicated
data structure before, despite the repo covering everything from SAT
solvers to nine separate from-scratch transformers. It's also a domain
where the "boring correct" implementation and the "cool live demo" are
the same artifact — a real-time multiplayer text editor *is* the
natural way to see and feel a CRDT working, unlike a Raft log or a SAT
solver's clause database.

## Adversarial review, honestly

`REVIEW.md` documents **10 real issues** found by attacking this build
as a hostile reviewer across every phase, not just Phase 3 — including
two issues where testing the literal claim in this document (not just
"does the new code look right") caught that an earlier fix in this same
document was itself incomplete or wrong:

- A CRDT-literature limitation ("the interleaving anomaly") that turned
  out to be **false** for this specific, correctly-implemented algorithm
  — verified experimentally in both directions rather than left as a
  textbook assumption.
- A fix for "the room lock blocks sends" that was real but incomplete
  — the real fix needed a per-connection outbound queue and writer
  thread, found by writing the test the first fix's own commit message
  promised, not by trusting it looked plausible.
- A fix for "loss needs anti-entropy" that, in its first version,
  silently defeated the live partition demo by ignoring active
  partitions entirely — caught by re-running the *existing* partition
  regression test immediately after, standard practice applied
  consistently rather than only for the newest change.

## Where a human could take this next

- A move/rename-aware sequence CRDT (e.g. a proper tree-move CRDT) would
  close the one documented, real gap in RGA — several independent peers
  each anchoring inside an already-formed run can still fragment it.
- The live anti-entropy pass currently resends a room's *entire*
  `op_log` every ~4s because the server holds no per-client "what have
  you definitely applied" state to diff against — a lightweight
  acknowledgment protocol would turn that into a true incremental diff,
  mattering once a document gets large.
- `crdt/document.py`'s nested-field model doesn't support nested
  *documents* (a field containing another whole `Document`) — real
  Automerge-style systems allow arbitrary nesting; this build stops at
  one flat level of named fields, which was enough for the "shared
  outline" scenario it was scoped around.
- The hand-rolled WebSocket layer doesn't support message fragmentation
  (documented, and never hit by Braid's own always-small JSON messages)
  — a general-purpose WS server would need it.
- A persistent storage layer: everything here is in-memory per room,
  for the life of the server process — real durability (even just an
  op-log append to disk) is the natural next step toward this being
  more than a demo.
