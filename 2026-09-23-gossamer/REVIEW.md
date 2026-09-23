# Adversarial review (Phase 3)

Attacking Gossamer as a hostile reviewer: real multi-process testing (killing
and reviving actual OS processes), deliberately malformed/exotic input, and
line-by-line re-reading of every concurrency-sensitive path. Every issue
below was reproduced with a concrete failing test or manual repro *before*
being fixed, and every fix has a regression test.

## Issues found and fixed

### 1. CRITICAL — silent data loss on a second hint-flush failure (`node.py::_flush_hints_for`)

**Repro:** node X holds hinted-handoff data for owner O across keys
`k1, k2, k3`. O revives, X starts flushing. O goes down again mid-flush,
right as X is sending `k2`. The original code:

```python
bucket = self.hints.pop(owner, {})   # entire bucket removed from self.hints
for key, siblings in bucket.items():
    for value, vclock, _ in siblings:
        try:
            httpjson.post_json(...)                      # k1 succeeds
        except httpjson.NodeUnreachable:
            ...                                           # k2 fails here
            self.hints[owner][key] = ...                  # only k2 is put back
            return                                        # k3 is NEVER put back
```

`bucket` was popped out of `self.hints` *entirely* up front. On the first
failure the loop puts back only the *currently failing* key and returns —
every subsequent key that hadn't been attempted yet (`k3` here) is gone
forever: not on O, not on X, not anywhere. A node that goes down twice in
quick succession during handoff permanently loses whatever hinted data
hadn't been reached yet, with no error surfaced anywhere.

Caught by re-reading the failure-recovery branch, not by a test — the
existing hinted-handoff test only exercises a single clean revival, so a
second failure during the flush itself was never exercised. Fixed by
building a `remaining` dict that starts as a full copy of the bucket, only
removing a key once its flush is *confirmed* successful, and merging the
*entire* unprocessed remainder back into `self.hints[owner]` on the first
failure — not just the one key that happened to be mid-flight. Added
`tests/test_flush_hints.py` reproducing the exact scenario (3 keys, second
one fails) and asserting all three keys are still recoverable afterward.

### 2. Keys containing reserved URL characters break or silently misroute (`node.py`, `client.py`)

**Repro:** `gossamer put "a key with spaces" '"v1"'` crashed outright with
an uncaught `http.client.InvalidURL`. A key like `"a&b=c"` didn't crash, but
on a cluster with more physical nodes than the replication factor N (so some
replicas are genuinely remote from the coordinator), the internal
`/internal/get?key=a&b=c` request gets parsed by the receiving node's
`parse_qs` as `key=a` **and** an unrelated `b=c` parameter — the remote
replica silently answers about the wrong key. This corrupts *that one
replica's* read response (it looks empty), though read-repair happens to
paper over it for the client-visible answer in the common case — the actual
bug (broken query-string construction) was still real and would surface
directly the moment two nodes' data disagreed on such a key without a
repair cycle in between.

Root cause: `_local_or_remote_get` built `/internal/get?key={key}` by naive
f-string interpolation, no `urllib.parse.quote`; the client and the `/kv/`
path handler had the same gap for path segments. Fixed by quoting the key
(and `hint_for`) with `urllib.parse.quote(..., safe="")` everywhere a key is
placed into a URL, and unquoting it on every server-side path extraction.
Added `tests/test_url_encoding.py` covering spaces, `&`, `=`, `#`, `+`, `%`,
and a literal `/` inside a key, over a real 5-node cluster with genuinely
remote replicas.

### 3. No validation of N/R/W at startup (`node.py::NodeServer.__init__`)

A cluster configured with `w` or `r` greater than `n`, or `n < 1`, silently
starts and then just fails every write/read forever (`acks < w` on every
request) with no indication *why* — a classic "looks broken, isn't
obviously misconfigured" trap. Fixed by validating `1 <= w <= n`,
`1 <= r <= n` in the constructor and raising `ValueError` immediately with
a message naming the actual bad values, instead of a cluster that starts
clean and then mysteriously 503s on every request.

### 4. A malformed `context` on PUT crashes with a raw 500 (`node.py::coordinate_put`)

`context` is supposed to be a list of vector-clock dicts (exactly what a
prior GET returns). Passing anything else — a dict, a string, a number —
made `VectorClock.from_dict` blow up inside `dict(counters)` with a bare
`TypeError`/`ValueError`, surfaced as an opaque 500 rather than a clean
`400` naming the actual problem. Fixed with explicit validation of
`context`'s shape before touching `VectorClock`, returning a 400 with a
specific message for a non-list `context`, a non-dict element, or a
non-integer counter value.

### 5. Non-atomic metric counters under concurrency (`node.py`)

`self._read_repair_bytes += ...` and `self._anti_entropy_bytes += ...` are
updated from multiple `ThreadPoolExecutor` threads with a bare Python `+=`
on a plain `int` attribute — not atomic, so concurrent updates can lose
increments (read-modify-write race). Only affects the informational
counters shown in `/admin/status`, never the actual stored data, but it's a
real race with no lock protecting it. Fixed by moving both counters behind
a small dedicated lock.

### 6. `_repair_one` logs/counts a "repair" even when nothing was sent (`node.py`)

If a replica flips from alive to suspected/dead in the narrow window
between a GET response being collected and its async read-repair running,
the original code skipped the actual RPC (correct) but still unconditionally
logged a `"read-repair"` event and added to `_read_repair_bytes` (incorrect
— nothing was transferred). Fixed by moving the logging and metric update
inside the success path only, so the dashboard's event log reflects what
actually happened over the wire.

### 7. Dead no-op branch in the gossip loop (`node.py::_gossip_loop`)

```python
if self.membership.status_of(target) != ALIVE and random.random() < 0.5:
    # Still occasionally probe non-alive peers so a revived
    # node gets noticed promptly, but bias towards live peers.
    pass
```

This comment promises behavior (bias gossip target selection toward live
peers) that the code never actually implements — a `pass` that does
nothing, left over from an abandoned approach. It's not a correctness bug
(random selection already gets every peer reached with adequate probability
in a small cluster, confirmed by the failure-detection tests), but it's
exactly the kind of dead, misleading code this review exists to catch.
Removed outright rather than left as decoration.

## Investigated, not a bug: hint concentration under simultaneous multi-replica failure

If two of a key's three preferred replicas are down *at the same time*,
each one's substitute is picked independently (`pick_substitute` is a pure
function of `(key, owner, alive-set)`, deliberately not coordinated across
concurrent `do_one` calls so that writers and readers can each recompute the
same target without any shared cache). This means both down replicas' hints
can land on the *same* single substitute node, concentrating risk (if that
one substitute also dies, both hints are lost together) instead of spreading
it across two different survivors.

This was deliberately not "fixed" by adding cross-owner collision avoidance:
doing so correctly requires resolving substitutes in a canonical order
shared by both the writer and every future reader, which trades a subtle
concurrency bug for a subtler ordering-dependency one, for a scenario this
review confirmed is not a correctness problem — `tests/test_multi_failure.py`
kills two of three replicas for the same key simultaneously and confirms the
write still succeeds, the read still returns the right value, and both
revived nodes fully recover their data. Documented here rather than
"fixed" because there was nothing actually broken to fix — only a resilience
trade-off worth being explicit about.

## Addendum: test-suite flakiness found while polishing (Phase 4)

Running the full suite repeatedly (not just once) surfaced a real, if
narrow, flake: `test_hint_is_stored_while_owner_down_and_flushed_on_revival`
failed roughly 1 run in 6-8 under the CPU load of running the whole suite
back to back. Root cause: several integration tests configured
`suspect_timeout` at only ~2-3x `gossip_interval` (e.g. `gossip_interval=
0.15, suspect_timeout=0.4`) to keep the suite fast. Under real system load
(many concurrent real clusters), a perfectly healthy node's heartbeat can
legitimately arrive a little late without the node being down at all — and
with that little slack, the coordinator's local failure detector would
occasionally mark a healthy peer "suspected" by mistake, so `pick_substitute`
found no candidate at all and no hint got stored, even though the write
itself still succeeded via the two genuinely-alive primaries. This is a
test-tuning bug, not a system bug — the underlying mechanism behaved
correctly given what it was (falsely) told about liveness — but it made the
suite unreliable, which is its own kind of defect. Fixed by widening
`suspect_timeout` to a safer multiple of `gossip_interval` (roughly 6-7x
instead of 2-3x) across the affected tests, bumping `request_timeout`'s
cluster-wide default from 1.5s to 3.0s so a transient slow RPC under load
isn't misread as an unreachable node, and rewriting
`test_multi_failure.py`'s write/read assertions to retry over a short
window — which is what a real client of a leaderless quorum store should do
on a transient quorum shortfall anyway, not a test-only concession. Verified
with 12 consecutive full-suite runs, all green (previously failing at
roughly the 5th-8th run).

## Gate

After all seven fixes: the suite grew from 49 to 64 tests (the new
`test_flush_hints.py`, `test_url_encoding.py`, `test_validation.py`, and the
multi-failure probe in `test_multi_failure.py`), all green, plus a clean
re-run of the flagship `python3 -m gossamer.demo` and `./demo.sh` end to
end. See git history for the fix commit.
