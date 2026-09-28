# Meridian

A from-scratch implementation of the **Chord distributed hash table**
protocol (Stoica et al., SIGCOMM 2001): consistent hashing over a SHA-1
ring, `O(log N)` lookups via finger tables, self-healing join/stabilization,
and crash fault tolerance via successor-list replication — running as real
independent OS processes talking real TCP, not threads in one process.

**Status: Phase 2 (core build) complete.** All 4 required features are
implemented and verified end-to-end against a real 20-process cluster:

- Consistent hashing + correct `find_successor` routing (verified: the ring
  converges to the exact sorted successor/predecessor cycle across all 20
  independently-hashed node processes).
- Finger-table-driven lookups: `get`/`put` on a 20-node ring resolve in
  2-5 hops (`O(log N)` for N=20 is ~4.3), not the 20 hops a linear scan
  would take.
- Join + background stabilization converges every node to correct
  successor/predecessor pointers regardless of join order or timing.
- Successor-list replication survives a real `SIGKILL` of the primary
  owner of live data: every one of 30 stored keys, including all of the
  keys the killed node had been primary for, was still retrievable via a
  replica *immediately* after the kill (0 failures across the run), and
  the ring's pointers self-heal back to a fully correct cycle within a
  couple of stabilization rounds.

Quickstart:

```
cd 2026-09-28-meridian
python3 -m meridian.cli cluster-start 8 --fast     # spawns 8 real node processes, joins them into a ring
python3 -m meridian.cli status                     # dump the live ring topology
python3 -m meridian.cli put mykey "hello"
python3 -m meridian.cli get mykey                  # prints the value and the real hop path taken
python3 -m meridian.cli kill <port>                # SIGKILL a node -- watch get() still work via replicas
python3 -m meridian.cli trace mykey --out trace.json
python3 -m meridian.visualize trace.json ring.html # open ring.html in a browser
python3 -m meridian.cli cluster-stop
```

See [`PLAN.md`](PLAN.md) for the full architecture and feature list.

**Status: Phase 3 (adversarial review) complete.** See
[`REVIEW.md`](REVIEW.md) for the full write-up. Five real bugs were found by
attacking a live multi-process cluster (not just reading the code) and
fixed, including one that would have silently mis-hashed keys on any
non-default ring size, and one where a cluster-start failure was reported
as success because the readiness check could be fooled by an unrelated
process squatting the port. Stretch features and final verification are
still to come.

**Status: Phase 4 (stretch + polish) complete.** Both planned stretch
features were already real as of Phase 2/3 and are now polished:

- **Real multi-process cluster over real TCP** (`meridian cluster-start`) —
  every node is an independent OS process; `meridian kill <port>` sends a
  genuine `SIGKILL`.
- **Interactive HTML ring visualizer** (`meridian.visualize`) — now
  responsive (resizes to the browser window, device-pixel-ratio aware),
  shows a hover tooltip per node instead of permanently-on overlapping ID
  labels, renders a real red-X marker for a killed node (previously the
  trace command silently dropped killed nodes from the payload entirely —
  fixed so the fault-tolerance story is actually visible), shows live
  summary stats (alive/killed/keys-stored), and gracefully handles an empty
  trace file instead of a blank canvas.
- A curated example is checked in at
  [`examples/demo_cluster.json`](examples/demo_cluster.json) /
  [`examples/demo_cluster.html`](examples/demo_cluster.html) — a 10-node
  cluster with one node killed mid-session, open the `.html` file directly
  in a browser.

Polish: `--m-bits`/`--r` are now validated with clear errors; `kill` and
`cluster-start` handle repeat/invalid operator input gracefully instead of
raising raw tracebacks; `cluster-start`'s readiness check now verifies a
real Meridian `ping` response (not just "some TCP listener exists") and
cleans up already-spawned processes if a later node in the batch fails;
every command prints a clear, specific message for the empty-cluster case.

**Status: Phase 5 (verification) complete.** 26 automated tests
(`tests/test_hashing.py`, `tests/test_node_unit.py`,
`tests/test_cluster.py`) plus an end-to-end `./demo.sh` covering every
required and stretch feature against a real multi-process cluster, all
green:

```
python3 -m unittest discover -s tests   # 26 tests, ~10s, no flakiness across repeated runs
./demo.sh                               # 10/10 checks, real cluster, real SIGKILL, real HTML output
```

Writing the fast in-memory unit test suite (`test_node_unit.py`) caught a
6th real bug that the earlier manual/ad-hoc cluster testing in Phases 2-4
had never happened to exercise: `put()` had no fallback when routing
reported an already-dead node as responsible (only `get()` did). Running
the real-cluster suite repeatedly then caught a 7th, rarer one: a
single-node kill could occasionally exhaust the fallback candidate list if
the specific cached successor-list view a lookup happened to consult was
still thin moments after `cluster-start`. Both are fixed and covered by
regression tests; full detail in [`REVIEW.md`](REVIEW.md).
`tests/test_node_unit.py` also reproduces the original Chord paper's own
published 3-bit worked example (Stoica et al., Figures 3-5) node-for-node
and finger-table-entry-for-entry, as an independent, external ground truth
beyond this build's own reasoning about itself.

### Known limitation (by design, not a bug)

Meridian follows Chord's own consistency model: **eventually consistent,
not linearizable.** If a key is written once, every read of it is correct,
including immediately after a node holding it crashes (verified). If a key
were overwritten while replicas are still catching up to a recent topology
change, a very short staleness window is possible — the same trade-off the
real protocol makes. See `REVIEW.md` for the full reasoning.
