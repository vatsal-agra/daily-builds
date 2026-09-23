# Gossamer

A from-scratch Dynamo-style leaderless distributed key-value store: real
consistent hashing with virtual nodes, real vector clocks for causality
tracking, tunable N/R/W quorum reads/writes with background read-repair,
and gossip-based failure detection — all running over real HTTP between
real independent OS processes. Hinted handoff, Merkle-tree anti-entropy
repair, and a live dashboard round it out.

The flagship demo proves it isn't just "eventually consistent" as a slogan:
it kills a real node mid-session, keeps serving correct reads and writes
through the outage via hinted handoff, revives the node from an *empty*
store, and watches it recover with zero manual repair — then, separately,
drives two clients to write the same key concurrently through two different
coordinators with no shared context, and shows the store keeping **both**
values as real siblings instead of silently picking a winner, exactly the
way a genuine vector-clock conflict is supposed to surface.

## Why this, today

This repo has built a lot of distributed systems, and every one of them
picked a *coordinated* consistency model:

- **Quorum** (Raft) — a single elected leader, strong consistency via a
  crash-fault-tolerant vote.
- **Concord** (an RGA CRDT collaborative editor) — no leader, but also no
  real conflict: every concurrent edit merges automatically and
  deterministically by construction.
- **Vein** (a Proof-of-Work blockchain) — no leader, mutually distrusting
  participants, consensus via an expensive public tie-break.
- **Swarm** (BitTorrent) — no leader, no vote, no shared mutable state at
  all; peers only ever transfer an immutable, hash-verified file.

None of these is the classic Amazon Dynamo shape: **many replicas of the
same *mutable* key, no leader, and writes that can genuinely and
permanently disagree.** Two clients can write concurrently to different
replicas while a third is unreachable, and there's no vote, no chain, and
no CRDT-style auto-merge to paper over it — the system's job is to *detect*
that disagreement structurally and hand it back to the application as real
sibling values, while staying available for reads and writes through
partitions and node failures. Getting that right needs a ring to decide who
to ask, vector clocks to decide whether two answers actually conflict,
quorum math to decide when to declare success, and a decentralized failure
detector to decide who to skip — four mechanisms that only mean something
once they're wired together into one live system, which is what this build
is.

## How to run it

```bash
python3 -m gossamer.demo
```

Starts a real 5-node cluster (independent OS subprocesses, real HTTP
between them) and runs eight narrated, assertion-backed scenarios end to
end: consistent-hash routing, a basic put/get through any node, quorum
fault tolerance after a real `SIGKILL`, gossip-based failure detection
converging to "suspected" then "dead" purely from local views, hinted
handoff to a substitute node, full data recovery after reviving a node from
an empty store, a genuine concurrent-write conflict surfacing as two real
siblings and then being resolved, and a Merkle-tree anti-entropy repair
measured to transfer a partial diff rather than a full resync.

```bash
./demo.sh
```

Runs the full test suite, a CLI smoke test, the flagship demo above, and a
real headless-Chromium pass over the live dashboard — everything this repo
promises, checked, in one command.

Manual usage, as a long-running cluster of separate OS processes:

```bash
python3 -m gossamer.cli cluster start --nodes A,B,C,D,E --base-port 9500
python3 -m gossamer.cli put mykey '"hello"'
python3 -m gossamer.cli get mykey
open http://127.0.0.1:9500/dashboard   # live ring, gossip views, conflicts
python3 -m gossamer.cli cluster stop
```

Any node can coordinate any request — there is no special coordinator
binary, and every node in the cluster runs the exact same code.

## Feature list

**Required:**

1. **Consistent hashing ring with virtual nodes** (`gossamer/hashring.py`)
   — SHA-1-based, each physical node owns many virtual positions so adding
   or removing one node reshuffles roughly `1/n` of the keyspace rather
   than everything. Verified by a property test that removes a node from a
   10-node ring and checks *exactly* which keys moved (only the ones that
   actually routed through it) and that the fraction moved is close to the
   theoretical `1/n`, not "most of them."

2. **Vector clocks for causal conflict detection** (`gossamer/vclock.py`,
   `gossamer/store.py`) — real causal reasoning (`EQUAL`/`DESCENDS`/
   `ANCESTOR`/`CONCURRENT`), not last-write-wins with a timestamp. A write
   that causally descends every current value replaces them; a write
   causally descended by an existing value is rejected as stale; a write
   concurrent with the current value becomes a real second sibling.

3. **Quorum reads/writes with background read-repair**
   (`gossamer/node.py::coordinate_put/coordinate_get`) — a tunable
   `(N, R, W)`: `N` replicas per key, a write acks once `W` respond, a read
   acks once `R` respond and returns the causally-merged sibling set. Any
   replica caught holding a stale or missing value during a read gets the
   winning value pushed back to it over a real internal HTTP call.

4. **Gossip-based failure detection** (`gossamer/gossip.py`) — every node
   periodically exchanges heartbeat counters with a random peer; failure
   status (`alive`/`suspected`/`dead`) is derived *locally* from elapsed
   wall-clock time since each node's own last observation, never copied
   from a peer's opinion. There is no central membership authority.

**Stretch (both shipped):**

5. **Hinted handoff + Merkle-tree anti-entropy repair**
   (`gossamer/node.py`, `gossamer/merkle.py`) — when a preferred replica is
   suspected dead, the coordinator writes a tagged "hint" to a
   deterministically-chosen substitute instead; hints flush back to the
   owner the moment gossip reports it alive again. Independently, every
   node periodically diffs a Merkle tree over its key space against a
   random peer's and repairs only the actually-divergent buckets — proven
   in the flagship demo by loading 220 keys, taking a node down for part of
   that load, reviving it, and confirming it catches up via background
   repair with **no read ever issued** (so read-repair structurally can't
   be what fixed it).

6. **Live dashboard** (`gossamer/dashboard.html`, served at `/dashboard` on
   any node) — a dependency-free HTML/CSS/vanilla-JS page polling every
   node's own `/admin/status` and `/admin/events` directly (no central
   aggregator): the hash ring with animated live request routing, each
   node's own local gossip view of every peer, and real vector-clock
   conflicts highlighted the moment they occur. Verified with a real
   headless-Chromium smoke test against a live cluster, screenshotted, zero
   console errors.

## Architecture

Every physical node runs identically (`gossamer/node.py::NodeServer`): an
HTTP server (stdlib `http.server`, `ThreadingHTTPServer`), a local causal
store, a gossip/failure-detector thread, a hinted-handoff hint store, and
an anti-entropy thread — wired together with the hash ring and vector
clocks. A "client" is just any HTTP caller hitting some node's `/kv/<key>`
endpoint; that node becomes the coordinator for that one request only.
Nodes talk to each other only over real HTTP between separate OS processes
(`gossamer/cluster.py` spawns them via `subprocess.Popen`, the same pattern
this repo's Vein and Swarm builds used) — so a "dead node" in every test and
demo is a real `SIGKILL`, not a flag flip in shared memory.

## Testing

- `python3 -m unittest discover -s tests` — 64 tests: pure-logic unit tests
  for the ring, vector clocks, causal store, and gossip membership, plus
  real multi-process integration tests that kill and revive actual
  subprocesses to exercise quorum fault tolerance, gossip convergence,
  hinted handoff, read-repair, anti-entropy, and simultaneous multi-replica
  failure.
- `tests/browser_smoke.py` — a real headless-Chromium pass over the live
  dashboard against a running cluster.
- Stress-verified: the full suite was re-run 12 consecutive times with zero
  failures after the Phase 4 timing fix documented in
  [REVIEW.md](REVIEW.md)'s flakiness addendum (it used to fail roughly 1
  run in 6-8 under full-suite load).

See [PLAN.md](PLAN.md) for the original design plan and
[REVIEW.md](REVIEW.md) for the adversarial review: 7 real bugs found and
fixed, including a silent data-loss bug in hinted-handoff flush retry and a
URL-encoding bug that corrupted keys containing reserved characters on
genuinely remote replicas — each with a regression test.

## Where a human could take this next

- **Real network partitions, not just node death.** Everything here tests
  a node going fully silent; a genuine `iptables`-style partition (nodes
  A/B can't reach C/D/E, but C/D/E can all reach each other) exercises a
  different and harder case — both sides accepting writes and forming
  divergent sibling sets that only reconcile once the partition heals.
- **A real client library with automatic conflict resolution policies**
  (last-write-wins by timestamp, CRDT-style per-field merge, or an
  application callback) instead of leaving every sibling to the caller.
- **Persistence.** The local store is in-memory only; a node revived in
  this build starts genuinely empty and recovers via hinted handoff or
  anti-entropy — swap in an on-disk log (this repo's own PicoSQL or Graft
  builds have real from-scratch on-disk formats to borrow the pattern from)
  and a node could recover its own last-known state before repair even
  starts.
- **Dynamic ring membership** — `HashRing.add_node`/`remove_node` already
  exist and are tested, but nothing in the running cluster currently calls
  them at runtime; wiring a `join`/`leave` RPC would let the cluster
  actually grow and shrink live instead of only at startup.
- **Sloppy quorums and stricter consistency levels** (`ONE`/`QUORUM`/`ALL`
  per request, the way real Cassandra exposes it) instead of one fixed
  N/R/W for every key.
