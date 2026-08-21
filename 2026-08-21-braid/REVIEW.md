# Adversarial review

Seven real issues found by attacking Braid as a hostile reviewer, each
reproduced with a concrete script before being fixed. All are fixed
below; none were shrunk out of scope.

## 1. A claimed limitation that turned out to be false for this algorithm

`crdt/rga.py`'s original docstring claimed RGA's textbook "interleaving
anomaly" (two peers concurrently typing multi-character runs at the same
position converge *interleaved*, e.g. `"aXbYcZ"` instead of clean
`"abcXYZ"` blocks) as an accepted limitation, copied from general CRDT
literature before the subtree-skip integration logic (`_subtree_end`)
was fully derived and tested.

**It's wrong for this implementation.** Once `_integrate` correctly skips
a losing sibling's *entire* subtree in one jump (not just the sibling
node itself), two peers each typing a genuine contiguous run from the
same shared starting position converge as two **intact, unsplit blocks**
— verified by actually reproducing the textbook setup (shared doc `"ye"`,
both peers insert at the gap, one types `"ABC"` character-by-character
with each keystroke chained to its own previous character like a real
editor does) across 50 random delivery orders: every single trial
converges to `"yXYZABCe"`, never a fragment.

The real, narrower anomaly *does* still exist, and is now demonstrated
rather than hand-waved: if **three separate peers** each independently
anchor a single character at a **different node strictly inside an
already-formed run** (not extending their own chain — e.g. peer X
inserts after run-char `A`, peer Y after `B`, peer Z after `C`, all
concurrently), the run genuinely fragments: `"yAXBYCZe"`, deterministic
across 30 random delivery orders. This is real and inherent to any
position-based sequence CRDT without extra move-tracking machinery — not
a bug, and not something "two people typing at once" in a real editor
actually triggers in practice (that specific pattern requires several
independent peers each targeting different existing characters, not one
person composing a sentence).

**Fix:** rewrite the `rga.py` module docstring and `PLAN.md` to state the
verified, narrower claim instead of the inaccurate broad one. Both
reproductions are preserved as `tests/test_interleaving.py` so the claim
stays checked, not just asserted in prose.

## 2. `Room.tick()` held the room lock across blocking socket sends

`tick()` called `self.net.step(deliver)` **while holding `self.lock`**,
and `deliver` calls `client.send_json`, a blocking `socket.sendall`. A
single slow or half-open client (a dropped WiFi connection, a browser
tab put to sleep) could stall delivery to every other peer in that room
— and since one shared background thread ticks *every* room in turn,
a bad enough stall could delay other rooms too.

**Fix:** collect the due `(peer, op)` deliveries while holding the lock,
release it, then send. `tests/test_server.py::test_slow_client_does_not_block_room`
reproduces this with a deliberately-stalled socket and asserts a second,
healthy client still receives its op promptly.

## 3. Live server had no anti-entropy — `loss_p > 0` could permanently drop an op

`verify/convergence.py` proves (and this review's Tier-2 output shows
honestly) that pure op-broadcast cannot survive permanent packet loss —
that's exactly why Tier 3 adds periodic anti-entropy. But the *live*
`braid_server.py` never actually ran that anti-entropy pass: with the
chaos panel's loss slider above 0%, a dropped op stayed dropped for
every already-connected client for the rest of the session (a client
that reconnects *does* get healed, via a fresh bootstrap from the
room's always-reliable mirror — so not silent data loss, but a
connected peer had no way to self-heal without reloading the page).

**Fix:** the room ticker now also runs a periodic (every 100 ticks,
~4s) anti-entropy pass per room, resending each connected client the
room's *entire* current `op_log` straight over the wire, bypassing the
chaos network (an assumed-reliable resync channel, same modeling choice
`verify/convergence.py`'s Tier 3 makes). This is a full resync rather
than a true diff: unlike the offline verifier, the server doesn't hold
an `RGA` replica *of each client* to diff against, only its own
reliable `mirror` — so it can't compute "what is peer X specifically
missing," only "what does the room canonically contain." Resending
everything is safe only because `apply_remote`/`RGA._log` are already
idempotent (an already-known op is a genuine no-op), so a healthy
client pays a periodic no-op scan, not corruption — acceptable at demo
scale, called out here rather than silently claimed as more efficient
than it is. `tests/test_server.py::test_loss_recovers_via_anti_entropy`
reproduces permanent loss live over real sockets and confirms both
peers converge without either one reconnecting.

**Self-caught regression while fixing this:** the first version of this
fix pushed the resync to *every* connected client unconditionally,
completely ignoring active partitions — re-running the existing
partition/heal Playwright regression test immediately after (standard
practice: re-run the full suite after every fix, not just the new one)
showed both "partitioned" tabs converging in real time, meaning the
anti-entropy pass had silently healed a partition it had no business
touching within one ~4s interval, breaking the "Partition me" demo
outright. Fixed by adding `SimNetwork.is_currently_partitioned()` and
skipping resync to any peer on either side of an active partition — a
deliberately-partitioned peer doesn't get a magic reliable backdoor a
real network split would also have severed.

## 4. Peer identity persisted in `sessionStorage` — Chrome's "Duplicate Tab" collides it

`app.js` stored the browser's randomly generated peer id in
`sessionStorage` so a page *refresh* keeps the same identity. But
Chrome (and most Chromium browsers) copy `sessionStorage` verbatim when
you duplicate a tab — the new tab would silently get the **same**
`peer_id` as the original, while its `RGA`'s Lamport clock starts fresh
at 0. Both tabs' first local insert would then mint the identical
`(1, peer_id)` node id for two different characters, which `apply_remote`
treats as a duplicate delivery and silently drops the second one —
genuine, silent character loss, not just a cosmetic identity clash.

**Fix:** stop persisting peer identity at all — generate a fresh random
id purely in memory on every page load. The cost (a reload gets you a
new anonymous identity, same as most anonymous-collaborator UIs) is far
smaller than a duplicated tab corrupting a shared document.

## 5. Malformed chaos-API query params crashed the request thread

`?loss=abc` (or a non-numeric `lat_min`/`ticks`) hit an unguarded
`float()`/`int()` call in `_handle_chaos_api`, raising an uncaught
`ValueError` that killed the request-handling thread with a raw
traceback instead of a clean 400 — and left the socket never explicitly
closed via `_send_http`, relying only on the OS to reclaim it when the
thread died.

**Fix:** wrap query-parameter parsing in a try/except that returns a
real `400 Bad Request` with a message, closing the socket normally.

## 6. Unbounded `SimNetwork.events` audit log

`events` is append-only, forever, for the life of the process — fine for
a bounded offline verification run, a real resource leak for a
long-running live server (every send/loss/duplicate/delivery in every
room, forever).

**Fix:** cap it to the last 500 entries per room (ring-buffer trim) —
it's diagnostic-only, nothing reads more than recent history.

## 7. Disconnected peers left a ghost cursor caret behind

`app.js` only removed a `remote-caret` marker when that peer's cursor
*moved* — a peer who disconnected mid-session left their last-known caret
rendered forever in every other open tab, with no signal it was stale.

**Fix:** the `presence` handler now prunes `remoteCursors` for any peer
no longer in the live peer list, and re-renders immediately.

## Also considered, deliberately not "fixed"

- **A malformed op from one client can raise inside that client's own
  message loop** (e.g. an `insert` op missing `id`) — Python's `finally`
  still runs `room.remove_client`, so the blast radius is exactly that
  one connection disconnecting itself, not the room or server. Given
  Braid has no authentication layer at all (out of scope — it's a
  from-scratch CRDT/network demo, not a hardened multi-tenant service),
  hardening every field of a JSON message against a malicious client
  wasn't worth the complexity it would add for a threat model this build
  doesn't otherwise defend against. A light try/except now logs and
  keeps the loop alive for the common case of a *transient* JSON
  hiccup, without pretending to be a security boundary.
- **Rooms are never garbage-collected** once created (even a bare
  `/api/chaos?room=X` ping creates one). Acceptable for a demo/session
  process; a real deployment would need idle-room eviction, noted here
  rather than built, since nothing in the required feature list needs it.
- **O(n) per RGA operation** (`_integrate`, `_visible_ids`) — documented,
  measured (1800 sequential inserts: 0.23s; 1000 random edits on a
  ~2000-char doc: 0.33s), and entirely adequate for a live-editing demo;
  a production sequence CRDT would use a balanced tree or skip list
  instead of a flat Python list, which is out of scope for a from-scratch
  educational implementation prioritizing a checkable correctness proof
  over asymptotic performance.
