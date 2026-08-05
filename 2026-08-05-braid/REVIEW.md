# Adversarial review

Hostile-reviewer pass over the Phase 2 build. Goal: break it, not admire
it. Every issue below was reproduced with a concrete failing test *before*
being fixed, and re-verified after. This is not a token pass — six real
bugs were found and fixed, two of them serious correctness bugs in the
core CRDT algorithm that every prior automated test had missed.

## Bugs found and fixed

### 1. Delete-after-undo silently dropped on remote replicas (severe)

**How it was found:** a Python↔JS parity fuzzer that included undo/redo
in its random op streams (the plain insert/delete fuzzer alone never
triggered this).

**The bug:** `local_delete` returned an op whose `id` was the *target
node's* id — the same id an earlier `insert` op for that node already
carried. `Site`'s dedup (`applied_ids`) is keyed by that id alone, so once
a node had been deleted once, a *second, independent* delete of the same
node (e.g. delete → undo/restore → delete again) produced an
op that looked byte-identical to "duplicate delivery of the first
delete" and got silently skipped by every remote replica — the second
delete never took effect anywhere but the originating site.

**The fix:** delete/restore ops now carry their own freshly-allocated
`id`, separate from the `target` node they act on (`crdt/rga.py`,
`static/rga.js`). `Site._op_key`'s comment explains why this separation
is load-bearing.

### 2. `Site.receive()` never actually buffered a not-yet-applicable op (severe)

**How it was found:** the live browser UI stalling mid-sync in a real
two-tab Playwright test — every headless test (fuzzer, network
simulation, CLI) had happened to route around this by calling the
lower-level `_try_apply`/`buffer` directly instead of the public
`receive()` API, so the bug was invisible everywhere except the one
caller that actually used `receive()` as documented.

**The bug:** `receive()`'s docstring promised "if its causal dependency
hasn't arrived yet, buffer it and retry" — the code checked
`_try_apply(op)` and, on failure, did *nothing*. An op that arrived before
its origin/target was permanently dropped instead of queued, so any
out-of-order delivery (routine over a real network, or even just several
concurrent `fetch()` calls racing on separate threads) could permanently
stall a replica mid-document.

**The fix:** `receive()` now calls `self.buffer(op)` on failure, matching
its own docstring, in both `crdt/site.py` and `static/rga.js`. Added a
regression test that drives `receive()` through its public API only
(`tests/test_site.py`).

### 3. Non-concurrent inserts could land in the wrong position (severe)

**How it was found:** manually testing "type near existing text on a
fully-synced tab" while chasing down bug #4's symptom — realized it
reproduced with plain ASCII and zero concurrency.

**The bug:** id tie-breaking in `_integrate` compared *raw per-site
counters*. A site that had made more edits already always had numerically
higher ids than a newer/quieter site, regardless of real causal order. So
if site A had typed "hab" and site B (fully synced, watching "hab") clicked
right after "h" and typed "X", B's very first op could still *lose* the
tie-break against A's older "a" — purely because A's counter happened to
be bigger — and X would be pushed past "a" *and* "b" to land at the very
end (`"habX"` instead of the obviously-correct `"hXab"`), despite there
being no concurrency to resolve at all.

**The fix:** the per-site counter is now a **Lamport clock**: every time a
replica observes a remote op (applied or merely buffered), it advances its
own clock to at least that op's counter (`apply_remote_op` /
`applyRemoteOp`). Any id allocated after observing another id is now
guaranteed to compare greater than it, so a causally-later insert always
wins ties against everything it already knew about. Genuine concurrent
inserts (neither side has seen the other) still tie-break by id either
way — that's the correct, expected, and now-narrower interleaving
anomaly documented in PLAN.md and below.

### 4. Astral Unicode characters (most emoji) silently split into two CRDT nodes

**How it was found:** deliberately testing non-ASCII input while
investigating bug #3.

**The bug:** `typeText`/the local-edit diff in `app.js` iterated JS
strings by UTF-16 *code unit*. Most emoji (𝕏, 😀, family/flag emoji, …)
are two UTF-16 units (a surrogate pair) but one character — iterating by
unit split them into two independently-addressable single-"character"
CRDT nodes. Locally this happened to reassemble correctly by luck of
ordering, but the two halves had no relationship to each other beyond
adjacency, so a concurrent edit landing between them (or bug #3, before
its fix) could genuinely tear an emoji in half.

**The fix:** `typeText` now iterates by Unicode code point
(`[...text]`), matching how Python already indexes strings (Python 3
`str` has no surrogate-pair concept). `localInsert`'s one-character
validation was also fixed to count code points, not UTF-16 units. The
local-edit diff in `app.js` was reworked to compute prefix/suffix
boundaries in UTF-16 units (what `textarea.value` actually uses) but
never let a boundary split a surrogate pair, then convert to a code-point
node index before touching the CRDT. Cursor-tracking math for remote ops
was similarly split into a UTF-16-unit-aware path (`utf16IndexOfId`,
`charUnitLength`) separate from the CRDT's own code-point-based node
indexing (`visibleIndexOfId`), since they're genuinely different numbers
once any astral character exists earlier in the document.

### 5. Static file serving: path-traversal check used a bypassable string prefix

**How it was found:** reviewing `server.py` for the kind of mistake a
"startswith" check for path containment classically hides.

**The bug:** `safe_path.startswith(STATIC_DIR)` is true for a sibling
directory whose name merely starts with the same characters (e.g.
`static-evil` starts with `static`). Not exploitable in this repo today
(no such sibling exists), but it's a real, latent path-traversal
weakness, and confirmed to actually let a raw `..`-containing request
through if such a directory ever appeared next to `static/`.

**The fix:** require an exact match or a path genuinely nested under
`STATIC_DIR` (`STATIC_DIR + os.sep` prefix), not just a shared string
prefix. Verified with a raw `http.client` request carrying a literal
`..` (a normal HTTP client like `curl` silently normalizes `..` out of
the URL before sending it, so testing this required bypassing that
normalization) — confirmed 403 before the fix would have been a 200.

### 6. Ugly failure modes: bad CLI args, op payloads, and port conflicts

Found by deliberately feeding the CLI and server nonsense:

- `braid simulate --sites 0` / `--sites 1` crashed with a raw
  `IndexError` traceback from deep inside `random.choice`. Fixed with an
  `argparse` validator (`_int_at_least`) giving a clean
  `error: argument --sites: must be >= 2, got 0` instead — and
  `Simulation.__init__` itself now raises a clear `ValueError` as a
  second line of defense for any other caller.
- `braid serve` on a port already in use raised a raw
  `OSError: [Errno 98]` traceback. Fixed with a friendly message
  suggesting the next port.
- `POST /op` only checked that `type` and `id` were *present* — a
  malformed op (wrong types, missing `value`/`target`, multi-character
  `value`, non-integer counter) would get relayed as-is to every
  connected browser, whose own CRDT engine doesn't re-validate op shape
  before using it (e.g. a missing `value` would silently insert the
  string `"undefined"` into every peer's document). Added `_validate_op`
  covering shape for all three op types, so malformed input is rejected
  at the door with a `400` instead of corrupting every connected
  client's document.

All six were reproduced with a failing test/request first, fixed, then
re-verified — including a full re-run of the 500-seed local fuzzer, the
150-seed network-chaos sweep, the 150-seed Python↔JS parity check, and
the full Playwright multi-tab browser suite (now extended with dedicated
regression cases for #2, #3, and #4) after every fix. All green.

## UX polish found during the pass

- The top bar wrapped awkwardly on narrow/mobile viewports (the identity
  badge split across two lines, crowded by the tagline). Fixed with a
  mobile breakpoint that hides the decorative tagline and lets the
  toolbar wrap cleanly.
- Verified empty-document state, light/dark theming, and the
  fully-synced "join an existing document" state all render cleanly via
  screenshots (see the polish/verification phases for the full pass).

## Known, honest limitations (not bugs — documented, not hidden)

- **RGA does not guarantee intention preservation for genuine
  concurrency.** Two peers inserting at the *exact same position* in the
  *same instant*, with neither having seen the other's edit yet, can get
  their characters interleaved rather than either person's text staying
  contiguous. This is inherent to the RGA family (the same lineage
  YATA/Yjs improves on) and is a Strong-Eventual-Consistency guarantee,
  not an intention-preservation one. Bug #3's fix (Lamport clocks)
  eliminates the *spurious* version of this anomaly (non-concurrent edits
  colliding due to counter magnitude alone) but does not and cannot
  eliminate the case of genuine, simultaneous, mutually-unseen edits —
  no CRDT in the RGA/WOOT family does, without adopting a materially more
  complex algorithm (YATA/Fugue).
- **Grapheme clusters are not segmented.** One CRDT node is one Unicode
  *code point* (fixed to match Python's string model in bug #4's fix),
  not one user-perceived character — a flag emoji, a skin-tone-modified
  emoji, or any other multi-codepoint grapheme cluster is still several
  CRDT nodes under the hood. They won't get torn apart in ways that
  produce invalid text (each codepoint is always a complete, valid
  character), but a concurrent edit could in principle insert content
  in the middle of what looks like one emoji to a user. Full Unicode
  text segmentation (UAX #29) is out of scope for this build.
- **The live web UI's document is single-shared-per-process**, and the
  server holds it only in memory — restarting `braid serve` loses it.
  This is a deliberate scope choice (see PLAN.md); the CLI's
  `simulate`/`sweep`/`scenario` commands are what formally prove the
  CRDT's convergence property, independent of this server.
- **A tab that goes offline and never reconnects loses its queued
  outbox** (its local edits stay visible in that tab, but never reach
  anyone else). This matches how "local-first, sync when you can"
  software behaves without a persistence layer; there's no server-side
  durability for outbound edits ahead of relay, by design (see
  PLAN.md's server architecture note: the server is a dumb, in-memory
  relay, not a database).
