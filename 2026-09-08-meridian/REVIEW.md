# Adversarial review

Phase 3: attacking Meridian's own implementation as a hostile reviewer,
hunting for bugs, broken edge cases, lazy shortcuts, and bad UX. This pass
happened in two waves: bugs caught while *writing* the test suite in Phase
2 (fixed immediately rather than left for this document to "discover" for
theater), and a dedicated adversarial pass afterward specifically looking
for concurrency/edge-case bugs the happy-path tests wouldn't surface. Every
issue below is fixed, with a regression test.

## Bugs found and fixed

### 1. `KBucket.remove()` never actually removed anything (found while writing tests/test_routing.py)

`self.contacts` is an `OrderedDict[int, None]` -- every stored value is the
same sentinel, `None`. `remove()` used to do:

```python
removed = self.contacts.pop(node_id, None) is not None
```

`dict.pop(key, default)` returns the *stored value* when the key exists --
and the stored value is always `None`, the same as the "not found" default.
So `removed` was `False` unconditionally, whether or not the key was
actually present and actually removed. Nothing downstream currently calls
`RoutingTable.remove()` in the live code paths (it exists for a future
graceful-leave-detection path and is exercised directly by tests), so this
never manifested in the demo/CLI -- but it's exactly the kind of bug that
would have silently broken a real caller. Fixed by checking membership
first (`if node_id not in self.contacts: return False`) instead of relying
on the pop's return value to signal presence.

### 2. Republishing a value never refreshed the republishing node's *own* local copy's expiry (found while writing tests/test_storage.py)

`tick_maintenance()`'s republish loops updated `last_published` /
`last_republished` bookkeeping and pushed fresh `StoreReq`s out to the
current k-closest peers -- but never touched the republishing node's own
`storage[key_id].expires_at`. A node holding a replica would dutifully keep
everyone *else's* copy alive on schedule while its own copy's TTL clock
kept counting down untouched, until `tick_maintenance()`'s expiry-purge
step deleted its own entry -- despite having just "republished" it moments
before. Fixed by adding `_store_local()`, called from both the owner-
republish and replica-republish paths (and from `put()` itself, so a
publisher also keeps a fresh local copy from the start), which refreshes
the local entry's `expires_at` in addition to the external `StoreReq`
pushes. Covered by `test_replica_holder_republishes_too` and
`test_value_survives_past_original_ttl_via_republish` (the latter is a
"survives past its original TTL" test that would fail if the local-refresh
half of this fix ever regressed, since the fetching node's own request
eventually gets routed to a holder relying on that refresh).

### 3. Concurrent "ping the head before evicting" episodes on the same bucket could evict the wrong contact (found by dedicated adversarial review, not by the happy-path test suite)

This is the subtle one. The core Kademlia eviction rule -- when a bucket is
full and a new contact shows up, ping the least-recently-seen ("head")
contact and only evict it if the ping times out -- is correct in isolation.
But if a *second* new contact shows up for the same bucket before the first
ping resolves, both episodes independently call
`RoutingTable.record()` -> `'ping_head'`, and both fire their own `PING`
against the same head contact. The bug was in how each episode's *outcome*
got applied:

```python
def resolve_ping_head(self, idx, candidate_id, head_alive):
    bucket = self.buckets[idx]
    if not head_alive:
        head = bucket.head()          # <-- re-reads head() NOW, not at ping time
        if head is not None:
            bucket.replace_head_with(candidate_id)
```

If the head really is dead, the *first* episode's ping times out and
correctly evicts it, promoting its own candidate. But the *second*
episode's ping (to the same, now-already-evicted contact) also times out
and resolves afterward -- and `resolve_ping_head` evicts "whatever
`bucket.head()` is right now", which is a completely different contact
that was never pinged, may be perfectly healthy, and had nothing to do
with the ping that actually failed. On a busy network with a small `k`
(more full buckets, more overlap), this would silently evict healthy,
long-lived contacts -- undermining the entire point of the "trust old
contacts over new ones" rule this feature exists to implement.

Fixed by having the caller (`DHTNode.record_contact`) pass the *specific*
contact ID it pinged through to resolution (`pinged_head_id`), and having
`KBucket.replace_head_with(old_id, new_id)` evict that specific contact --
becoming a safe no-op if it's no longer present, rather than a footgun
that evicts whoever happens to occupy the head slot at resolution time.
Caught with a direct unit test
(`test_overlapping_ping_episodes_never_evict_the_wrong_contact`) that
manufactures the exact race by hand (two candidates hitting an already-full
bucket before either ping resolves), then confirmed the fix survives a
60-seed fuzz sweep with tiny `k` values (1-20) specifically chosen to
maximize how often full-bucket eviction races actually occur.

### 4. `get_file` crashed on a syntactically-valid-but-wrong-shaped manifest (found by dedicated adversarial review)

The manifest-parsing path guarded against invalid JSON *syntax*
(`json.JSONDecodeError`) but not against JSON that parses fine and just
isn't a manifest object -- e.g. a tampered or bit-rotted value that decodes
to a JSON string or list. `manifest.get("chunk_hashes", [])` on a
non-`dict` raises `AttributeError`, uncaught, from inside a callback fired
deep inside the scheduled-event loop -- crashing the whole simulation run
with a raw traceback instead of reporting "this manifest is bad" the way
every other failure mode in `get_file` already does cleanly. Fixed by
validating the decoded value's shape (a dict, with a list of strings under
`chunk_hashes`, a string under `sha256`) before touching any field, and
reporting a clean `on_complete(None, False, "corrupt manifest: ...", None)`
otherwise. Covered by
`test_malformed_manifest_shape_is_reported_not_crashed`.

### 5. Duplicate `--nodes` argparse registration on the `demo` subcommand (found while writing tests/test_cli.py)

`build_parser()`'s `common(sp)` helper always added `--nodes` with a
default of 40; `cmd_demo`'s parser then added it a *second* time to give
`demo` a smaller default (30), which is an `argparse.ArgumentError` at
parser-construction time -- meaning `meridian demo` (and, transitively,
every other subcommand, since `build_parser()` builds all of them up
front) would have failed immediately on any invocation. Fixed by
parameterizing `common()` with a `nodes_default` argument instead of
re-registering the flag.

## Design choices verified, not bugs

- **Local `get()` can return a stale value if the same key is `put()`
  again with a different value elsewhere before the local copy's TTL
  expires.** This matches real Kademlia's actual guarantees (best-effort
  freshness via TTL + republish, not linearizable reads) rather than being
  a shortcut -- and it's also why the content-addressed file store never
  needs this to be stronger: a chunk's key *is* its hash, so a chunk is
  never "updated," only ever newly published under a different key.
- **A crashed node's periodic maintenance timer keeps firing forever**
  (it re-schedules itself every tick regardless of liveness, just skipping
  the actual maintenance work when dead). This wastes a trivial number of
  no-op events on a long-running simulation of a permanently-dead node, but
  costs nothing correctness-wise and isn't worth the complexity of
  proactively cancelling scheduled callbacks in a simulator that has no
  cancellation primitive to begin with.
- **Crashing every replica holder for a key simultaneously loses the
  data.** This is correct, expected behavior, not a resilience gap: no
  distributed system, Kademlia included, can survive the instantaneous
  loss of literally every copy of something with no warning. The CLI demo
  deliberately tests the meaningful claim instead -- surviving a *partial*
  outage (most, not all, replica holders crashing) -- documented inline in
  `cli.py`.

## Verification after fixes

Re-ran the full suite (107 tests, up from 104 -- three new regression
tests for bugs #3-#5 above, one more for #2) plus a 60-seed fuzz sweep
across randomized `(n, k, alpha, loss)` combinations exercising lookups,
churn, key/value STORE+GET, and file-store PUT+GET together in one script,
specifically choosing small `k` values (1-20) to maximize how often the
full-bucket eviction race from bug #3 actually triggers. Zero failures,
zero exceptions.
