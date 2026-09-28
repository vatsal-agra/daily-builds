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
Adversarial review, stretch features, and final verification are still to
come.
