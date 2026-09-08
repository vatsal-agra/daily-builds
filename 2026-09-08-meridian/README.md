# Meridian

A from-scratch implementation of **Kademlia**, the XOR-metric peer-to-peer
distributed hash table behind BitTorrent's trackerless DHT, IPFS/libp2p, and
Ethereum node discovery — running inside a deterministic, seeded network
simulator with latency, packet loss, and node churn, topped with a
content-addressed file store.

**Status: Phase 2 (core build) complete.** All four required features are
implemented and passing 104 automated tests. See [`PLAN.md`](./PLAN.md) for
the full architecture and feature list.

## Try it now

```
python3 -m meridian.cli demo --nodes 30 --seed 7
```

Runs a full scripted walkthrough: bootstraps a 30-node swarm, runs an
iterative lookup verified against a brute-force oracle, stores a value on
one node and fetches it from a different one, survives a partial replica
outage, then uploads and downloads a real file through the DHT (surviving
a crashed chunk holder along the way).

```
python3 -m unittest discover -s tests
```

Runs the full test suite (104 tests as of this commit).

## What's implemented so far

1. **XOR-metric k-bucket routing table** (`meridian/routing.py`) — 160
   buckets, k=20 contacts each, real "ping the least-recently-seen contact
   before evicting it" eviction with a replacement cache.
2. **Iterative FIND_NODE / FIND_VALUE lookup** (`meridian/dht.py`) — the
   round-based alpha=3 lookup algorithm, run over a real simulated network
   with latency and loss, verified against a brute-force oracle in
   `tests/test_lookup.py`.
3. **STORE with replication, TTL, and republishing** — values are pushed to
   the k nodes closest to their key, expire on a TTL, and are kept alive by
   periodic republishing from both the original publisher and every replica
   holder.
4. **Deterministic churn simulation** (`meridian/simulator.py`,
   `meridian/network.py`) — a seeded discrete-event simulator with staged
   joins, graceful leaves, and random crash churn; the same seed reproduces
   a run byte-for-byte.

Also already built and tested: a content-addressed file store
(`meridian/filestore.py`) on top of the DHT (chunking, manifests, SHA-256
integrity verification, cross-node retrieval surviving a crashed chunk
holder) — this is stretch feature #6 from the plan, pulled forward because
the file store and the KV engine share the same put/get plumbing.

Still to come: the interactive HTML replay visualizer (stretch #5), the
adversarial review pass, and final polish.

Remaining work will update this section as each phase lands.
