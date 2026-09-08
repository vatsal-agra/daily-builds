# Meridian

A from-scratch implementation of **Kademlia**, the XOR-metric peer-to-peer
distributed hash table behind BitTorrent's trackerless DHT, IPFS/libp2p, and
Ethereum node discovery — running inside a deterministic, seeded network
simulator with latency, packet loss, and node churn, topped with a
content-addressed file store and an interactive HTML replay visualizer.

**Status: feature-complete and verified.** All 4 required features and both
stretch features are implemented, tested (115 unit tests + a 60-seed
multi-feature fuzz sweep), adversarially reviewed (5 real bugs found and
fixed — see [`REVIEW.md`](./REVIEW.md)), and verified end to end via
[`demo.sh`](./demo.sh) (9/9 checks green — see
[`VERIFICATION.md`](./VERIFICATION.md)). See [`PLAN.md`](./PLAN.md) for the
full architecture and feature list.

## Why this, today

Every prior "from scratch" build in this repo has been a language runtime
or VM, a leader-based consensus protocol (Quorum's Raft), a solved/fully-
observable game (Gambit's chess), or a physically-simulated but still
single-agent system (Beacon's SLAM, Silicon's CPU pipeline). Kademlia is a
different kind of hard problem: fully decentralized coordination with no
leader, no global view, and no fixed membership — any two peers can only
ever see a tiny slice of the network (their own routing table), yet the
XOR-metric structure guarantees a lookup converges toward its target in
O(log n) hops from *anywhere*, and the network self-heals as nodes join and
crash. It's the real mechanism behind internet-scale, adversarial,
already-running P2P networks — not a toy.

## Run it

```bash
# scripted end-to-end walkthrough of every feature
python3 -m meridian.cli demo --nodes 30 --seed 7

# a larger swarm simulation with churn, reporting routing/lookup health
python3 -m meridian.cli run --nodes 60 --churn --ticks 8000

# store and retrieve one real file through the DHT
python3 -m meridian.cli filedemo /path/to/some/file

# generate an interactive HTML replay of a simulation
python3 -m meridian.cli viz --html-out viz/replay.html
# then open viz/replay.html in a browser

# full verification: tests + fuzz sweep + every CLI subcommand +
# a headless-Chromium check of the visualizer
bash demo.sh
```

`viz/replay.html` and `viz/trace.json` in this repo are a pre-generated
example — open `viz/replay.html` directly in a browser to see it without
running anything.

## Feature list

**Required (core):**

1. **XOR-metric k-bucket routing table** (`meridian/routing.py`) — 160
   buckets, k=20 contacts each, the real "ping the least-recently-seen
   contact before evicting it" rule with a replacement cache, so long-lived
   contacts are trusted over unverified new ones (this is what makes
   Kademlia resistant to a flood of throwaway nodes).
2. **Iterative FIND_NODE / FIND_VALUE lookup** (`meridian/dht.py`) — the
   round-based alpha=3 lookup algorithm, run over a real simulated network
   with latency and packet loss, verified against a brute-force
   "true k-closest" oracle in `tests/test_lookup.py`.
3. **STORE with replication, TTL, and republishing** — a value is pushed to
   the k nodes closest to its key, expires on a TTL, and is kept alive by
   periodic republishing from both the original publisher *and* every
   replica holder (a real bug where a republishing node forgot to refresh
   its own local copy's expiry is documented and fixed in `REVIEW.md`).
4. **Deterministic churn simulation** (`meridian/simulator.py`,
   `meridian/network.py`) — a seeded discrete-event simulator with staged
   bootstrap joins, graceful leaves, and random crash churn; the same seed
   reproduces a run byte-for-byte, so any bug found is 100% reproducible.

**Stretch (both shipped):**

5. **Interactive HTML/Canvas replay visualizer** (`viz/template.html`,
   `meridian viz --html-out`) — a single self-contained HTML file (no
   server, no build step, no dependencies) rendering the XOR keyspace as a
   ring with every node placed by ID, animated hop-by-hop lookup paths,
   pulsing STORE replication rings, live join/crash highlighting, a
   scrubbable timeline with play/pause, and a clickable event log.
6. **Content-addressed file store** (`meridian/filestore.py`) — chunks a
   file into fixed-size blocks, keys each by its own SHA-256 hash, stores a
   manifest under a key derived from the manifest's own content
   (BitTorrent-magnet-style), then retrieves and reassembles it *from a
   different node than the one that uploaded it* — including surviving a
   crashed chunk-holder via fallback to a live replica — with end-to-end
   hash verification.

## Architecture

```
meridian/
  nodeid.py     160-bit ID space, XOR distance, bucket-index math
  routing.py    k-bucket routing table (LRU + ping-before-evict + replacement cache)
  network.py    deterministic discrete-event simulated network
  protocol.py   the 4 Kademlia RPC message types
  dht.py        DHTNode: iterative lookup, STORE/replication/TTL/republish
  simulator.py  swarm orchestration: bootstrap, churn, the correctness oracle
  filestore.py  chunking / manifests / SHA-256 integrity on top of the DHT
  cli.py        `meridian` CLI: run / demo / filedemo / viz
tests/          115 unit tests (oracle-verified lookup correctness, routing-
                 table eviction fidelity incl. a concurrency-race regression,
                 TTL/republish behavior, file-store round trips and
                 corruption detection, CLI validation, an HTML-viewer test)
scripts/
  fuzz_sweep.py   60-seed randomized multi-feature fuzz sweep
  viz_smoke.js    headless-Chromium smoke test of the visualizer
viz/
  template.html   the visualizer's HTML/CSS/JS (trace JSON gets inlined into a copy)
  replay.html     a pre-generated example (open directly in a browser)
  trace.json      that same example's raw trace data
demo.sh         runs everything above end to end
```

No third-party dependencies anywhere in the engine — pure Python 3 stdlib
(`hashlib`, `heapq`, `random`, `dataclasses`, `argparse`, `unittest`,
`json`). The visualizer is static HTML/CSS/JS with zero dependencies;
Playwright/Chromium (pre-installed in this environment) is used only for a
headless console-error smoke test of it, never by the engine itself.

## Design notes worth knowing

- **Round-based lookup, not a continuously-pipelined one.** The real
  Kademlia lookup keeps up to `alpha` requests in flight continuously,
  topping one up the instant any single one resolves. Meridian instead
  queries `alpha` candidates per round and waits for the whole round to
  resolve before deciding on the next one. This changes nothing about
  correctness (which nodes get queried, what the lookup converges to) or
  about anything observable in a simulation with no real wall-clock benefit
  to squeeze out of tighter interleaving — it only makes the state machine
  much easier to reason about and test deterministically. Documented in
  `dht.py`'s `Lookup` docstring, not hidden.
- **Two different hashes, two different jobs.** DHT keys (both node IDs and
  content keys) live in a 160-bit space addressed via SHA-1 — matching the
  real protocol's own convention (and NodeID's own width) exactly, no
  truncation. File-chunk *integrity* verification uses SHA-256 completely
  independently. Reusing one hash for both "which bucket does this land
  in" and "did I get back the exact bytes I stored" would have been the
  shortcut; using two is the honest version.
- **A crashed node's maintenance timer keeps firing forever** (skipping the
  actual work once dead, but still re-scheduling itself). Documented as a
  deliberate non-fix in `REVIEW.md` — correctness is unaffected, and there's
  no cancellation primitive in this simulator worth building just to avoid
  a trivial number of no-op events on a permanently-dead node.

## Where a human could take this next

- **Real networking.** Swap `network.py`'s in-process simulated delivery for
  actual UDP sockets and the exact same `DHTNode`/`Lookup`/`RoutingTable`
  code would run as a real, internet-routable Kademlia peer — the protocol
  layer was written deliberately network-agnostic.
- **Continuous alpha-pipelining** instead of round-based lookup, if wall-
  clock latency under real network conditions ever mattered (see design
  notes above).
- **Signed/authenticated STORE.** Nothing currently stops a malicious peer
  from overwriting another key's value; real deployments (e.g. BitTorrent's
  mutable DHT items) require a signature the storing nodes verify before
  accepting a STORE.
- **A real k-d-tree or trie-indexed routing table** instead of the
  flatten-and-sort `closest()` — irrelevant at this demo's scale (dozens to
  low hundreds of nodes) but would matter at real internet scale.
- **NAT traversal / rendezvous**, since real P2P deployments can't assume
  every peer is directly reachable the way this simulator does.
