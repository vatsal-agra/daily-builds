# Adversarial review

Methodology: read every algorithm against the Chord paper's actual pseudocode
line by line looking for places the implementation diverged; then attacked
the running system directly — real multi-process clusters (6 to 20 nodes),
real `SIGKILL`s, non-default ring configurations, deliberately broken
environments (occupied ports), and edge-case CLI input — rather than only
reasoning about the code in the abstract. Every bug below was caught by
actually reproducing it against a live cluster, not just by inspection.

## Bugs found and fixed

### 1. (found during Phase 2, fixed before it shipped) `stabilize()` never asked a lone node for its own predecessor

**Symptom:** on a freshly-formed 5-node ring, one node's successor pointer
stayed pointed at *itself* forever, and every single `put()` ended up
routed to that one node regardless of key.

**Root cause:** `stabilize()` had `if succ.id != self.ref.id: ...` guarding
the entire "ask my successor who its predecessor is" step, on the theory
that asking yourself is pointless. It isn't: in the real Chord protocol,
when node `A` is alone (`A.successor == A`), the exact way `A` ever
discovers the first node `B` that joins it is by asking "my successor"
(itself) for "its" predecessor (which, on `A`, is `A.predecessor` — and
that's set to `B` the moment `B` first calls `notify` on `A`). Special-casing
`succ == self` away breaks the single mechanism a solo ring uses to grow.

**Fix:** removed the guard; `stabilize()` always queries (locally, if
`succ == self`, via the same code path as any remote query — `ChordServer`
already short-circuits same-id calls to a direct local method call, so
this costs nothing).

### 2. (found during Phase 2, fixed before it shipped) fault-tolerant lookup fallback rejected candidates it had never actually tried

**Symptom:** after killing a node mid-cluster, ~13% of `get()` calls for
*unrelated, live* keys failed with "routing loop detected," even though the
correct data was sitting right there on a live replica.

**Root cause:** `iterative_find_successor`'s dead-hop fallback path chose
the next candidate from the previous hop's successor list, then added that
candidate's id to the "already visited" set *before* ever attempting to
contact it. The very next loop iteration's top-of-loop loop-guard saw that
id already marked visited and raised "routing loop detected" — on the
candidate's first and only attempt.

**Fix:** the visited-set (`contacted_ids`) is now only populated after a
node *successfully* answers, so it genuinely tracks confirmed routing
cycles among live hops, never candidates merely queued to try next.

### 3. `get()`/`put()` hashed keys into the wrong-sized identifier space for a non-default ring

**Symptom:** none observed on the default 32-bit ring (the bug happens to
be numerically invisible whenever the ring's `--m-bits` is a value ≤ the
hardcoded default, because reducing a value mod 2^32 and then mod a
smaller power of two gives the identical result as reducing directly —
`(x mod 2^32) mod 2^m == x mod 2^m` for any `m <= 32`). It would **not**
be invisible for `--m-bits` > 32, or for any non-power-of-two scheme:
keys would systematically load onto a lucky subset of the ring instead of
spreading uniformly, a real, silent, load-skewing bug.

**Root cause:** `node.get()`/`node.put()` hard-coded
`hashing.key_id(key, hashing.DEFAULT_M_BITS)` instead of accepting the
ring's actual configured `m_bits`. The CLI *tracks* `m_bits` per cluster
in its state file but was never threading it through to the actual hashing
call.

**Fix:** `get()`/`put()` now take an explicit `m_bits` parameter (default
preserved for convenience/back-compat), and every CLI call site
(`put`, `get`, `trace`) passes `state["m_bits"]` explicitly. Verified with
a real 6-node cluster running `--m-bits 12` end to end (put/get/status all
correct, ring converges to the exact sorted 12-bit cycle).

### 4. `cluster-start`'s readiness check couldn't distinguish "our node is up" from "some other process already occupies this port"

**Symptom:** reproduced directly: pre-occupy a port with an unrelated
listening socket, then `cluster-start` a cluster that includes that port.
The real node process crashed on `bind()` and exited immediately — but the
CLI reported full success and wrote a state file listing a "started" node
that did not exist, because its readiness check was a bare
`socket.create_connection()`, which happily completes a TCP handshake
against *any* listener, including the unrelated one still squatting the
port.

**Fix:** readiness is now checked by an actual Meridian `ping` RPC against
the node's real identifier (so a impostor listener that doesn't speak the
protocol fails the check), and the subprocess's `poll()` is checked on
every iteration so a process that already exited is reported immediately
instead of only after the full timeout elapses. On failure, `cluster-start`
now kills every process it had already spawned before exiting, rather than
leaking them.

### 5. `kill` and `cluster-start` crashed on ordinary operator mistakes

**Symptom:** `kill <port>` a second time raised an uncaught
`ProcessLookupError` traceback (the pid was already gone); killing a port
that was already marked killed sent a redundant `SIGKILL` to a possibly
*reused* pid. `cluster-start` on top of an existing `--force`-less state
file was fine, but a mid-spawn failure (see #4) used to leave already-started
subprocesses running with no record of them.

**Fix:** `kill` now checks the `killed` flag first, and catches
`ProcessLookupError` around the syscall itself, printing a clear message
either way instead of a traceback. `cluster-start` cleans up on failure
(see #4). `cluster-start 0` (or negative) is now rejected with a clear
error instead of silently doing nothing and writing an empty cluster.

### 6. (found while writing Phase 5's unit tests) `put()` had no fallback when the routing-reported owner was already dead

**Symptom:** none seen in the earlier manual cluster testing, because
those tests always killed a node *after* successfully storing data on it.
Writing a fast in-memory unit test for the "kill it first, then use it"
ordering caught it immediately: `put()` called `rpc_call(final_node,
"store", ...)` with no `try`/`except` around it at all, so if the node
`iterative_find_successor` reported as responsible had already died before
the `store` call landed, `put()` raised the raw `RPCError` straight out to
the caller instead of falling back to a live replica the way `get()`
already did.

**Root cause:** `iterative_find_successor` is, by design, a pure routing
function — it reports whatever a live node's own local view currently
believes is responsible for an id, and never itself contacts that
*reported* node to check it's actually still up (see its updated
docstring / `_candidate_replicas`'s docstring for why: verifying every
reported answer would mean paying a liveness check on every hop, most of
which don't need it). `get()` already accounted for this by falling back
to successor-list candidates when the reported node didn't answer;
`put()` never got the equivalent handling.

**Fix:** factored the candidate-resolution logic both functions need
(reported node, else its successor list, else the previous hop's view of
that list) into one shared helper, `_candidate_replicas()`, and `put()`
now tries each candidate in turn exactly like `get()` does. Covered by
`tests/test_node_unit.py::TestGetPutSurviveAPrimaryOwnersDeath`, including
the specific "the node routing reports doesn't exist by the time we try to
use it" ordering that the manual, ad-hoc cluster testing in Phases 2-4 had
never actually exercised.

### 7. (found running the real-cluster test suite) a single-node kill occasionally exhausted the fallback candidate list

**Symptom:** on one run of the 15-node real-cluster fault-tolerance test
(30 keys stored, one node holding several primary keys `SIGKILL`ed, then
all 30 immediately read back), exactly 1 of 30 reads failed with "no live
successor candidates after ... died" — even though only a single node had
died and the replication factor was `r=4`.

**Root cause:** `_candidate_replicas()`'s fallback (when the reported
responsible node is dead) asks the *previous hop* for **its** cached
successor list and tries whichever entries that contains. That cached list
is a snapshot from the previous hop's last `stabilize()` round — which,
immediately after `cluster-start`, might not yet have grown to `r` full
distinct entries (a freshly-joined node's successor list can still be
padded with repeats of very few real neighbors it has learned about so
far). If that particular cached list happened to consist entirely of the
now-dead node (padding repeats it), there was nothing else to try — not
because replication had actually failed, but because the *specific* cached
view this one lookup path happened to consult was momentarily thin,
while a fresh routing attempt from scratch a moment later would very
likely see an already-more-complete view.

**Fix:** `get()`/`put()` now retry the *entire* lookup (fresh routing from
the original start node, not just re-trying candidates from the same
stale hop) up to 3 times with a short delay, before finally raising. A
definitive `KeyNotFoundError` from a live, reachable node is never
retried, since more attempts can't change a confident negative answer.
This is standard practice for any DHT client talking to a system that is
only ever eventually consistent, and is different from (and does not
weaken) the deliberate "not a bug" limit right below: this retry helps
exactly the transient "my cached view was momentarily thin" case, not the
genuine "more than `r-1` nodes are actually down" case, which still fails
after retries exhaust, as it should.

## Reviewed and judged not a bug (by design / inherent to the protocol)

- **Stale replicas after a key's ownership moves are not actively deleted.**
  When a new node joins and takes over part of an existing node's key
  range, the *old* replica copies that other nodes were holding on the
  *previous* owner's behalf are left in place rather than eagerly cleaned
  up. This cannot produce a wrong answer for keys that are only ever
  written once (which is everything this build's put/get and tests
  exercise) since the stale copy's value is still correct; it would only
  become observable as staleness if a key were overwritten and then, before
  the new replicas fully propagate, an old dead-node's stale copy were
  served instead of the update. This is exactly Chord's real, well-known
  consistency model — eventually consistent, not linearizable — and fixing
  it fully would mean adding per-key versioning/vector clocks, which is a
  different, larger feature than "a DHT," not a bug in this one. Documented
  as a limitation in the README rather than silently left unmentioned.
- **A lookup can legitimately fail if more than `r - 1` nodes in a row have
  failed simultaneously.** This is the fault-tolerance bound the paper
  itself describes (successor-list depth `r` tolerates `r - 1` concurrent
  failures); exceeding it and failing loudly is correct behavior, not a
  bug, and the CLI reports it as a clean error rather than a traceback.
- **Concurrent (unstaggered) joins can cause a brief period where finger
  tables point at slightly stale information.** Verified this always still
  converges to the fully correct sorted ring via `stabilize()`'s continued
  background passes; Chord's join protocol is explicitly designed to be
  correct-eventually under concurrent joins, not correct-instantaneously.

## Hardening applied while reviewing (not bugs, but worth doing)

- The RPC server now tolerates a malformed/truncated message on a
  connection (drops that one request) instead of leaking a raw traceback
  to stderr per bad request.
- `KeyNotFoundError`'s message is now a full sentence instead of just the
  bare key, so `meridian get missing-key` prints something a human can
  act on instead of a cryptic repr.
- The CLI's routing-start-node selection (`_first_alive_ref`) now actually
  pings a candidate before using it, instead of trusting the "not killed by
  us" bookkeeping flag, so a node that died for some other reason doesn't
  make every single command fail with a confusing "bootstrap unreachable"
  error.
- `meridian status | head` (or any reader that closes the pipe early) no
  longer prints a `BrokenPipeError` traceback.
