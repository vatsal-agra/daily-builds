# Phase 3 — Adversarial Review

Approach: attack the two things Braid actually promises — (1) the CRDT
always converges regardless of delivery order, and (2) the app layer never
silently loses an edit. Found bugs by writing exploit scripts that try to
break exactly those promises, not by reading the code and guessing.

## Bugs found and fixed

### 1. [HIGH] RGA insert only skipped a sibling, not that sibling's whole subtree — replicas could disagree on final text with zero data loss, zero dropped packets, and zero causal-buffer errors

**How it was found:** the 100-seed randomized convergence test (already
part of the Phase 2 harness) failed on 4/100 seeds with `lossRate: 0`,
`isFullyDelivered() === true` on every peer — meaning nothing was lost or
stuck, the replicas just plain disagreed on the final text. That ruled out
network bugs and pointed straight at the merge algorithm.

**Root cause:** `Doc._applyInsert`'s scan for where to splice a new node
walked forward from the anchor, skipping any *immediately next* sibling
with a higher id — but stopped the instant it hit a node whose `origin`
didn't exactly match. If that skipped sibling already had its own child
inserted (from concurrent activity elsewhere), that child sat physically
next in the list and had a *different* origin, so the scan stopped one
node too early and spliced the new node into the middle of someone else's
subtree instead of after it. Which subtree happened to have a child
already, at the moment a given op was applied, depends on delivery order —
so different replicas produced different (both "locally consistent but
globally different") linearizations of the exact same set of operations.

Traced with a hand-built repro (`u`/`z`/`c` inserted concurrently at the
document head by three sites, each given one child): one replica applying
ops in one order landed on `uszxce`, another applying the *same six ops*
in a different order landed on `uceszx`. Confirmed by manually computing
the canonical pre-order-tree-traversal linearization (`uszxce`) — one
replica was simply wrong.

**Fix:** the scan now tracks the set of ids it has already committed to
skipping and treats any subsequent node whose *origin* is in that set as
part of the same already-skipped subtree, so it's skipped too, however
deep the nesting goes. See the comment on `_applyInsert` in `src/rga.js`.

**Regression test:** `test/regression.test.js` pins the exact `u/s/z/x/c/e`
scenario against five different delivery orders, and the 100-seed
randomized suite (`test/convergence.test.js`) now passes consistently
across repeated runs (previously ~4-8% of seeds failed).

### 2. [HIGH] Reusing a peer's display name after removal silently swallows the new peer's edits

**How it was found:** adversarial question — "what happens if I remove a
peer and then add a new one?" The UI's `nextName()` only checked the
*currently active* `peers` map, so a freed name (e.g. "Alice") was handed
straight back out.

**Root cause:** a peer's display name doubles as its CRDT site id, and a
fresh `Peer`'s id-counter always restarts at 0. A recycled name means the
new peer's first insert gets id `{site: "Alice", seq: 0}` — identical to
an id the *old* Alice already used and every other replica already knows
about. `Doc._applyInsert`'s idempotency check (`if (idMap.has(id)) return`)
correctly treats a duplicate id as "already applied" and no-ops it — which
means the new peer's first several keystrokes vanish from every other
pane, with no error, no warning, nothing in the console.

Confirmed with a standalone exploit script: old "Alice" typed "hello", was
replaced by a new "Alice", who typed "X" — a third peer's document stayed
`"hello"`, the "X" never arrived.

**Fix:** extracted name allocation into `src/names.js`'s `NameAllocator`,
which tracks every name ever handed out (not just currently-active ones)
and never reuses one. `app.js` now uses one allocator instance for the
whole session.

**Regression test:** `test/regression.test.js` reproduces the exact
data-loss scenario at the `Peer`/`Doc` level (documenting the underlying
mechanism), then asserts `NameAllocator` can never produce a duplicate
across more allocations than the name pool has entries (forcing it through
the `PeerN` fallback path too).

### 3. [MEDIUM] Astral characters (most emoji) were diffed by UTF-16 code unit, not Unicode code point

**How it was found:** adversarial question — "what happens if two peers
concurrently edit near an emoji?" Most emoji are two UTF-16 code units but
one visual character; `Peer.setText`'s prefix/suffix diff walked the raw
string, so an emoji typed in one edit became two independent CRDT nodes
(one per surrogate half) chained by origin.

**Risk:** in the general case this could let a concurrent insert from
another peer land, per the (now-fixed) RGA ordering rule, in a position
between a character's own two surrogate halves — rendering as a broken/
replacement glyph. It didn't reproduce in exploit testing after fix #1 was
in place (the subtree-skip fix happens to keep a low surrogate glued to
its high-surrogate parent as a "child" in the tree), but relying on that
as an incidental side effect of an unrelated fix is fragile, not a
guarantee, and any future change to the id-chaining scheme could silently
reopen it.

**Fix:** `Peer.setText` now diffs by Unicode code point (`Array.from(text)`
rather than raw string indexing), so an astral character is always exactly
one CRDT node — atomic and untearable by construction, independent of
whatever the RGA ordering rule happens to do.

**Regression test:** `test/regression.test.js` runs a concurrent-edit
scenario next to an emoji and asserts both convergence and the absence of
any lone (unpaired) surrogate in the result.

### 4. [LOW] "Add peer" always joined a hardcoded default group

**How it was found:** adversarial question — "what if I split into groups
B and C, then click Add Peer?" The new peer was hardcoded to join group
"A" regardless of where anyone else actually was — if nobody was in "A",
the newcomer joined completely alone with no indication why messages
weren't going anywhere.

**Fix:** a new peer now joins whichever group an existing peer is
currently in (arbitrary existing peer, since group membership is otherwise
symmetric), so "Add peer" always joins the live conversation by default.

## Things considered and deliberately NOT changed

- **Packet loss can still cause temporary, not permanent, divergence.**
  A single delivery attempt lost to `lossRate` is genuinely gone — nothing
  queues it, unlike a partition. What recovers it is anti-entropy: each
  peer periodically (every 4s live, every resync pass in tests)
  re-announces every op it has ever originated; re-applying a known op is
  a no-op, so this is always safe, and each pass is an independent trial
  against the loss rate. This mirrors how real unreliable-transport CRDT
  sync works (gossip / anti-entropy, not per-message acks). The test
  suite accounts for this correctly: it resyncs until convergence (capped
  at 25 passes) rather than assuming one flush after healing is enough.
- **`resyncOps()` grows unboundedly over a long session** (every op a peer
  has ever made, re-sent on every anti-entropy pass). For a demo/lab of
  this scope that's fine — a real system would replace this with a
  compact state summary (version vector) rather than full history replay.
  Documented as a known scope limitation, not fixed, per PLAN.md's
  non-goals (no persistence layer).
- **Large pastes generate one CRDT op per character**, not a single batch
  op. Functionally correct (just more messages), and keeps the wire
  format uniform. Left as-is; a production system would batch.

## Verification

All 16 tests pass after fixes (`npm test`): 9 RGA unit tests, 4 convergence
scenarios (including the 100-seed randomized sweep), and 3 regression tests
pinning the exact bugs above. Re-ran the 100-seed sweep 5 times in a row
with no failures (previously failed intermittently before fix #1).
Re-verified all three fixes live in a real browser via Playwright: remove
+ re-add no longer reuses a name, the new peer's edits propagate
correctly, and concurrent emoji edits converge without tearing.
