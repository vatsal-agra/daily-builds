# Meridian

A from-scratch implementation of the **Chord distributed hash table**
protocol (Stoica et al., SIGCOMM 2001): consistent hashing over a SHA-1
ring, `O(log N)` lookups via finger tables, self-healing join/stabilization,
and crash fault tolerance via successor-list replication — running as real
independent OS processes talking real TCP, not threads in one process.

**Status: Phase 1 (plan) complete.** See [`PLAN.md`](PLAN.md) for the full
architecture and feature list. Implementation in progress — this README
will be filled in with run instructions, the full feature list, and
verification results as each phase completes.
