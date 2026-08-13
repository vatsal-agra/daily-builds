# Braid

A from-scratch CRDT (Conflict-free Replicated Data Type) collaborative
text editor and network convergence lab. No `Yjs`, no `Automerge`, no
`ShareDB` — the entire replication algorithm that makes Google-Docs-style
concurrent editing possible is ~250 lines in [`src/rga.js`](./src/rga.js),
written from first principles, plus a simulated, adversarial network
sitting between several independent peers, all running live in one page.

## What it is

Open the page and you get several editable panes side by side — each one
a fully independent CRDT replica with its own local operation log. Type
in any of them and your keystrokes appear, correctly interleaved, in
every other pane. A control panel lets you inject network latency, packet
loss, message reordering, and full network **partitions** — split peers
into isolated groups, edit both sides independently while they can't see
each other, then heal the network and watch the divergent histories merge
back into one document, deterministically, with no central server and no
silently-dropped keystrokes.

It's built as two things at once: an actual usable (if minimal) real-time
editor, and a lab for seeing a well-known hard distributed-systems problem
fail and recover in front of you, instead of just reading about it.

## How to run it

```bash
npm test          # 18 tests: RGA correctness, a 100-scenario randomized
                   # convergence proof, and regressions for every real bug
                   # found during review (see REVIEW.md)

./demo.sh          # npm test PLUS a real-Chromium end-to-end smoke test
                   # driving the actual app: multi-peer convergence,
                   # partition + heal, attribution, undo/redo, peer
                   # add/remove, edge cases — 14 more checks

python3 -m http.server 8000   # then open http://localhost:8000/
```

No build step, no dependencies to install for the app itself (the test
suite uses Node's built-in `node:test`; the browser demo uses Playwright
if it's available, and skips gracefully with a clear message if not).

## Feature list

**Required (all working end-to-end):**
1. **From-scratch RGA CRDT** (`src/rga.js`) — every character gets a
   globally unique `{site, seq}` id; concurrent inserts at the same
   position are ordered deterministically by comparing ids, so every
   replica converges to the same text regardless of delivery order;
   deletes are tombstone votes (never physically remove structure), which
   is what makes undo-of-delete and out-of-order delivery both safe; a
   causal buffer holds any op whose dependency hasn't arrived yet and
   replays it the instant that dependency shows up.
2. **Multi-peer live editor UI** (`app.js` + `index.html`) — add/remove
   peers on the fly, each an independent replica; typing converges in
   real time across all of them.
3. **Adversarial network simulator** (`src/network.js`) — adjustable
   latency range, packet-loss %, message reordering (falls out naturally
   from randomized per-message latency), and a partition control that
   splits peers into isolated groups whose messages queue (not vanish)
   until healed.
4. **Randomized convergence test harness** (`test/convergence.test.js`) —
   100 randomized scenarios (random peer counts, edits, latency, loss,
   mid-run partitions) asserting Strong Eventual Consistency, run via a
   discrete-event virtual clock so all 100 execute in milliseconds, not
   real seconds.

**Stretch (all shipped):**
5. **Character-level attribution** — toggle a view coloring every
   character by which peer originated it, live-updated as merges happen.
6. **Causal undo/redo** — each peer can undo its own past edits, correctly,
   even after other peers have edited around that exact text — implemented
   with per-edit "votes" on tombstones rather than positional undo, so it
   can never disturb anyone else's concurrent edit.
7. **Convergence indicator** — a badge that goes red the instant any two
   peers' documents disagree (with each peer's live content hash shown)
   and green the moment they reconverge, so divergence during a partition
   is visible, not just inferred.

## Why I chose this today

Collaborative editing is one of the few distributed-systems problems you
can actually *watch* fail and recover, rather than just read about. Most
CRDT writeups show the algorithm; almost none let you break the network on
purpose and see the algorithm survive it. Building the RGA by hand —
concurrent-insert ordering, tombstone deletes, causal buffering for
out-of-order delivery, vote-based undo — forces confronting the genuinely
hard parts (how do independent peers who've never talked to each other
agree on one character order with no coordinator?) instead of trusting a
library to have gotten it right. It's also a problem where "looks correct"
and "is correct" diverge sharply — bug #1 below produced replicas that
looked locally consistent and were nonetheless permanently wrong relative
to each other, which is exactly the kind of failure a property-based test
harness exists to catch and eyeballing a demo never would.

## What the adversarial review actually found

Five real bugs across Phase 3 and Phase 5 (full writeup in
[REVIEW.md](./REVIEW.md)) — worth calling out because none of them were
contrived:

- **The RGA merge algorithm itself had a real ordering bug.** The insert
  scan skipped a losing sibling but not that sibling's whole subtree, so
  three replicas applying the exact same six operations in different
  orders landed on different final text, with zero data loss and zero
  errors anywhere — caught only by the 100-seed randomized property test,
  not by any amount of manual testing.
- **Reusing a removed peer's display name silently swallowed their
  edits** (a fresh replica's id-counter restarts at 0, colliding with ids
  the old occupant of that name already used).
- **A new peer joining after the original author of some content had
  left got an empty join-snapshot**, even though the content was plainly
  sitting in every remaining peer's document — the snapshot mechanism
  replayed "what each peer personally typed," not "what each peer
  currently has."
- **`healAll()` silently used two different labels for "healed"** (the
  network module's own internal default vs. the app's own group label),
  so any peer added after a heal was isolated in a partition of one, with
  the UI cheerfully showing it as "group A" alongside everyone else.
- Astral characters (most emoji) were diffed by UTF-16 code unit rather
  than Unicode code point — hardened even though it didn't reproduce a
  visible tear in testing, since relying on an unrelated fix's side effect
  to keep it safe is fragile.

## Where a human could take this next

- **Rich text.** Currently plain text only, on purpose (keeps the CRDT
  logic the focus). A tree-structured CRDT (or a sequence-of-blocks
  design) for headings/bold/lists is the natural next layer.
- **A real network transport.** Swap the in-page simulated `Network` for
  actual WebSockets/WebRTC between real browser tabs or machines — the
  `Peer`/`Doc` API doesn't know or care that the network is simulated.
- **Compaction.** Tombstones and the full-document anti-entropy snapshot
  both grow unboundedly over a session; a real deployment would want
  periodic garbage collection of fully-acknowledged tombstones and a
  compact version-vector-based sync protocol instead of full replay.
- **Presence beyond attribution** — live cursor positions for each peer,
  not just retroactive "who wrote this."
- **Persistence** — currently everything lives in memory; a page reload
  loses the whole session.

## Verification

`npm test`: 18/18 passing (9 RGA unit tests, 4 convergence scenarios
including the 100-seed randomized sweep, 5 regression tests pinning every
bug found in review). `./demo.sh`: 14/14 live-browser checks passing with
zero console errors, stable across repeated runs.
