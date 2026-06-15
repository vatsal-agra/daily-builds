# Quorum

A deterministic **Raft consensus simulator** with an adversarial network, fault
injection, and machine-checked safety invariants. Daily build, 2026-06-15.

> Status: **Phase 2 — core build complete.** All 4 required features work
> end-to-end. Adversarial review, stretch features, and polish still to come.

## Quick start
```bash
cd 2026-06-15-quorum
python3 -m quorum.cli demo            # end-to-end tour of every feature
python3 -m quorum.cli run --seed 5    # healthy cluster: elect + replicate
python3 -m quorum.cli chaos --runs 20 # randomized fault-injection torture test
python3 -m quorum.cli scenario split_brain
```

## What works now (required features)
1. **Correct Raft core** — leader election (with the up-to-date-log vote
   restriction), log replication with conflict backtracking, the current-term
   commit rule (+ no-op on election), and a replicated key/value state machine.
2. **Deterministic adversarial network** — seeded discrete-event simulator with
   latency, loss, duplication, reordering, and partitions (connectivity checked
   at delivery time). Same seed replays identically.
3. **Safety invariant monitor** — runtime checks of Raft's five safety
   properties over global state; raises a precise violation the instant one
   breaks.
4. **Fault injection + chaos driver** — crash/restart, partition/heal, and a
   randomized chaos generator. 40+ seeds run clean: zero safety violations,
   fully linearizable client histories.

See [PLAN.md](./PLAN.md) for architecture and the full feature list (including
stretch features still in progress).
