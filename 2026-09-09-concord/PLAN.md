# Concord — a real-time collaborative text editor built on a from-scratch CRDT

## The concept

Every prior build in this repo that touches distributed/replicated state does it
with a *coordinator*: Quorum (2026-06-15) is Raft — a leader, a log, strong
consistency, majority votes before anything is durable. Matchbook (2026-09-04)
and Beacon (2026-09-02) are both single-authority simulations (one exchange, one
robot) with no concurrent writers at all.

Concord is the opposite shape of problem: **N independent editors, no leader,
no voting, sometimes no network at all** — the actual architecture behind Google
Docs, Figma, and every offline-capable note app. Two people type in the same
paragraph at the same instant, on opposite sides of a flaky connection, and both
documents must end up byte-identical with *no* merge conflict UI and *no*
central arbiter deciding whose edit "wins." That's a CRDT (Conflict-free
Replicated Data Type): a data structure whose merge operation is provably
commutative, associative, and idempotent, so any two replicas that have seen
the same set of operations — in *any* order — converge to the same state.
This is "eventual consistency" as a mathematical guarantee, not a hope.

## Why it's interesting

- It's a genuinely new domain for this repo: concurrent multi-writer state
  with no coordinator, as opposed to Raft's single-writer-via-consensus
  (Quorum) or single-owner simulations (Beacon, Matchbook, Impulse).
- The correctness property is unusually crisp and testable: **strong eventual
  consistency** — replicate the same operations in different orders / with
  network partitions in between, and assert every replica's final text is
  character-for-character identical. That's a real property to fuzz, not a
  vibe.
- It forces genuinely hard, well-known distributed-systems problems into a
  small enough box to solve for real in one day: concurrent-insert tie-breaking
  (two people type at the same cursor position at the same instant — whose
  character comes first, and does *everyone* agree?), causal delivery (an
  operation can reference an id that hasn't arrived yet if the network
  reorders messages), and offline/merge (edit with zero connectivity, then
  reconcile against however far the world moved on without you).
- It's a real, usable product shape — a live multiplayer text editor — which
  gives the UI/UX phase (4) something worth actually polishing, not just a
  CLI.

## Architecture

```
 site A (browser tab)              site B (browser tab)
 ┌─────────────────────┐           ┌─────────────────────┐
 │  crdt.js (RGA)       │           │  crdt.js (RGA)       │
 │  local replica of    │           │  local replica of    │
 │  the FULL document   │           │  the FULL document   │
 │  ids: (siteId,ctr)   │           │  ids: (siteId,ctr)   │
 └─────────┬────────────┘           └─────────┬────────────┘
           │ POST /ops (local edits)          │ POST /ops
           │ GET  /events (SSE, remote ops)   │ GET  /events (SSE)
           ▼                                  ▼
        ┌─────────────────────────────────────────┐
        │   server/relay.py  (Python stdlib only)   │
        │   • per-document append-only op LOG       │
        │     (source of truth for *joining* a doc, │
        │      NOT a CRDT authority — it never      │
        │      resolves anything, just orders and   │
        │      rebroadcasts what it received)       │
        │   • hand-rolled SSE broadcast per doc      │
        │   • ephemeral cursor/presence relay        │
        └─────────────────────────────────────────┘
```

The server is deliberately dumb: it never inspects, reorders, or resolves an
operation — it just appends to a log and rebroadcasts to every other
subscriber. All CRDT logic — insertion ordering, tombstoning, causal
buffering, merge — lives in the client, because the whole point of a CRDT is
that replicas don't need a smart middleman to agree. That also means the
*same* client engine has to handle "the server relay disappeared entirely,"
which the offline-mode feature exercises directly against the real relay
implementation (kill the connection, not a mock).

## Feature list (4 required + 2 stretch)

**Required:**

1. **RGA sequence CRDT engine** (`client/crdt.js`) — a Replicated Growable
   Array (Roh et al. 2011): every character gets a globally unique id
   `(lamportCounter, siteId)`; insertion is always "insert after node X,"
   with a deterministic tie-break among concurrent inserts after the same
   node (higher id wins, so every replica that applies the same op set ends
   up with the same left-to-right order regardless of arrival order);
   deletion tombstones rather than removes, so a delete can never race an
   insert into corrupting the list. This is the mathematical core the whole
   feature list stands on.
2. **Live multi-client sync** (`server/relay.py` + `client/net.js`) — a
   from-scratch Server-Sent-Events broadcast hub over Python's stdlib
   `http.server` (no `websockets`/Flask/etc.), so any number of open browser
   tabs on the same document URL see each other's keystrokes appear within a
   fraction of a second, each one running its own independent CRDT replica.
3. **Causal delivery buffering** — an `insert(afterId, ...)` or `delete(id)`
   op that names a node the local replica hasn't received yet (a real
   possibility any time delivery can reorder) gets buffered, not dropped or
   crashed on, and is replayed automatically the instant its dependency
   shows up. Proven, not asserted: a test harness force-delivers a batch of
   ops out of causal order and checks the replica still converges to the
   right text.
4. **Offline editing + merge-on-reconnect** — a client can flip "offline,"
   keep typing against its local replica with zero network calls, and on
   "online" again: (a) flush its own queued ops to the relay, (b) pull every
   op it missed while it was gone, (c) end up at the exact same document
   text as a client that was connected the whole time — no merge dialog, no
   picking a winner.

**Stretch:**

5. **Live multi-cursor presence** — every connected client broadcasts its own
   cursor position as an ephemeral (non-CRDT, non-logged) event; every other
   client renders a labeled, colored caret that tracks correctly even as
   *other* people insert/delete text before it.
6. **CRDT internals inspector** — an in-app toggle that renders the actual
   live RGA structure (every node including tombstones, its author, its
   `afterId` pointer, and which nodes are concurrent siblings) instead of
   just the rendered text, so the "conflict-free" claim is something you can
   watch happen rather than take on faith.

## Verification strategy (bar this repo has consistently held to)

The core CRDT algorithm is written once in JavaScript (it has to run in the
browser — that's the whole point of a client-side replica). To hold it to the
same standard as this repo's past from-scratch-engine-plus-independent-oracle
builds (Kiln differentially tests against Node's real WASM runtime; Graft/
Strata/Palimpsest differentially test against real `git`), Concord's `crdt.js`
is plain CommonJS-compatible so the *exact same file* is `require()`'d
directly by a Node-based property-fuzz harness (`tests/fuzz_convergence.js`) —
no separate reimplementation to drift out of sync with the shipped code.
That harness is the real gate for Phase 2/3/5: simulate N sites, generate
random concurrent edit scripts, replicate operations to every site in
independently-randomized orders (including deliberately-scrambled/causally-
invalid orders that exercise the buffering feature), and assert every site's
final visible text is identical. Thousands of random trials, not a handful of
hand-picked ones.
