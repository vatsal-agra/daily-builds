# Quorum

**A deterministic Raft consensus simulator** — spin up a cluster of Raft nodes
inside a seeded, adversarial discrete-event network, inject crashes, partitions,
and message loss, and *prove* with a machine-checked monitor that Raft's safety
properties hold no matter how hostile the network gets. Fully deterministic: the
same `(seed, scenario)` replays byte-for-byte, so any bug is 100% reproducible.

Pure Python 3 standard library. No dependencies, no threads, no sockets, no
wall-clock time — the whole cluster is a pure state machine advanced one tick at
a time, which is exactly what makes correctness checkable.

```
   t=240  leader=node 2 (term 7)   in-flight=11
   node  role        term  log (commit=█ pending=▒)               cmt
  ★2     LEADER         7  ··████████████████████████████████████  41   ●
   0     follower       7  ··████████████████████████████████████  41   ●
   1     candidate      8  ··██████████████████████▒▒▒▒▒▒▒▒▒▒▒▒▒▒  29   ◧ grp0
```

## What it is
Consensus is famously hard to get right. Quorum's value isn't "a Raft library" —
it's a **testbed that catches the subtle bugs**. It models an asynchronous,
adversarial network as a reproducible event queue, encodes Raft's five safety
invariants as runtime monitors over *global* state (something a real distributed
system can never observe at once, but a simulator can), and confirms that every
committed client operation forms a single linearizable history.

## How to run
Requires only Python 3.9+.

```bash
cd 2026-06-15-quorum

python3 -m quorum.cli demo              # narrated tour of every feature
python3 -m quorum.cli run --seed 5      # healthy cluster: elect + replicate
python3 -m quorum.cli chaos --runs 50   # randomized fault-injection torture test
python3 -m quorum.cli scenario split_brain   # a classic Raft hard case
python3 -m quorum.cli dashboard         # live animated cluster (best in a TTY)

./demo.sh                               # everything end-to-end
python3 -m unittest discover -s tests   # the 27-test verification suite
```

## Features

### Core
1. **Correct Raft engine** (`raft.py`) — leader election with the up-to-date-log
   voting restriction, log replication with the consistency check and
   conflict-based fast backtrack, the current-term commit rule (+ a no-op entry
   on election so prior-term entries commit safely), and the higher-term demotion
   rule. Drives a replicated key/value state machine.
2. **Deterministic adversarial network** (`network.py`) — a seeded discrete-event
   simulator: variable latency (→ reordering), message loss, duplication, crashed
   nodes, and network partitions via a connectivity check evaluated *at delivery
   time* (a message in flight when a partition forms does not cross it).
3. **Safety invariant monitor** (`invariants.py`) — runtime checks of Raft's five
   canonical safety properties (Election Safety, Leader Append-Only, Log Matching,
   Leader Completeness, State Machine Safety) over global state, raising a precise
   violation the instant one breaks.
4. **Fault injection + chaos driver** (`faults.py`, `cluster.py`) — crash/restart
   nodes, cut/heal partitions, and a randomized chaos generator that injects a
   stream of faults while the monitor watches. 100-seed sweeps run clean.

### Stretch (all three shipped)
5. **Linearizability checker** (`linearizer.py`) — a Wing & Gong search verifies
   the committed client history is linearizable against a sequential KV spec,
   catching stale reads and split-brain writes. Validated against known-bad
   histories so the verdict isn't decorative.
6. **Live ASCII dashboard** (`dashboard.py`) — animates the cluster: per-node
   role, term, a log bar (committed vs pending), commit index, partition group,
   and a rolling fault feed.
7. **Log compaction / snapshots** (`raft.py`) — nodes auto-compact their logs
   into snapshots; a far-behind or restarted follower is brought current via
   `InstallSnapshot`. Exercised continuously under chaos.

### Plus
- Four scripted "hard case" scenarios (`scenario.py`): `split_brain`,
  `leader_crash`, `rolling_restart`, `flapping_partition`.
- A polished CLI with input validation and graceful errors.

## How it's verified
- **27-test suite** covering the core, the safety rules (a deterministic
  Figure-8 commit-rule regression, the up-to-date voting restriction), the
  network, faults, scenarios, snapshots, the linearizer, and the CLI.
- **Mutation tests** that deliberately break Raft (remove the voting restriction)
  and confirm the monitor *fires* — proving the checks aren't vacuous.
- **100-seed chaos sweep**: zero safety violations, every history linearizable.

See [REVIEW.md](./REVIEW.md) for the adversarial review (it found and fixed a
real single-node election/commit bug, a snapshot-vs-append-only false positive,
and a test gap where random chaos under-exercised the commit rule).

## Why I chose this today
The two previous daily builds were a procedural world generator and a regex
engine — both Python + single-file HTML visualizers with a parser/automata
flavor. To avoid a close variation I deliberately switched domains to distributed
systems + property-based testing: no HTML, no parser, CLI/log-first. Consensus is
a genuinely hard problem where the interesting work is *catching* the subtle bugs,
which makes a deterministic, invariant-checked simulator a satisfying complete
product rather than a fragment.

## Where a human could take this next
- **Jepsen-style nemeses & model-based exploration:** add clock skew, asymmetric
  partitions, and a DPOR/state-space search that enumerates interleavings instead
  of sampling seeds, to *prove* (not just sample) safety up to a bound.
- **More of the algorithm:** joint-consensus membership changes, pre-vote and
  leadership transfer, read leases / read-index for fast linearizable reads.
- **Liveness checking:** assert progress under eventual synchrony, and measure
  election-storm pathologies and commit latency distributions.
- **Compare protocols:** drop in Multi-Paxos or Viewstamped Replication behind the
  same network + invariant harness and benchmark them head to head.
- **A real adapter:** wire the pure node state machine to actual sockets so the
  exact code that's model-checked here also runs as a real (if toy) KV store.

## Stack
Pure Python 3 standard library (`dataclasses`, `heapq`, `random`, `argparse`,
`unittest`). ~2,350 lines across engine, network, invariants, linearizer,
dashboard, scenarios, CLI, and tests. Zero third-party dependencies.
