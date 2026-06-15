# Quorum

A deterministic **Raft consensus simulator** with an adversarial network, fault
injection, and machine-checked safety invariants. Daily build, 2026-06-15.

> Status: **Phase 4 — stretch + polish complete.** All 4 required features plus
> all 3 stretch features work end-to-end. Verification suite next.

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

## Stretch features (all three done)
5. **Linearizability checker** — Wing & Gong search verifies the committed client
   history is linearizable against a sequential KV spec (catches stale reads /
   split-brain writes). Validated against known-bad histories.
6. **Live ASCII dashboard** — `python3 -m quorum.cli dashboard` animates the
   cluster: per-node role, term, log bar (committed vs pending), commit index,
   partition group, and a rolling fault feed.
7. **Log compaction / snapshots** — nodes auto-compact their logs into snapshots;
   a far-behind or restarted follower is caught up via `InstallSnapshot`.
   Exercised continuously under chaos.

See [PLAN.md](./PLAN.md) for architecture and [REVIEW.md](./REVIEW.md) for the
adversarial review.
