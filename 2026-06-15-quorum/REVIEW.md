# Quorum — Adversarial Review (Phase 3)

I attacked my own implementation as a hostile reviewer, hunting for correctness
bugs, vacuous checks, and untested code paths. Every issue below was reproduced,
then fixed, then re-verified.

## Findings & fixes

### F1 — Single-node cluster (n=1) never elected a leader *(real bug)*
A node with no peers became a candidate with one self-vote — already a majority —
but the "did I win?" check only ran when processing a `RequestVoteResp`, which
never arrives with zero peers. The node spun re-electing itself forever.
**Fix:** `_become_candidate` now checks for an immediate majority and promotes
itself to leader on the spot. Verified n=1 elects and commits.

### F2 — Single-node / fresh leader didn't advance commit index *(real bug)*
`_maybe_advance_commit` ran only on receipt of an `AppendEntriesResp`. With no
peers, a single-node leader appended client entries but never committed them
(0/3 committed). **Fix:** the leader also runs `_maybe_advance_commit` in
`tick()`, so a one-node majority and freshly appended entries make progress.
Verified n=1..3 commit fully.

### F3 — Safety monitor was partly vacuous: the current-term commit rule was
under-tested *(test gap — the dangerous one)*
A mutation test that *removed* Raft's current-term commit rule (commit any
majority-replicated index, the classic Figure-8 hazard) was caught by the monitor
on **0 / 30** random chaos seeds — random chaos simply didn't reproduce the
precise Figure-8 interleaving, so this critical safety rule was effectively
untested. By contrast, removing the up-to-date-log *voting* restriction was
caught on 28/30, confirming the monitor itself has teeth.
**Fix:** added a deterministic regression (`test_figure8_commit_rule`) that
constructs the exact Figure-8 log/`matchIndex` state and asserts the leader
*refuses* to commit a prior-term entry sitting on a bare majority, yet commits it
indirectly once a current-term entry reaches a majority. Correct code passes;
the mutated commit rule fails it.

### F4 — Snapshotting tripped a false "Leader Append-Only" violation *(monitor bug)*
The append-only invariant compared raw log *prefixes* and assumed index 1 is
always present. When a leader compacted its log into a snapshot (legitimately
trimming a committed prefix), the visible log shifted and the check fired a false
`LeaderAppendOnly` violation. **Fix:** the invariant is now absolute-index aware —
it compares only entries at indices present in *both* the old and new view, so
trimming a committed prefix is correctly allowed while any real mutation of a
retained entry is still caught. Verified the full InstallSnapshot catch-up path
(a long-crashed follower rejoins and is brought current via a snapshot).

### F5 — Linearizability checker could have been a no-op *(validation)*
A checker that always returns `True` would silently pass everything. I validated
it against a hand-crafted **stale-read** history (a `get` that returns `None`
entirely after a `put(x,1)` committed) — correctly rejected — and against a valid
*concurrent* history where the `get` overlaps the `put` — correctly accepted. So
the verdict is meaningful, not decorative.

### F6 — "Linearizable" verdict on an unsettled run could be inconclusive *(soundness)*
The history fed to the checker excludes aborted/uncommitted ops; this is only
sound if every op reached a definite outcome. **Mitigation/decision:** every
chaos run and scenario ends with a heal-and-settle phase that restarts all nodes,
removes partitions, and runs to quiescence so each op either commits or is
provably overwritten (reaped). All 50 chaos seeds and all 4 scenarios report
`settled=True`; the verification suite asserts this.

## Things I checked that turned out to be correct
- **Idempotent duplicates:** duplicate `RequestVote`/`AppendEntries` don't
  double-count (votes tracked in a set; AppendEntries only truncates on a genuine
  term conflict, so a replayed prefix is a no-op).
- **Stale-leader writes:** a leader stranded in a minority partition keeps
  accepting writes that never commit; they are reaped once a higher-term entry
  commits at their index. The `split_brain` scenario exercises exactly this.
- **Commit cap on heartbeats:** `commitIndex = min(leaderCommit, prevLogIndex +
  len(entries))` never over-commits and still converges, because a caught-up
  follower's `prevLogIndex` equals its last log index.
- **Connectivity at delivery time:** a message in flight when a partition forms is
  dropped at delivery, so partitions are strict.
- **Determinism:** seeded RNG streams (node timers vs. network) replay byte-for-
  byte; same-seed runs produce identical op counts and tick totals.

## Post-fix status
- 100-seed chaos sweep: **0 violations**, all histories linearizable (~0.3 s/seed).
- All 4 scripted scenarios pass and settle.
- Mutation tests confirm the monitor catches both a broken voting restriction and
  a broken commit rule.
