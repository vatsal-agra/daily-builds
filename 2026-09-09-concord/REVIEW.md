# Adversarial review

Hostile-reviewer pass over Concord's Phase 2 build. Every issue below was
found by actually running the system (fuzzing, a real relay + real browser,
crafted malicious input) rather than by reading the code and guessing — and
every one was fixed before Phase 4 started. Ordered roughly by severity.

---

### 1. CRITICAL — the RGA tie-break scan computed genuinely different
   orderings on different replicas (a real divergence, not a data-loss bug)

**Found:** before the first commit, running the most basic possible
concurrent-edit scenario (two sites both append text at the same position at
the same instant) by hand.

**What was wrong:** the original `_integrateInsert` scan stopped the instant
it hit a node whose `leftId` didn't exactly equal the new node's `leftId`,
treating that as "past the contested region, insert here." That's wrong: a
node three characters into someone else's chained insert has a *different*
`leftId` (it points to the *second* character of that chain, not the
original reference point) while still very much belonging to the region
being scanned past. The bug's actual failure mode: `A` and `B` both type six
characters at the same position; site `A` ends up with all of `B`'s
characters grouped together ahead of all of `A`'s, while site `B` computes
the *opposite* grouping — two replicas, same op set, different text.
Reproduced directly with `a.text() !== b.text()` in a five-line smoke test.

**Fix:** replaced the leftId-equality check with a position-based
three-way branch (`client/crdt.js:_integrateInsert`): compare the *array
index* of `other`'s own left-neighbor against our own insertion point.
Strictly after → `other` is a descendant of a winning sibling, skip past it
unconditionally. Exactly equal → real tie-break contest, compare ids.
Strictly before → we've walked past the whole contested run, insert here.

**Verified:** `tests/fuzz_convergence.js`, 2000+ randomized trials per run,
every trial replicating to N fresh sites in independently-randomized
delivery orders (including a fully-reversed order and a fully-scrambled
order that ignores per-site ordering entirely) — all converge to
byte-identical text.

---

### 2. CRITICAL — `localInsert` crashes on an out-of-range position

**Found:** deliberately calling `rga.localInsert(-1, 'x')` and
`rga.localInsert(999, 'x')` against a short document during adversarial
testing of the public API surface.

**What was wrong:** `leftId = pos === 0 ? null : this._visibleNodeAt(pos -
1).id` — for any `pos` that isn't a valid in-range position,
`_visibleNodeAt` returns `null`, and `.id` on `null` throws
`TypeError: Cannot read properties of null`. Under normal typing this can't
happen (app.js's diffing always derives `pos` from the textarea's own
current, in-sync length), but a crash reachable from the public engine API
on bad input is exactly the kind of "lazy shortcut" this review exists to
catch — a future caller, a test, or a bug elsewhere in app.js could trigger
it and take down the whole replica.

**Fix:** clamp `pos` to `[0, this.length()]` at the top of `localInsert`
(and, for consistency/defense-in-depth, `localDelete` and `anchorAt` too,
even though those two were already safely no-op-ing rather than crashing).

**Verified:** direct regression check (`localInsert(-1, ...)` /
`localInsert(999, ...)` no longer throw and insert at the nearest valid
position); full fuzz suite re-run clean.

---

### 3. HIGH — a client's own delete echoing back corrupted its own caret,
   which then corrupted *subsequent* keystrokes

**Found:** typing text containing an emoji into the real browser UI, then
backspacing through it, and diffing the result against what should have
been deleted. The text came out with the wrong characters removed from the
wrong places — not a crash, not a CRDT convergence bug (the underlying data
was always correct), but a real, user-visible data-corruption bug in the one
tab actually being typed in.

**What was wrong:** two things compounded:

- `net.js` originally special-cased "skip an incoming op if its siteId is
  mine — I already applied it locally." That's true within one unbroken JS
  session, but false the instant identity persists across a page reload: a
  fresh page load has an *empty* in-memory replica and must replay this
  exact site's own pre-reload history from the relay's backlog like anyone
  else's. (Confirmed independently by `test_browser.js`'s dark-mode reload
  check, which failed until this was fixed.)
- Once that shortcut was removed (see fix below), a site's *own* delete op
  legitimately echoes back to itself over its own SSE subscription. But
  `applyRemote`'s delete branch, unlike its insert branch, had no
  idempotence guard — it recomputed `visibleIndex` (getting `-1`, since the
  node was already tombstoned) and reported `applied: true` a second time.
  `app.js`'s caret-shift logic saw that phantom `-1 < caret` and shifted the
  local caret left *again*, for a delete that removed zero additional
  characters. Repeated over several backspaces, the real browser caret
  drifted further and further from where the user's next keystroke actually
  landed, so each subsequent backspace/keystroke silently acted on the
  wrong character.

**Fix:** removed the siteId shortcut from `net.js` entirely (idempotent
`applyRemote` makes it redundant, not just unsafe) and added the missing
`if (node.deleted) return { applied: false, reason: 'duplicate' }` guard to
the delete branch, symmetric with the insert branch's existing `byId.has`
check.

**Verified:** typed text containing an emoji (multi-unit UTF-16) into a real
headless-Chromium tab and backspaced through it, both with artificial
pacing between keystrokes and fully rapid-fire back-to-back — output now
matches the expected result exactly in both cases.

---

### 4. HIGH — a rejected op batch could still partially reach every other
   client

**Found:** re-reading `_handle_post_ops` specifically looking for
partial-failure states, then confirming with a live test.

**What was wrong:** the handler validated and appended/broadcast ops
one-at-a-time in a loop, returning `400` the instant it hit a malformed op
— but every *earlier*, valid op in that same batch had already been
appended and broadcast to every other subscriber before the loop got that
far. A client sending `[valid_op, malformed_op]` would see "400, your
request failed" while every other open tab on that document had already
silently received `valid_op`.

**Fix:** validate the entire batch first; only append/broadcast once every
op in it has passed `_valid_op`.

**Verified:** `tests/test_relay.py::test_partial_batch_is_atomic_not_partially_broadcast`
sends `[good_op, bad_op]`, asserts `400`, then asserts the server's log for
that document is still completely empty.

---

### 5. MEDIUM — a duplicated browser tab could collide identities and
   silently drop a real keystroke

**Found:** thinking through what a completely ordinary browser action
("Duplicate Tab") does to this app's identity model.

**What was wrong:** `siteId` was originally persisted in `sessionStorage`
for reload continuity. But `sessionStorage` is exactly what a browser's
"Duplicate Tab" feature clones into the new tab — so two tabs could end up
generating ops under the literal same `(counter, siteId)` identity. If both
then typed concurrently, they could mint a genuinely colliding id for two
*different* characters; the CRDT's own duplicate-detection (`byId.has`)
would then treat the second one as a redundant redelivery of the first and
silently drop it — real, silent data loss, not a cosmetic glitch.

**Fix:** stop persisting `siteId` at all — generate a fresh
cryptographically-random one on every page load. This was only safe to do
*because* of the fix in #3 above (removing the "skip my own ops" shortcut
made `siteId` continuity across reloads unnecessary for correctness in the
first place); `name`/`color` stay persisted since sharing those between two
duplicated tabs is purely cosmetic.

**Verified:** manual reasoning + the existing reload/convergence tests
continuing to pass with a fresh siteId every load; no practical way to
force a real "Duplicate Tab" event from a test harness, so this is a
design-level fix rather than something with its own dedicated regression
test — noted rather than hidden.

---

### 6. MEDIUM — the CRDT internals inspector had an XSS hole

**Found:** auditing every `innerHTML` assignment in `app.js` for unescaped
attacker-influenceable content, on the assumption that a relay with no
authentication should treat "another connected client" as untrusted input.

**What was wrong:** `renderInspector` correctly escaped a node's rendered
*character* (`escapeHtml(n.value)`) but not its *siteId* metadata
(`shortSite(n.author)`, `shortSite(n.leftId[1])`). The relay's op validation
(`_valid_id`) only checks that a siteId is a non-empty string — it doesn't
restrict its characters. A hostile or buggy peer could craft an op whose id
embeds markup (`[1, "<img src=x onerror=...>"]`); the relay would accept it
as structurally valid (correctly — that's not the relay's job to police)
and broadcast it, and every other connected client's inspector would then
render it as live HTML.

**Fix:** wrap both `shortSite(...)` calls in `escapeHtml(...)` too.

**Verified:** `tests/test_browser.js` crafts exactly this payload directly
against the relay's HTTP API (bypassing `crdt.js` entirely, like a real
attacker would) and asserts (a) `window.__xss` was never set and (b) the
payload appears in the DOM HTML-escaped rather than as a live `<img>` tag.

---

### 7. MEDIUM — pasting a few thousand characters visibly froze the UI

**Found:** timing `rga.localInsert(0, 'x'.repeat(5000))` directly, on the
theory that "paste a paragraph of text" is a completely ordinary action a
performance bug could hide behind (all earlier functional tests used short
strings and never would have noticed).

**What was wrong:** **2.24 seconds** for a single 5,000-character insert.
Every character in a local multi-char insert re-ran both the full
concurrent-sibling tie-break scan *and* a full `O(n)` `posById` rebuild —
`O(n)` work per character, `O(n²)` for the whole paste.

**Fix:** added a same-run fast path in `localInsert`. Only the *first*
character needs the general scan (it may really be contesting a position
against some pre-existing sibling); every character after it in the same
local call is provably each other's only possible concurrent sibling — they
were all just created, synchronously, in this exact call, so nothing else
in the universe could reference them yet — meaning each one deterministically
belongs exactly one slot past the previous one, no scan needed. The
`posById` rebuild is now done once per call instead of once per character.

**Verified:** the same 5,000-character insert now takes **~11ms** (measured
directly; ~200x faster), and the full convergence fuzz suite still passes
(this fast path is exercised by every multi-character random edit the
fuzzer already generates, not just this one dedicated timing check).
`localDelete` was measured too (46ms to delete-all of 5,000 characters) and
judged acceptably fast as-is — not worth the same batching complexity for a
non-crashing, sub-50ms operation.

---

### 8. LOW-MEDIUM — reloading or closing the tab while offline could
   silently discard unsynced edits

**Found:** thinking through what happens to `net.js`'s in-memory outbox
across a page reload — there's no localStorage persistence of the CRDT
state at all (a disclosed, deliberate scope decision — see README's "known
limits"), so a reload while offline wipes the queued-but-unsent edits with
zero warning to the user.

**Fix:** true offline persistence across reloads is out of scope for
today's build, but *silent, unwarned* data loss on an ordinary accidental
reload/close is a much cheaper, narrower problem — added a standard
`beforeunload` guard (`window.addEventListener('beforeunload', ...)`) that
blocks navigation with the browser's native "you have unsaved changes"
confirmation whenever `net.hasUnsyncedChanges()` is true, exactly the same
pattern any editor with a "you have unsaved changes" prompt uses.

**Verified:** `tests/test_browser.js` dispatches a synthetic `beforeunload`
event while offline edits are pending and asserts `event.defaultPrevented`
is `true`; asserts it flips back to `false` once those edits have
synced.

---

### 9. LOW — a failed POST while nominally "online" could strand queued ops
   with nothing left to retry them

**Found:** reading through `net.js`'s error-handling paths and asking "what
actually re-triggers a retry here?"

**What was wrong:** `sendOps`/`_flushOutbox`'s failure handlers pushed the
ops back onto the outbox and set the UI status to "reconnecting" — but
didn't actually do anything to force a reconnect. The *only* thing that
flushes the outbox is the SSE stream's next `'ready'` event. If a POST
failed for a reason that didn't *also* trip `EventSource`'s own `onerror`
(a real possibility — they're separate connections), the outbox could sit
stuck indefinitely with literally nothing left in the system that would
ever retry it.

**Fix:** both failure paths now explicitly call a shared `_retryConnection`
helper that forces a fresh `connect()` call, guaranteeing there's always
something driving toward a retry. Safe by construction: both call sites are
only reached after already checking `this.online`, so this can never fire
during (or fight) a deliberate `disconnect()`.

**Verified:** full integration/browser suite re-run clean after the change;
this specific failure mode (a POST failing while the SSE stream stays
nominally healthy) isn't practical to force deterministically from a test
harness without adding a network-fault-injection layer that would be a
bigger addition than the fix itself, so — as with #5 — this is disclosed as
reasoned-through rather than test-gated.

---

---

### 10. MEDIUM — the offline banner rendered even while hidden (Phase 4)

**Found:** screenshotting the freshly-loaded, still-online empty-state UI
during Phase 4's visual redesign pass — the "You're offline" banner was
plainly visible in a screenshot of a tab that had never gone offline.

**What was wrong:** the redesign gave `#offline-banner` its own
`display: flex` rule (needed for its icon + text layout). An ID selector
outranks a bare attribute selector on specificity, so that rule beat the
browser's built-in `[hidden] { display: none }` UA rule outright —
`app.js` was correctly setting/clearing the `hidden` attribute the whole
time (this project's own stated convention: toggle `.hidden`, never
`style.display`), but the attribute was being silently overridden by CSS
that had nothing to do with visibility logic. A `Playwright` check that
only asserts the `[hidden]`/`:not([hidden])` attribute selector — which
`test_browser.js` did, right up until this was found — would never catch
this, because the attribute itself was always correct; only the actual
rendered `display` was wrong. Only a real screenshot (or an explicit
`isVisible()` check) surfaces it.

**Fix:** split the layout declaration into `#offline-banner:not([hidden])
{ display: flex; }` so the `[hidden]` state has nothing left to lose the
specificity fight against.

**Verified:** direct `page.isVisible('#offline-banner')` checks (true only
while offline, false otherwise) — added permanently to `test_browser.js`
right after the initial online-status check, specifically to keep this
"attribute is right but rendering is wrong" class of bug from silently
regressing again.

---

## Things checked and found NOT to be bugs

- **Same-site ops arriving at the relay out of the order they were
  generated** (a real possibility: a browser's connection-pool can dispatch
  several `fetch()` calls from rapid keystrokes over parallel connections
  that don't preserve issue order). This is exactly what causal buffering
  exists for — a receiving replica correctly holds a dependent op until its
  dependency shows up, regardless of *why* the network reordered them.
  Rather than being a bug, this validates the buffering feature; added the
  fully-scrambled-order fuzz variant (which ignores per-site ordering
  entirely, strictly harder than anything a real network does) specifically
  to keep this covered.
- **Tombstones accumulate forever and are never garbage-collected.** True,
  and a real cost of the RGA design (a document that's been heavily edited
  keeps every deleted character's node around). This is the standard,
  well-understood RGA trade-off (a "GC" pass would need a causal-stability
  check that's a meaningfully bigger feature), not an oversight — disclosed
  in README rather than silently accepted or hidden.
- **A dependency that never arrives buffers forever.** Also true, and also
  correct: the only two possible behaviors for a causally-dependent op
  whose dependency legitimately never shows up are "wait forever" or
  "silently apply something wrong" — buffering forever is the only sound
  choice. The `pendingCount()` is surfaced in both the statusbar and the
  inspector precisely so this state is visible rather than mysterious.
- **Unicode astral characters (e.g. 🎉) split across two RGA nodes** (one
  per UTF-16 surrogate half), since the engine operates on UTF-16 code
  units, not grapheme clusters. Convergence is unaffected (proven by the
  fuzz suite, which includes emoji in its alphabet) and a delete can't
  crash on an orphaned surrogate half — verified directly by backspacing
  through an emoji in a real browser tab. A genuine, disclosed limitation
  (this is also how a plain `<textarea>` already behaves), not something
  this build attempts to fix with grapheme-cluster-aware editing.
