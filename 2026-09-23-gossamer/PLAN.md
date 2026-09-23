# Gossamer — a from-scratch Dynamo-style distributed key-value store

## Concept

Every distributed-systems build in this repo so far has picked a *coordinated*
consistency model of one flavor or another:

- **Quorum** (Raft) — a single elected leader; strong consistency via a
  crash-fault-tolerant vote.
- **Concord** (RGA CRDT) — no leader, but no real conflict either: every
  concurrent edit merges automatically and deterministically by construction.
- **Vein** (Proof-of-Work blockchain) — no leader, mutually distrusting
  participants, consensus via an expensive public tie-break (most cumulative
  work wins).
- **Swarm** (BitTorrent) — no leader, no vote, no shared mutable state at
  all — peers only ever *transfer* an immutable, hash-verified file.

None of these is the classic "Amazon Dynamo" shape: **many replicas of the
same mutable key, no leader, and writes that can genuinely and permanently
disagree** — two clients write concurrently to different replicas while a
third replica is unreachable, and there is no vote, no chain, and no
CRDT-style auto-merge to paper over it. The system's job is to *detect* that
disagreement structurally (not statistically) and hand it back to the
application as real "sibling" values, while still staying available for
reads and writes through partitions and node failures. That's Gossamer.

It is a genuine implementation of the mechanisms from the 2007 Amazon Dynamo
paper (and its open-source descendants — Riak, Cassandra, Voldemort):
consistent hashing with virtual nodes for partitioning, vector clocks for
causality tracking, a tunable N/R/W quorum protocol, gossip-based failure
detection, hinted handoff, and Merkle-tree anti-entropy repair. Every one of
these is a distinct, real algorithm with its own correctness property to
test against — not a simulation of "a database is eventually consistent,
trust me."

## Architecture

```
gossamer/
  hashring.py    consistent hash ring w/ virtual nodes; ring.replicas_for(key, N)
  vclock.py      VectorClock: increment / compare (EQUAL/DESCENDS/ANCESTOR/CONCURRENT) / merge
  store.py       per-node LocalStore: causal put (accept/reject/sibling) + get (all live siblings)
  merkle.py      Merkle tree over a node's key space, for anti-entropy diffing
  gossip.py      heartbeat gossip + phi-accrual-ish failure suspicion, membership view
  node.py        NodeServer: single physical node — HTTP server wiring together
                 the ring, local store, gossip state, hinted-handoff queue, and
                 anti-entropy loop. Every node is identical code; there is no
                 special coordinator process.
  client.py      Client: picks coordinator = ring.replicas_for(key,N)[0],
                 fans out PUT/GET to replicas over real HTTP, applies quorum
                 rules (ack when >=W / >=R respond), read-repairs stale replicas.
  cluster.py     CLI: spin up a cluster of real `node.py` subprocesses on
                 localhost, wire them to gossip about each other, tear down /
                 kill / revive individual nodes for fault-injection demos.
  dashboard/     self-contained HTML/CSS/vanilla-JS SSE dashboard: ring
                 layout, live node health (alive/suspected/dead), per-request
                 routing, and vector-clock sibling conflicts as they occur.
  cli.py         `gossamer` command: cluster / put / get / status / demo
tests/           unit + property + multi-process integration tests
demo.sh          runs the full test suite + the flagship multi-process demo
```

Every node runs the *exact same* server code — there is no special
"coordinator" binary. Any node can act as coordinator for any request; it's
just "whichever node the client happened to ask first." This is the real
Dynamo shape (peer-to-peer partitioning), not a client/server simplification.

Nodes talk to each other only over real `http.server`-based HTTP, in
separate OS processes (`subprocess.Popen`), exactly like this repo's Vein and
Swarm builds — so failures are *real* process death and *real* connection
refusal, not a flag flipped in shared memory.

## Feature list

### Required (4)

1. **Consistent hashing ring with virtual nodes.** Keys and nodes are hashed
   onto a fixed-size ring (SHA-1-based, no external hashing lib); each
   physical node owns a configurable number of virtual node positions so
   that adding/removing one physical node only reshuffles roughly `1/N` of
   the keyspace rather than everything. `ring.replicas_for(key, N)` walks
   clockwise from the key's hash position and returns the first `N` distinct
   *physical* nodes encountered (skipping repeats from a node's own multiple
   vnodes). Verified against a uniform-load property test and an explicit
   "add a node, measure exactly how many keys moved" test.

2. **Vector clocks for causality + conflict detection.** Each value stored
   under a key carries a vector clock (`{node_id: counter}`). A local store's
   `put` compares the incoming clock against every existing sibling's clock:
   strictly descends an existing value → replace it; is strictly descended by
   an existing value → reject the write as stale; is concurrent with (compares
   neither before nor after) → keep *both* as siblings. This is real causal
   reasoning, not last-write-wins-with-a-timestamp.

3. **Quorum-based reads/writes with read-repair.** A tunable `(N, R, W)`:
   `N` replicas hold each key, a write succeeds once `W` replicas ack, a read
   succeeds once `R` replicas respond and returns the *merged* sibling set
   (vector-clock-deduplicated). Whenever a read sees a replica holding a
   causally stale (or entirely missing) value, it pushes the up-to-date
   value to that replica in the background (read-repair) — over real HTTP
   calls between real node processes, not an in-memory shortcut.

4. **Gossip-based failure detection and membership.** Every node
   periodically gossips its membership table (which nodes it believes are
   alive, and a heartbeat counter for each) to a random peer over real HTTP;
   a node whose heartbeat hasn't advanced within a timeout is marked
   `suspected`, then `dead` after a longer timeout, purely from each node's
   own local view — there is no central membership authority. The
   coordinator consults this local view (not a live ping-on-every-request)
   to skip a suspected-dead replica and pick a substitute for hinted
   handoff, exactly mirroring how Dynamo avoids hammering a downed node on
   every single request.

### Stretch (2+)

5. **Hinted handoff + Merkle-tree anti-entropy repair.** When a preferred
   replica is suspected-dead, the coordinator writes a "hint" to a
   substitute node instead (tagged with the intended owner); when gossip
   reports the original node alive again, hints are flushed to it directly.
   Separately, each node maintains a Merkle tree over its key space so two
   replicas of the same key range can diff their trees and exchange only the
   actually-divergent leaves — proven by measuring that a repair after a
   real downtime window transfers a small fraction of the dataset, not a
   full resync.

6. **Interactive live dashboard.** A self-contained HTML/SSE page (no build
   step) visualizing the hash ring and every node's position on it, live
   node health from each node's own gossip view, per-request replica
   routing as it happens, and vector-clock sibling conflicts (and their
   eventual resolution) rendered as they occur during the flagship demo —
   not a static diagram.

## Why this is interesting

Dynamo-style stores are the one distributed-systems shape this repo hasn't
built, and they have a property none of the others do: **the system is
allowed to permanently and correctly disagree with itself**, and correctness
means detecting that (not hiding it) while never refusing service. Getting
this right requires all four required features working *together* — the
ring decides who to ask, vector clocks decide whether two answers actually
conflict, quorum decides when to declare success, and gossip decides who to
skip — so it's a good test of whether the pieces compose into a real system
rather than four unrelated demos.
