# Concord

> A real-time collaborative text editor built on a from-scratch CRDT (RGA).
> No leader, no locking, no merge-conflict dialog — independent replicas
> that mathematically converge.

## What it is

Concord is a Google-Docs-shaped multiplayer text editor where the hard part
— what happens when two people edit the same spot at the same instant, or
one of them is offline for a while — is solved by a CRDT (Conflict-free
Replicated Data Type) instead of a central authority. Every browser tab
holds a complete, independent replica of the document (an RGA — Replicated
Growable Array — implemented from scratch in `client/crdt.js`, no library).
A deliberately "dumb" relay server (`server/relay.py`, Python stdlib only)
does nothing but log and rebroadcast operations between tabs — it never
inspects, orders, or resolves anything. All of the actual conflict
resolution happens independently, identically, on every replica, which is
the whole point of a CRDT: two replicas that have seen the same set of edits
— in any order, with any network hiccups in between — provably end up with
byte-identical text, with no coordinator required.

## How to run it

```bash
python3 server/relay.py
```
Then open `http://127.0.0.1:8420/?doc=demo` in two (or more) separate
browser tabs/windows and start typing in either one — watch it sync live in
the other. Toggle **Go offline** in one tab, keep typing, then go back
online and watch it merge with whatever happened elsewhere while it was
gone. Click **Show CRDT internals** to see the actual replicated data
structure behind the text, tombstones included.

To see the whole system work without a browser:
```bash
node examples/two_clients_demo.js   # narrated walkthrough, spins up its own relay
```

To verify everything:
```bash
./demo.sh                           # full suite, prints a PASS/FAIL tally (10/10)
```

## Full feature list

**Required:**
1. **RGA sequence CRDT engine** (`client/crdt.js`) — globally unique
   `(lamportCounter, siteId)` ids, deterministic tie-breaking for
   concurrent inserts at the same position (every replica computes the
   identical ordering regardless of arrival order), tombstone-based
   deletes that can never race an insert into corrupting the structure.
2. **Live multi-client sync** — a from-scratch Server-Sent-Events
   broadcast hub over Python's stdlib `http.server`; any number of open
   tabs on the same document see each other's keystrokes appear in real
   time.
3. **Causal delivery buffering** — an operation referencing a not-yet-seen
   dependency (a real possibility any time delivery can reorder) is
   buffered, not dropped or crashed on, and replays automatically the
   instant its dependency arrives. Proven with a fuzz harness that
   force-delivers ops in fully reversed and fully scrambled orders.
4. **Offline editing + merge-on-reconnect** — flip offline, keep editing
   against the local replica with zero network calls, then reconnect:
   queued edits flush, missed edits get pulled in, and the document
   converges with everyone else's — no merge dialog, no picking a winner.

**Stretch (both shipped):**
5. **Live multi-cursor presence** — every connected client broadcasts its
   cursor position as an ephemeral (non-CRDT) event; everyone else renders
   a labeled, colored caret that tracks correctly even as other people
   edit around it.
6. **CRDT internals inspector** — an in-app panel rendering the actual
   live RGA node list (author, id, left-neighbor pointer, tombstone state)
   instead of just the rendered text, so "conflict-free" is something you
   can watch happen.

Plus, found and fixed during the adversarial review and polish passes (see
[REVIEW.md](REVIEW.md) for the full writeup): a critical bug in the core
tie-break algorithm that made two replicas compute genuinely different
orderings for the same edits; a crash on out-of-range positions; a
data-corruption bug where a client's own delete echoing back to itself
drifted its local caret and corrupted subsequent keystrokes; a
non-atomic server batch-validation bug that could partially broadcast a
rejected request; an XSS hole in the internals inspector; an O(n²)
performance bug that made a 5,000-character paste take 2+ seconds (now
~11ms); a duplicate-tab identity-collision risk; a silent-data-loss gap on
reload-while-offline; a stranded-outbox retry gap; and a CSS specificity
bug that rendered the offline banner even while hidden.

## Why I chose this today

Every prior build in this repo that touches replicated/distributed state
does it with a coordinator: Quorum (Raft, a leader and a vote before
anything is durable) or single-authority simulations (Beacon's one robot,
Matchbook's one exchange). Concord is the opposite shape of problem — many
independent writers, no leader, sometimes no network at all — which is a
genuinely different, well-known-hard set of distributed-systems problems
(concurrent-insert tie-breaking, causal delivery, offline/merge) squeezed
into something small enough to build, verify, and use in one day. It also
has an unusually crisp, testable correctness property (strong eventual
consistency: replay the same ops in different orders, assert every replica
ends up identical), and it's a real product shape — a working multiplayer
editor — that gave the polish phase something worth actually designing, not
just a CLI.

## Known limits (disclosed honestly, not hidden)

- **No persistence.** The relay's op log lives in memory only; restarting
  it discards history for any new joiner (existing open tabs keep their own
  in-memory state and keep working). A page reload while genuinely offline
  loses any *queued-but-unsent* edits — the `beforeunload` guard warns
  before that specific case, but full offline persistence across
  reloads/tab-closes (a localStorage-backed replica snapshot) wasn't built.
- **Tombstones accumulate forever.** A heavily-edited document keeps every
  deleted character's node around — the standard, understood RGA trade-off;
  a real system would eventually need a causal-stability GC pass.
- **UTF-16 code units, not grapheme clusters.** An emoji outside the BMP
  becomes two RGA nodes (one per surrogate half). Convergence is unaffected
  (proven by the fuzz suite, which includes emoji) — this is also exactly
  how a plain `<textarea>` already behaves.
- **No authentication.** Anyone who can reach the relay can join any
  document by URL and post arbitrary (structurally-valid) ops under any
  claimed identity — appropriate for a same-day demo, not for anything real.

## Where a human could take this next

- **Persistence**: back the relay's op log with SQLite/a file instead of an
  in-memory list, so history survives a restart.
- **Rich text**: the CRDT only knows about characters; extending it to
  bold/italic/headings would mean adding a second, position-independent
  attribute layer (Peritext-style) rather than encoding formatting as
  characters.
- **A proper undo/redo** that's CRDT-aware (tombstone-based, so undoing a
  remote-affected region doesn't fight the CRDT's own convergence).
- **Document access control** and per-document auth, now that the core
  sync engine works.
- **A real WebSocket instead of SSE+POST**, mostly to halve the number of
  connections per client — SSE was a deliberate choice to reuse this repo's
  existing hand-rolled-SSE pattern (Impulse) rather than implement the
  WebSocket handshake from scratch, and it works fine at this scale.
