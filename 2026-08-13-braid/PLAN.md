# Braid — a from-scratch CRDT collaborative text editor & convergence lab

## Concept

**Braid** is a real-time collaborative plain-text editor where the replication
layer — the actual conflict-free merge algorithm that makes Google-Docs-style
editing possible — is implemented from scratch, not borrowed from a library.
No `Yjs`, no `Automerge`, no `ShareDB`. Just the core data structure
(a **Replicated Growable Array**, RGA) and a simulated, adversarial network
sitting between several independent peers, all running live in one page.

Braid is two things in one:

1. **An editor.** Open the page, type in any of several peer panes, and watch
   your keystrokes appear — correctly interleaved — in every other pane,
   even though each pane is a fully independent CRDT replica with its own
   local operation log.
2. **A convergence lab.** A network-simulation control panel lets you inject
   latency, reordering, packet loss, and full network partitions between
   peers *while they keep editing independently*. When the partition heals,
   you watch divergent edit histories merge back into one document —
   deterministically, without a server, without last-writer-wins silently
   eating anyone's keystrokes.

## Why this is interesting

Collaborative editing is one of the few problems in distributed systems you
can *see* fail. Most CRDT explanations show you the algorithm; almost none
let you actually break the network and watch the algorithm survive. Building
the RGA by hand (unique fractional-ish identifiers, tombstones, causal
delivery buffering, per-character origin tracking) forces confronting the
real hard parts:

- How do you order two inserts made concurrently at the same position by two
  peers who have never talked to each other, such that *every* peer ends up
  agreeing on the same order — without a central sequencer?
- How do you delete a character that hasn't arrived yet, and have it still
  be gone (or never-appear) once it does?
- How do you buffer an operation whose causal dependency (the character it's
  inserted after) hasn't arrived yet, without blocking everything else?
- How do you undo *your own* edit two minutes later, after three other
  people have typed around it, without corrupting anyone else's text?

These are the actual mechanics behind every real collaborative app, and
they're small enough to build and *prove correct* (via randomized testing)
in a single day.

## Architecture

Everything is vanilla JavaScript (ES modules), zero dependencies, zero
build step, zero server requirement for the core simulation (peers are
simulated in-page — no WebSocket server needed, so the whole thing runs by
double-opening `index.html` or serving the folder statically).

```
braid/
  src/
    rga.js        — the CRDT itself: Doc class, Node/tombstone model,
                     unique IDs, local insert/delete, remote-op apply,
                     causal buffering for out-of-order ops
    peer.js        — Peer wraps an rga.Doc: owns a site ID, an outbox,
                     an inbox buffer, undo/redo history
    network.js      — Network: message bus between peers. Configurable
                     latency (ms range), loss %, reorder %, and a
                     partition-group model (peers only exchange traffic
                     with peers in the same partition)
    attribution.js  — per-character author tracking + convergence hashing
  test/
    convergence.test.js — Node-run randomized property-based test harness:
                     hundreds of randomized concurrent-edit scenarios
                     (with partitions, loss, reordering) asserting Strong
                     Eventual Consistency (all peers converge to the same
                     visible text) and no data loss for delivered ops
    rga.test.js    — unit tests for the CRDT primitives themselves
  index.html       — the editor + network control panel + convergence lab UI
  style.css
  app.js           — wires DOM <-> peers <-> network, drives the UI
  demo.sh          — runs the full test suite, prints a pass/fail summary
```

### The CRDT (RGA — Replicated Growable Array)

- Every character ever inserted gets a globally unique ID `(siteId, seq)`.
- An insert op is `{id, char, afterId}` — "insert `char` with id `id`
  immediately after the character with id `afterId`" (or after a virtual
  document-start sentinel).
- Concurrent inserts after the *same* `afterId` are ordered deterministically
  by comparing IDs (siteId as tiebreaker) — every replica computes the same
  total order without coordination.
- Delete never physically removes a node; it flips a `tombstone` flag. This
  is what makes "delete something that hasn't arrived yet" and "concurrent
  delete + edit-near-it" both safe.
- Remote ops whose `afterId` isn't in the local document yet are held in a
  **causal buffer** and re-checked whenever a new op is applied, so
  out-of-order delivery can never corrupt the structure.

## Feature list

**Required (core, must work end-to-end):**
1. **From-scratch RGA CRDT** — unique-ID ordering, tombstone deletes, causal
   buffering for out-of-order remote ops. No existing CRDT library.
2. **Multi-peer live editor UI** — N editable panes (peers), each backed by
   an independent CRDT replica; typing in one converges into all others in
   real time via the simulated network.
3. **Configurable adversarial network simulator** — per-message latency
   range, packet-loss %, and reordering, plus a partition control (split
   peers into isolated groups, edit independently, heal and watch merge).
4. **Randomized convergence test harness** — a Node-run property-based
   test suite that runs hundreds of randomized concurrent-edit + partition
   scenarios and asserts Strong Eventual Consistency (every peer's visible
   text is byte-identical once all messages drain), catching real ordering
   bugs rather than trusting the algorithm by inspection.

**Stretch:**
5. **Character-level attribution** — every character in every pane is
   colored by which peer authored it (a live "who wrote this" heatmap),
   recomputed as merges happen.
6. **Causal undo/redo** — each peer can undo its own past inserts/deletes
   (marking them undone rather than reversing positionally), correctly
   even after other peers have edited around that text, without disturbing
   anyone else's edits.
7. *(if time allows)* Convergence-hash indicator strip that goes red the
   instant any two peers' documents disagree and green the moment they
   reconverge, so divergence during a partition is visible, not just
   inferred.

## Non-goals

No real network sockets, no persistence layer, no rich text/formatting —
plain text only, so the CRDT logic stays the focus rather than getting
buried under editor-framework concerns.
