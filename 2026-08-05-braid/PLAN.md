# Braid — a from-scratch CRDT for real-time collaborative text editing

## Concept

Braid is a real-time collaborative plain-text editor whose consistency
guarantee comes from a **Conflict-free Replicated Data Type (CRDT)** built
entirely from scratch — no OT (operational transform), no central
lock-step sequencer, no CRDT library (no Yjs, no Automerge, no
`json-crdt`). Every peer keeps its own local, mutable, causally-consistent
replica of the document. Edits apply **instantly and locally** (no
round-trip to a server before you see your own keystroke), and when
updates from other peers arrive — in any order, with any delay, after a
network partition, out of order, duplicated — every replica is
mathematically guaranteed to converge to the *same* document without any
peer ever coordinating with another. This is the algorithmic backbone of
real products (Google Docs-style editors, Figma, Yjs-based apps).

## Why this is interesting

The daily-build ledger already has a deterministic **consensus** protocol
(Quorum, Raft) — a family of algorithms whose whole point is to make a
*single, agreed order* out of concurrent operations. A CRDT is the
opposite bet: no agreement, no leader, no voting, no blocking — and it
*still* provably converges. That's a genuinely different distributed-systems
idea (Strong Eventual Consistency vs. linearizability), it hasn't been
built here before, and it has an extremely satisfying live demo: open two
browser tabs, type in both at once, kill the network, keep typing, restore
the network, watch both tabs converge to an identical document without
either one "winning."

The core data structure is the **Replicated Growable Array (RGA)** —
Roh, Jeon, Kim & Lee (2011) — the same lineage of algorithm YATA/Yjs is
built on. It represents the document as a singly-linked sequence of
tombstone-capable nodes, each carrying a globally-unique
`(counter, siteId)` id and a reference to the node it was inserted after
(its "origin"). Concurrent inserts after the same origin are ordered by a
deterministic tie-break on id, so every replica that has seen the same set
of operations — regardless of the order it received them in — computes
the *identical* linear sequence.

## Architecture

```
crdt/rga.py        from-scratch RGA CRDT engine (Python) — the algorithm
crdt/network.py     deterministic seeded adversarial network simulator
                     (latency, reorder, duplication, drop, partition) —
                     same "replay a seed, get byte-identical chaos" idea
                     as Quorum's Raft simulator
crdt/site.py         a Site = local RGA replica + causal-delivery buffer
                     (an insert can't apply until its origin node exists
                     locally — remote ops that arrive "too early" queue
                     until their dependency lands)
static/rga.js         hand-ported JS mirror of rga.py — runs client-side
                     in the browser so every browser tab is a real,
                     independent CRDT replica, not a dumb terminal;
                     parity with the Python engine is verified by a
                     cross-language test (same op stream -> same string,
                     checked over Node)
server.py             stdlib-only http.server; relays ops between browser
                     replicas over Server-Sent Events (SSE) + POST — the
                     server never touches CRDT logic, it's a dumb relay,
                     so the safety guarantee is proven purely by the
                     replicas, exactly like a real P2P deployment would
                     need it to be
cli.py                 headless multi-peer simulation driver + convergence
                     report + scripted offline/reconnect scenario
static/index.html,      the live multi-tab editor: presence, live cursors,
static/app.js,          a network-chaos control panel (drop live traffic,
static/style.css        force offline, watch it heal), CRDT-aware undo/redo
```

## Feature list

1. **[required] From-scratch RGA CRDT engine** — insert/delete, tombstones,
   `(counter, siteId)` unique ids, deterministic concurrent-insert
   tie-break, causal-delivery buffering for out-of-order remote ops,
   `local_insert`/`local_delete`/`apply_remote_op`/`to_string`.
2. **[required] Deterministic adversarial network simulator + convergence
   proof** — seeded network (latency/reorder/dup/drop/partition), a CLI
   `simulate` driver that runs many peers issuing random concurrent edits
   under chaos and asserts every peer's final document is byte-identical
   (Strong Eventual Consistency) across a large sweep of seeds.
3. **[required] Real-time multi-peer collaborative web editor** — open
   several browser tabs, each running its own JS CRDT replica; edits are
   local-first (apply instantly, no waiting on the server) and sync live
   over SSE; concurrent edits from multiple tabs converge correctly.
4. **[required] Headless CLI simulation & scripted scenarios** — run
   convergence sweeps, and a scripted "peer goes offline, edits diverge,
   reconnects, merges" scenario with a human-readable report, no browser
   required.
5. **[stretch] CRDT-aware local undo/redo** — each site keeps its own undo
   stack of *its own* operations; undoing must correctly re-derive a
   compensating edit even if remote edits have landed in between, without
   corrupting the shared document (a known-hard CRDT feature — naive
   "undo the last N characters" breaks the moment another peer has
   inserted text in the same region).
6. **[stretch] Live presence + network-chaos control panel** — see who
   else is connected and where their cursor is in real time, plus UI
   controls to inject latency/loss or force a tab offline and watch it
   resync on reconnect — makes the convergence guarantee something you
   can *watch happen*, not just take on faith.

## Correctness target (stated honestly up front)

CRDTs give **Strong Eventual Consistency**: replicas that have delivered
the same set of operations converge to an identical state, regardless of
delivery order. That is the property this build proves, exhaustively, via
seeded property-based testing.

RGA's id tie-break uses **Lamport clocks**, not raw per-site counters
(see REVIEW.md #3) — every replica advances its own clock to at least the
highest counter it has observed before allocating a new id. That
eliminates *spurious* interleaving: a purely sequential, non-concurrent
insert always lands exactly where the user expects, because its id is
guaranteed to outrank everything it already knew about. What it can't
eliminate — because no CRDT in the RGA/WOOT lineage can, without a
materially more complex algorithm like YATA/Fugue — is interleaving from
**genuine** concurrency: two peers inserting at the exact same cursor
position in the same instant, with *neither* having seen the other's
edit yet, can still get their characters interleaved rather than either
person's text staying contiguous. That narrower, honest limitation is
demonstrated and called out explicitly in REVIEW.md rather than glossed
over.
