# Meridian — a from-scratch Chord Distributed Hash Table

## Concept

Meridian is a real implementation of the **Chord protocol** (Stoica, Morris,
Karger, Kaashoek & Balakrishnan, SIGCOMM 2001) — the structured
peer-to-peer overlay that popularized "consistent hashing + finger tables"
as the answer to "how do a million machines, with no central directory,
each find the one machine responsible for a given key in `O(log N)` hops,
and keep working correctly while machines join and leave at will?"

It is a genuinely new domain for this repo's distributed-systems lineage.
Every prior distributed build here picked a different coordination shape,
but none has been a **structured routing overlay**:

- **Quorum** (Raft) — a known leader, a crash-fault-tolerant *vote* among
  trusted members.
- **Concord** (RGA CRDT) — no leader, but no adversary and no scarcity;
  every op just merges by construction, and there is no *routing* problem
  because every replica holds everything.
- **Vein** (Proof-of-Work blockchain) — mutually distrusting peers,
  consensus by expensive public tie-break, full replication of the whole
  ledger to every node.
- **Swarm** (BitTorrent) — no leader and no routing structure either; a
  central HTTP tracker hands out peer lists, and data placement is
  "whoever has the piece," not "whoever is *responsible* for the piece."
- **Matchbook** (exchange) — one central order book; not decentralized at
  all.

Chord is the odd one out: it is decentralized *and* structured. Every key
and every node is hashed into the same `m`-bit ring; a key belongs to
exactly one node (its successor on the ring); and each node maintains a
small `O(log N)`-sized **finger table** of long-range ring pointers so a
lookup started anywhere reaches the right node in `O(log N)` hops without
any node knowing the full membership. Nodes join and leave constantly in
the real protocol, and a background **stabilization** protocol continually
repairs successor/predecessor pointers and finger tables so the ring stays
correct — the interesting problem is proving that repair actually
converges under concurrent joins, and that data survives a node crash via
replication onto a **successor list**, not just a single successor.

Meridian implements the real protocol, not a toy simplification: SHA-1
160-bit identifier space, the paper's exact `find_successor` /
`closest_preceding_finger` / `join` / `stabilize` / `notify` / `fix_fingers`
/ `check_predecessor` algorithms, a successor-list for fault tolerance
(section IV of the paper), and real key migration on join/leave. Nodes are
independent OS processes talking real TCP, not threads sharing memory —
so "the ring" is only ever knowledge distributed across independently
crashable processes, exactly like the real thing.

## Architecture

```
meridian/
  hashing.py       SHA-1 ring math: sha1_id(), interval tests (open/closed,
                    wraparound-aware), finger start-point computation
  protocol.py       length-prefixed JSON-over-TCP RPC framing (request/response)
  node.py           ChordNode: local ring state (id, successor, predecessor,
                    successor-list, finger table, local KV store) + the
                    Chord algorithms (find_successor, join, stabilize,
                    notify, fix_fingers, check_predecessor, key migration)
  server.py         RPC server wrapping a ChordNode; background maintenance
                    threads (stabilize / fix_fingers / check_predecessor
                    loops) with jittered periods
  client.py         thin RPC client stub used by the server (node-to-node
                    calls) and by the CLI (external put/get/status calls)
  node_process.py   process entrypoint: `python -m meridian.node_process
                    --port P [--join HOST:PORT]` — one OS process, one node
  cli.py            operator CLI: cluster start/stop, put/get (reports the
                    actual hop path), status (ring dump across all live
                    nodes), kill (simulate a crash), trace (capture a
                    lookup for the visualizer)
  visualize.py      renders a self-contained HTML/Canvas ring visualizer
                    from a captured JSON snapshot (ring topology + finger
                    tables + one or more lookup traces with hop-by-hop paths)
tests/
  test_hashing.py         ring interval math, wraparound edge cases
  test_node_unit.py       single-process, in-memory-RPC unit tests of the
                           Chord algorithms against the paper's worked
                           3-bit example (Fig. 3/4 of the Chord paper)
  test_cluster.py         real multi-process integration tests: spin up N
                           real node processes over real sockets, join them,
                           put/get thousands of keys, verify against a
                           ground-truth dict, verify O(log N) hop bounds,
                           kill nodes mid-run and verify self-healing +
                           replica fallback, verify data migration on join
  helpers.py               process orchestration + free-port allocation for tests
examples/
  demo_cluster.json        a captured 8-node cluster trace used by the demo
demo.sh                    end-to-end script exercising every feature
PLAN.md / REVIEW.md / README.md
```

## Why this is interesting

The hard, checkable part isn't "can nodes exchange messages" — it's that
finger-table-based routing is only correct if the *invariant* it depends on
(`successor` pointers form a single sorted cycle over live nodes) holds
even while joins are happening concurrently and messages are in flight.
Chord's answer — join optimistically, fix everything lazily via periodic
stabilization — is a real, subtle, and *provably eventually correct*
protocol, and Meridian can be checked against genuine ground truth the same
way this repo's other "from scratch" builds check themselves: a real
`O(log N)` hop-count bound to verify, a paper-published worked example to
match exactly, and a brute-force oracle (a plain Python dict, updated
alongside real put/get calls to real crash-prone processes) that the live
cluster's answers must always agree with, including immediately after a
node is killed.

## Feature list

**Required (4):**

1. **Consistent hashing ring + correct routing** — SHA-1 160-bit identifier
   space, `find_successor` / `find_predecessor` / `closest_preceding_finger`
   exactly per the Chord paper, verified byte-for-byte against the paper's
   published 3-bit worked example.
2. **Finger tables giving genuine `O(log N)` lookups** — every node
   maintains `m` finger entries (`fix_fingers` refreshing them over time);
   lookups from an arbitrary node measurably take `O(log N)` hops, not
   `O(N)`, verified by counting real inter-process RPC hops across cluster
   sizes and checking the bound.
3. **Join + stabilization protocol** — nodes join the ring at an arbitrary
   point and reach correct sorted successor/predecessor order via the
   background `stabilize`/`notify` protocol regardless of join order or
   timing, verified by joining nodes in randomized orders and waiting for
   convergence.
4. **Fault-tolerant replication via successor lists** — every node
   replicates its keys onto its `r` successors; killing a node (real
   process kill, not a clean shutdown) never loses data — a `get` right
   after the kill still returns the correct value from a replica, and the
   ring self-heals (finger tables and successor pointers repair themselves)
   within a bounded number of stabilization rounds.

**Stretch (2+):**

5. **Real multi-process cluster over real TCP** — each node is an
   independent OS process (`node_process.py`) with its own socket; the
   CLI's `cluster start` spawns real subprocesses and joins them into one
   ring; `cli.py kill` sends a real `SIGKILL` to a real node process.
6. **Interactive HTML ring visualizer** — a self-contained, dependency-free
   HTML/Canvas page (no build step) that renders the ring as a literal
   circle with nodes placed by identifier, draws each node's finger table
   as chords across the circle, and animates a captured lookup trace
   hopping node-to-node to its answer.
