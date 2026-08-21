# Braid — a CRDT-based real-time collaborative editing engine, from scratch

## Concept

Every prior "distributed systems" build in this ledger has been about
**agreement**: Quorum's Raft simulator makes a cluster of nodes agree on a
single, totally-ordered log, with an explicit leader and a linearizability
checker. Braid is the other branch of distributed data: **agreement-free
convergence**. There is no leader, no quorum, no consensus round. Every
peer accepts every edit it receives, immediately and locally, and the
mathematical structure of the data type — not a vote — guarantees that
once two peers have seen the same set of edits, they hold bit-identical
state, no matter what order those edits arrived in, how many times a
message was duplicated, or how long two peers were partitioned from each
other. This is the algebra behind real production systems: Google Docs
(early versions used OT; modern Docs/Notion/Linear-style multiplayer and
Automerge/Yjs use CRDTs), Redis' CRDT-based Active-Active, and Riak's
distributed counters/sets.

CRDTs (Conflict-free Replicated Data Types) also have not been touched by
any of the ~50 prior builds in this repo (SAT solvers, transformers,
search engines, path tracers, VCS, chess, physics — never a replicated
data structure whose correctness proof is "form a join-semilattice").
It's a genuinely new domain, with an unusually strong, checkable
correctness property (Strong Eventual Consistency) that lets Phase 3/5
verification be a real proof-by-testing exercise rather than "looks right
in the demo," the same spirit as Quorum's safety-invariant monitor.

## Why this is interesting

- **No leader, no consensus, no voting** — yet still provably correct.
  The interesting part isn't the network code, it's proving that
  `merge(merge(A, B), C) == merge(A, merge(B, C))` for a real, editable
  text document — order and grouping of concurrent edits genuinely
  cannot matter, or the data type is broken.
- Text CRDTs have a famous, subtle failure mode (the "interleaving
  anomaly": concurrent insertions at the same position can converge to a
  mathematically valid but human-nonsensical *interleaved* result).
  Building RGA honestly means actually checking where it does and
  doesn't apply, rather than reciting the textbook caveat — see
  REVIEW.md #1: with correct subtree-skip integration, two peers each
  typing their own contiguous run converge as clean, unsplit blocks
  (verified, not assumed); a narrower real case (several independent
  peers each anchoring inside an existing run) still fragments it, also
  verified rather than hand-waved.
- It's a rare domain where the "boring correct" implementation and the
  "cool live demo" are the same artifact: a real-time multiplayer text
  editor *is* the natural way to see and feel the algorithm working, in a
  way Raft's log or a SAT solver's clause database never gets to be.

## Architecture

```
2026-08-21-braid/
  crdt/
    clock.py        vector clocks + causal-ready delivery predicate
    rga.py           RGA sequence CRDT (the text engine)
    counter.py       PN-Counter (state-based CRDT, simplest possible case)
    orset.py         OR-Set (add-wins observed-remove set)
    document.py      nested CRDT document: OR-Map of {text | register | counter | list}
    undo.py          CRDT-aware local undo/redo (inverse-op based, not snapshot revert)
  network/
    sim_network.py   seeded chaos network: latency jitter, reorder, duplicate,
                      drop, partition/heal, N peers, causal-delivery buffering
  verify/
    convergence.py   randomized property-based SEC test harness + CLI report
  server/
    ws.py            hand-rolled RFC 6455 WebSocket server from raw sockets
                      (HTTP upgrade handshake, frame encode/decode, masking,
                      fragmentation-safe, ping/pong) — no `websockets` lib
    braid_server.py  collaborative-doc server: one Braid document per room,
                      broadcasts ops over the hand-rolled WS layer, live
                      network-chaos knobs exposed to the client
    static/          the actual multiplayer editor UI (vanilla HTML/CSS/JS,
                      zero build step, zero frameworks)
  tests/             unit tests per module + full end-to-end demo script
  PLAN.md / REVIEW.md / README.md
```

Every peer runs the identical `rga.py`/`document.py` logic — client-side
JS re-implements the CRDT merge rules too (not just a dumb terminal),
because a real collaborative editor must apply *local* edits optimistically
before the round trip; this mirrors how Kiln's WASM interpreter and Ember's
JIT both had to keep two independently-checked implementations of "the
same" semantics in sync (there: interpreter vs JIT; here: Python peer vs
JS peer), and `verify/convergence.py`'s differential tests catch drift
between the two the same way Ember's gcc/objdump oracles did.

## Feature list

**Required (core, must work end-to-end):**

1. **RGA sequence CRDT** — the actual replicated text data structure:
   unique `(peer_id, seq)` identifiers per character, tombstone-based
   deletion, causal (parent-pointer) ordering that makes concurrent
   inserts at the same position resolve deterministically the same way on
   every peer, local `insert(pos, ch)` / `delete(pos)` API that a plain
   text editor can drive without knowing CRDT internals exist.
2. **Chaos network simulator** — N simulated peers exchanging ops over a
   seeded, adversarial channel: random per-link latency, message
   reordering, duplication, loss, and network partition/heal, with a
   causal-delivery buffer (peers hold a message until its causal
   dependencies have arrived, never applying an insert whose "insert
   after" target hasn't arrived yet).
3. **Convergence verification harness** — randomized property-based
   testing across many seeded scenarios (concurrent edits, partition +
   heal, fully permuted delivery order, duplicated/dropped messages) that
   *proves* Strong Eventual Consistency: every peer that has seen the same
   set of operations holds byte-identical document state, regardless of
   arrival order — analogous in spirit and rigor to Quorum's Raft safety
   monitor, but for a leaderless system.
4. **Real-time multiplayer text editor** — a hand-rolled WebSocket server
   (raw RFC 6455 handshake + frame codec over `socket`, no `websockets`
   library) serving a real browser UI: open the same document in two-plus
   tabs, type concurrently in each, watch them converge live, with a
   visible network-chaos control panel (inject latency/loss/partition
   in the running demo, not just in offline tests) and live peer cursors.

**Stretch (2+, implement what fits after required is solid):**

5. **Multi-type nested document CRDT** ("mini Automerge") — an OR-Map
   container holding a mix of nested CRDT values (RGA text fields,
   LWW-registers, PN-Counters, nested OR-Sets/maps), so the editor isn't
   just one text blob but a structured collaborative document (e.g. a
   shared outline: title register + counter + per-item text blocks).
6. **CRDT-aware undo/redo** — local undo implemented as generating and
   applying the semantic *inverse* of your own most recent op against the
   *current* document state, not a naive snapshot-stack revert — so
   undoing your own edit after a concurrent remote edit landed doesn't
   silently discard or corrupt the other peer's work.
7. *(bonus, time-permitting)* Causal-history / vector-clock DAG visualizer
   showing the actual operation graph a document converged from.

## Correctness bar

- Every stretch/required feature is demonstrated against the real running
  code — no mocked network, no fabricated "it converged" claims. The
  network simulator is a real seeded chaos engine; the WebSocket server is
  real RFC 6455 bytes on a real TCP socket; the verification harness
  asserts against actual object equality of real document states after
  actual randomized delivery, not printed-and-eyeballed output.
