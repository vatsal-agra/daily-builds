# Meridian

A from-scratch implementation of the **Chord distributed hash table**
protocol (Stoica, Morris, Karger, Kaashoek & Balakrishnan, SIGCOMM 2001):
consistent hashing over a SHA-1 ring, `O(log N)` lookups via finger
tables, self-healing join/stabilization, and crash fault tolerance via
successor-list replication — running as real independent OS processes
talking real TCP sockets, not threads sharing memory in one process.

It is a genuinely new domain for this repo's dense "from-scratch systems"
history: every prior distributed build here picked a different
coordination shape — Raft's leader-and-vote (Quorum), a leaderless CRDT
with no scarcity (Concord), Nakamoto consensus among mutually distrusting
peers (Vein), an unstructured swarm with a central tracker (Swarm) — but
none has been a *structured* peer-to-peer routing overlay: every key and
node hashed into one ring, each node holding only `O(log N)` long-range
pointers, and a lookup from anywhere reaching the right node in `O(log N)`
hops with no node ever knowing the full membership.

## Why this, today

Chord is checkable against real, external ground truth in a way a lot of
distributed protocols aren't from a hobby implementation: the original
paper publishes a fully worked 3-node example with exact finger tables,
so `tests/test_node_unit.py` reproduces it node-for-node and
finger-table-entry-for-entry rather than just trusting this build's own
reasoning about itself. And the interesting engineering problem is a real
one — finger-table routing only works if "successor pointers form one
sorted cycle" holds even while nodes join concurrently and processes get
`SIGKILL`ed — which turned out to be true: this build found and fixed
seven real bugs by actually attacking a live multi-process cluster rather
than only reading the code (see [`REVIEW.md`](REVIEW.md)), several of
which no amount of code review alone would likely have caught (a
readiness check fooled by a stray process squatting a port; a hardcoded
hash width invisible on the default ring size but not on others; a lookup
fallback that occasionally exhausted its retry candidates in a real
timing window that never showed up in synthetic tests until the real
cluster suite ran repeatedly).

## How to run it

```
cd 2026-09-28-meridian

# automated verification
python3 -m unittest discover -s tests   # 26 tests: hashing math, the Chord
                                         # paper's own worked example, and a
                                         # real multi-process cluster (~10s)
./demo.sh                                # end-to-end: every required +
                                          # stretch feature, real SIGKILL,
                                          # real HTML output (10/10 checks)

# operate a real cluster by hand
python3 -m meridian.cli cluster-start 8 --fast     # spawns 8 real node processes, joins them into a ring
python3 -m meridian.cli status                     # dump the live ring topology from every node's own view
python3 -m meridian.cli put mykey "hello"
python3 -m meridian.cli get mykey                  # prints the value and the real hop path taken
python3 -m meridian.cli kill <port>                # SIGKILL a node -- get() still works via replicas
python3 -m meridian.cli trace mykey --out trace.json
python3 -m meridian.visualize trace.json ring.html # open ring.html in a browser
python3 -m meridian.cli cluster-stop
```

A pre-rendered example is checked in — open
[`examples/demo_cluster.html`](examples/demo_cluster.html) directly in a
browser (10-node cluster, one node killed mid-session, 4 captured
lookups); it was generated from [`examples/demo_cluster.json`](examples/demo_cluster.json).

## Feature list

**Required:**

1. **Consistent hashing + correct routing** — real SHA-1 hashing folded
   into a configurable ring width (`--m-bits`, default 32 bits);
   `find_successor`/`closest_preceding_finger` per the paper, verified
   against its own published 3-bit worked example and against real
   clusters up to 20 nodes converging to the exact sorted cycle.
2. **Finger-table-driven `O(log N)` lookups** — measured directly: 15-20
   node real clusters resolve `put`/`get` in 2-5 hops, not the 15-20 a
   linear scan would need.
3. **Join + background stabilization** — nodes join at an arbitrary point
   and the ring converges to correct successor/predecessor order via
   `stabilize`/`notify`, regardless of join order or timing; verified with
   randomized join orders and with 5 new nodes joining an already-populated
   6-node ring (all 40 pre-existing keys survive).
4. **Fault-tolerant replication via successor lists** — every node
   replicates its keys onto its next `r` successors; a real `SIGKILL` of
   the node holding the most primary keys in a 15-node cluster loses zero
   of 30 stored keys, verified immediately after the kill (not after
   waiting for repair), and the ring self-heals to the exact correct cycle
   afterward.

**Stretch:**

5. **Real multi-process cluster over real TCP** — every node
   (`meridian.node_process`) is an independent OS process with its own
   socket; `meridian cluster-start` spawns real subprocesses, `meridian
   kill <port>` sends a real `SIGKILL`.
6. **Interactive HTML ring visualizer** (`meridian.visualize`) — a
   self-contained, dependency-free Canvas page (no build step):
   responsive/device-pixel-ratio-aware, hover tooltips instead of
   permanently-overlapping node labels, a real red-X marker for a killed
   node, live summary stats, and an animated hop-by-hop replay of a
   captured lookup.

## Known limitation (by design, not a bug)

Meridian follows Chord's own consistency model: **eventually consistent,
not linearizable.** Every read of a key that was written once is correct,
including immediately after the node holding it crashes (verified). If a
key were overwritten while replicas are still catching up from a very
recent topology change, a short staleness window is possible — the same
trade-off the real protocol makes. Full reasoning in `REVIEW.md`.

## Where a human could take this next

- **Vector-clock or version-stamped values** to close the eventual-
  consistency staleness window noted above for overwritten keys, turning
  "eventually consistent" into "read-your-writes."
- **A real network instead of localhost** — the protocol has no
  localhost-only assumption baked in; pointing node processes at different
  hosts (and adding basic auth/TLS on the RPC socket) would make this a
  genuine multi-machine deployment, not just a multi-process demo.
- **Kademlia-style parallel lookups** (query several fingers at once
  rather than strictly iteratively) for lower tail latency at large `N`.
- **A real workload on top of the KV layer** — the hard distributed-systems
  part is done; a small file store, a distributed cache with TTLs, or a
  pub/sub layer could all be built as a client of this ring rather than
  needing their own routing logic.
- **Chaos-style property testing** (in the spirit of this repo's own
  Quorum build) — randomized interleavings of joins, kills, and puts,
  checked against a linearizability-style oracle, would stress the eventual-
  consistency edges harder than the scripted scenarios in `tests/`.
