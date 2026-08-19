# Skein — a from-scratch CRDT for real-time collaborative text editing

## The concept

Google Docs, Figma, and every other "multiple people editing the same
document at once" tool solve a problem that sounds simple and is not:
what happens when two people type at the *same position* at the *same
time*, and their edits arrive at every replica in a *different order*?

The classical answer is operational transformation (OT) — the algorithm
behind early Google Docs — which requires a central server to
sequence operations and a notoriously fiddly transformation function
per operation pair. The modern answer, and the one behind Yjs and
Automerge, is a **Conflict-free Replicated Data Type (CRDT)**: a data
structure engineered so that applying the same set of operations *in
any order, on any replica, any number of times* converges to the exact
same document — no central sequencer, no transformation matrix, no
"master" copy. Mathematically: the merge operation is commutative,
associative, and idempotent, so replicas form a join-semilattice and
convergence is a theorem, not a hope.

This repo has built consensus before (Quorum, 2026-06-15, a Raft
simulator) — but Raft is the *opposite* approach: an elected leader
imposes a single total order via majority vote, and a minority partition
cannot make progress at all. A CRDT has no leader, no voting, no
minimum-quorum requirement — every replica, even one that's been
offline for a week, can keep editing and will still converge the moment
it reconnects. That's a genuinely different distributed-systems idea,
not a variation on Quorum.

## Why this is interesting

- It's the actual algorithm behind software people use every day, not
  a toy simplification — implementing it for real means confronting the
  same hard case that makes it famous: **concurrent insertion at the
  same position must be deterministic** on every replica without any
  replica ever talking to another to agree on who "won."
- It's *provable*, not just "looks right." Strong Eventual Consistency
  (SEC) is a formal guarantee: same operation set ⇒ same final state,
  regardless of delivery order. A build in this domain can — and must
  — put that guarantee under adversarial test: random delivery order,
  random network chaos, and a differential oracle, all asserting
  bit-identical convergence across thousands of trials.
- It naturally produces a good interactive demo: several independent
  "sites" typing concurrently into a shared document while a simulated
  lossy, reordering, partition-prone network carries their edits, and
  the fascinating part is watching every pane converge anyway.

## Architecture

```
skein/
  ids.py        Site IDs, Lamport-clock-style unique character IDs
  rga.py        The RGA (Replicated Growable Array) sequence CRDT itself:
                 - insert_local(pos, char) -> Op
                 - delete_local(pos) -> Op
                 - apply_remote(op)         (out-of-order safe: buffers
                                              ops whose left-parent hasn't
                                              arrived yet, replays them
                                              once it does)
                 - text property (materializes visible, non-tombstoned
                                   chars in causal/tie-broken order)
  network.py     SimNetwork: in-memory message bus between N sites with
                 configurable latency jitter, reordering, duplication,
                 drop rate, and partition/heal — but NEVER silent
                 corruption of a delivered message (that would be a
                 differently-scoped project: byzantine fault tolerance)
  site.py        Site: owns one RGA replica + an outbox to the network;
                 exposes type_at()/delete_at() as the "user" API
  simulate.py    Orchestrates N sites, a script of concurrent local
                 edits, and network delivery; can run with any chaos
                 profile
  convergence.py Property-based verification: run the same op set
                 through many random delivery-order shuffles and many
                 chaos seeds, assert every resulting replica is
                 byte-identical; also a naive sequential-oracle
                 differential check
  undo.py        Per-site local undo/redo stack that stays correct
                 under remote interleaving (stretch)
  cli.py         `skein sim / chaos / convergence-proof / demo / serve`
  web/           Self-contained HTML/CSS/JS multi-pane playground,
                 server-backed (stdlib http.server), zero client-side
                 CRDT logic — the browser only renders what the server
                 computes, same pattern this repo has used before
                 (Gambit, Formulate, Unify)
tests/           unittest suite
demo.sh          end-to-end walkthrough
```

### The core algorithm (RGA — Replicated Growable Array)

Every character ever inserted gets a globally unique ID
`(counter, site_id)`, minted by a per-site Lamport-style counter that
advances past the highest counter it has ever seen (locally or
remotely) — this is what gives concurrent inserts a **deterministic
total order** without coordination: insert after the same left-anchor
ID, and every replica breaks the tie the same way (higher `(counter,
site_id)` wins), because every replica sees the same IDs.

Deletion never physically removes an element — it's marked as a
**tombstone**. This is what makes delete commute correctly with a
concurrent insert at the same spot (you can't lose newly-inserted text
just because someone else deleted the character next to it). Tombstones
are real memory-forever in a minimal RGA; documented as a known
production concern (real systems garbage-collect tombstones behind a
causal-stability watermark) rather than pretended away.

Op application is **causally guarded**: an insert operation names its
left-anchor ID; if that anchor hasn't been applied to this replica yet
(the network delivered things out of causal order), the op is buffered
and retried once its dependency lands — never applied speculatively in
the wrong place.

## Feature list

**Required (core, must fully work end-to-end):**

1. **RGA sequence CRDT engine** — unique-ID-based insert/delete with
   tombstones, deterministic concurrent-insert tie-breaking, causal
   buffering for out-of-order delivery. The data structure everything
   else depends on.
2. **Simulated unreliable network** — per-message latency jitter,
   reordering, duplication, drop, and partition/heal between any subset
   of sites, driving a multi-site message bus.
3. **Multi-site concurrent-edit simulator** — N independent sites each
   performing local edits (including two sites typing at the exact same
   position in the same tick) and broadcasting ops over the simulated
   network to every other site.
4. **Convergence verification harness** — the actual CRDT proof: the
   same operation set replayed through hundreds of random delivery
   orderings and chaos profiles must produce byte-identical documents
   on every replica every time, cross-checked against an independent
   naive sequential-oracle implementation.

**Stretch (2+):**

5. **Interactive HTML collaborative playground** — a server-backed
   multi-pane editor: type into any site's pane, watch ops flow across
   a live network-activity log, inject latency/partition/packet-loss
   from the UI, and watch every pane converge in real time.
6. **CRDT-native per-site undo/redo** — undo must remove *this site's*
   last local operation specifically, correctly, even after arbitrary
   remote operations have interleaved with it in the visible document —
   materially harder than plain undo because the "last thing typed" may
   no longer be at a stable index.
7. **Causal/op-DAG visualizer** — render the actual causal dependency
   graph of a small edit session (who-inserted-after-whom, which nodes
   are concurrent siblings, how the tie-break orders them) so the
   deterministic-ordering rule is visible, not just asserted.

Plan is to ship all 4 required and at least features 5 and 6 of the
stretch list; feature 7 ships if time allows after the required
adversarial-review and verification gates are fully green.
