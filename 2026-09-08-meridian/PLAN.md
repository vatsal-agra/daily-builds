# Meridian — a from-scratch Kademlia distributed hash table

## Concept

A real implementation of **Kademlia**, the XOR-metric peer-to-peer DHT that
underlies BitTorrent's trackerless "mainline DHT", IPFS/libp2p, Ethereum's
node discovery protocol, and I2P — built from scratch and run inside a
deterministic, seeded network simulator with realistic latency, packet loss,
and node churn. On top of the raw DHT sits a small **content-addressed file
store**: a file is chunked, hashed, and its chunks are scattered across the
simulated network; retrieval happens from a *different* node than the one
that uploaded it, proving the data really did move through the network
rather than just living in one process's memory.

## Why this is interesting (and why it's a genuinely new domain for this repo)

Every prior "from scratch" build in this repo's history has been one of a
few well-worn shapes: a language runtime or VM (bytecode VMs, a WASM
interpreter, an x86-64 JIT, eight-plus transformer LLMs), a leader-based
consensus protocol (Quorum's Raft — one elected leader, a replicated log,
majority quorums), a solved/fully-observable game (Gambit's chess), or a
physically-simulated but still single-agent-perspective system (Beacon's
SLAM, Silicon's CPU pipeline). **Kademlia is a different kind of hard
problem: fully decentralized coordination with no leader, no global view,
and no fixed membership.** Peers only ever know a tiny slice of the network
(their own k-buckets), yet the XOR-metric routing structure guarantees any
lookup converges toward the target in O(log n) hops from *any* starting
point, and the network self-heals as nodes join and crash — properties that
have to emerge from purely local rules, not be assumed. It's the mechanism
behind real, running, adversarial internet-scale networks (BitTorrent's DHT
alone routes for tens of millions of peers), and it has never been touched
here.

## Architecture

```
meridian/
  nodeid.py     160-bit NodeID space, XOR distance, common-prefix-length
  routing.py    k-bucket routing table (bucket-per-prefix-length, k=20,
                 LRU + stale-contact eviction via a live ping)
  network.py    deterministic discrete-event simulated network: per-link
                 latency (jittered), packet loss, in-flight message queue,
                 seeded RNG so a run is 100% reproducible
  protocol.py   RPC message types (PING, STORE, FIND_NODE, FIND_VALUE) and
                 the wire-level request/response/timeout handling
  dht.py        DHTNode: local key/value store with TTL, the iterative
                 lookup algorithm (alpha=3 concurrent RPCs, shrinking
                 candidate set, correct termination), STORE replication to
                 the k closest nodes, periodic bucket refresh + key
                 republishing
  simulator.py  orchestrates a whole simulated swarm: bootstrap/join,
                 graceful leave, random crash churn, a scripted scenario
                 runner that records every event to a trace log
  filestore.py  chunks a file into fixed-size content-addressed blocks
                 (SHA-256 keys), builds a manifest, PUTs/GETs it through a
                 DHTNode's public get/put API, verifies integrity on
                 reassembly
  cli.py        `meridian` command-line tool: run/demo/put/get/viz/bench
tests/          unit + property/fuzz tests, an oracle-based correctness
                 checker for lookup (iterative result vs. brute-force true
                 k-nearest over every live node)
viz/            self-contained HTML/Canvas/JS replay visualizer: XOR
                 keyspace ring, live network graph, hop-by-hop lookup
                 animation, scrubbable timeline
demo.sh         runs the full test suite + a scripted CLI walkthrough of
                 every feature + a headless-Chromium check of the visualizer
```

No third-party dependencies for the engine (pure Python 3 stdlib —
`hashlib`, `heapq`, `random`, `dataclasses`, `argparse`, `unittest`). The
visualizer is a single static HTML file with inline CSS/JS and no build
step; Playwright/Chromium (already installed in this environment) is used
only for a headless console-error smoke test of that page.

## Feature list

**Required (core, must work end-to-end):**

1. **XOR-metric k-bucket routing table.** 160-bit node IDs, XOR distance as
   the metric, one bucket per common-prefix-length bucket (0..159), k=20
   contacts per bucket, correct insertion/lookup/eviction — including the
   real Kademlia rule that a *full* bucket doesn't just evict the oldest
   contact, it pings it first and only replaces it if the ping fails
   (long-lived nodes are trusted over new ones — this is the property that
   makes Kademlia resistant to certain flooding attacks).

2. **Iterative FIND_NODE / FIND_VALUE lookup.** The real Kademlia lookup
   algorithm: query `alpha=3` of the closest-known contacts in parallel,
   fold newly-discovered contacts into a shrinking candidate shortlist,
   keep going until the `k` closest contacts stop improving, running over
   the simulated network with real per-message latency and loss (not an
   in-memory shortcut).

3. **STORE with replication, TTL expiration, and republishing.** A stored
   key/value is pushed to the k nodes closest to the key (found via a real
   lookup), each replica expires after a TTL, and both the original
   publisher and the nodes holding a replica periodically republish it —
   so data measurably survives nodes coming and going.

4. **Deterministic network simulation with churn.** A seeded discrete-event
   simulator drives a swarm of dozens of nodes: staged bootstrap joins via
   a known contact, periodic bucket-refresh lookups, graceful leaves, and
   random crash churn — same seed reproduces the identical run byte-for-
   byte, so any bug found is 100% reproducible.

**Stretch:**

5. **Interactive HTML/Canvas replay visualizer.** Renders the XOR keyspace
   as a ring with nodes placed by ID, a live network graph, and a
   scrubbable timeline replaying a recorded simulation trace: watch a
   lookup's hop-by-hop path converge on its target, watch replicas spread
   on a STORE, watch the routing table reshape itself as nodes join/leave.

6. **Content-addressed file store on top of the DHT.** Chunk a file into
   fixed-size blocks, key each chunk by its SHA-256 hash, store a manifest
   listing the chunk hashes, then retrieve and reassemble the file
   *starting the GET from a different node than the one that ran the PUT*
   — including retrieving successfully after the chunk's original storing
   node has crashed, by falling back to a live replica — with end-to-end
   hash verification proving the bytes that come back are exactly the
   bytes that went in.
