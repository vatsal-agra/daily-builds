# Quorum — a deterministic Raft consensus simulator

## Concept
**Quorum** is a from-scratch implementation of the **Raft consensus algorithm**
running inside a **deterministic discrete-event network simulator**. It lets you
spin up a cluster of Raft nodes, drive time forward tick-by-tick, inject faults
(crashes, restarts, network partitions, message loss, duplication, reordering),
and then *prove* — with a machine-checked invariant monitor — that Raft's safety
properties continue to hold no matter how hostile the network gets.

Crucially everything is **deterministic and seeded**: the same seed + scenario
always replays the exact same execution, so a bug found by randomized testing is
100% reproducible. There are no threads, no sockets, no wall-clock time — the
whole cluster is a pure state machine advanced by an event loop, which is what
makes correctness checkable.

## Why it's interesting
Consensus is famously hard to get right; the value here is not "a Raft library"
but a *testbed that catches the subtle bugs*. The interesting engineering is:
- Modeling an asynchronous, adversarial network as a reproducible event queue.
- Encoding Raft's five safety invariants as runtime monitors over the *global*
  state (something a real distributed system can never observe at once, but a
  simulator can).
- A randomized "chaos" driver that hammers the cluster and a linearizability
  checker that confirms committed client operations form a single consistent
  history.

This is deliberately a different domain and shape from prior daily builds
(a procedural world generator and a regex engine): no HTML viz, no parser — it's
distributed-systems + property-based testing, CLI/log-first.

## Architecture
```
quorum/
  raft.py        # Pure Raft node state machine (no I/O): RequestVote,
                 # AppendEntries, terms, log, commit index, leader/follower/
                 # candidate roles, election + heartbeat timers as tick counts.
  network.py     # Deterministic discrete-event simulator: a seeded priority
                 # queue of (deliver_time, msg). Models latency, drops, dup,
                 # reorder, and partitions as a connectivity matrix.
  cluster.py     # Wires N nodes to the network, routes messages, advances
                 # time, applies committed entries to a replicated key/value
                 # state machine, exposes a client API (propose/read).
  invariants.py  # Global safety monitors: Election Safety, Leader Append-Only,
                 # Log Matching, Leader Completeness, State Machine Safety.
  linearizer.py  # Linearizability checker (Wing&Gong search) over the recorded
                 # client operation history against a sequential KV spec.
  faults.py      # Fault-injection scenarios + a randomized chaos generator.
  scenario.py    # Tiny scenario format (list of timed actions) + runner.
  cli.py         # `quorum` CLI: run/chaos/scenario/demo subcommands + a
                 # live ASCII cluster dashboard.
tests/
  test_quorum.py # Full test suite exercising every feature.
demo.sh          # One-shot runnable demo of all features.
```

## Feature list

### Required (core)
1. **Correct Raft core** — leader election, log replication, term/vote rules,
   commit-index advancement, and a replicated key/value state machine. Elects a
   single leader from a quiet cluster and replicates client writes to all nodes.
2. **Deterministic adversarial network** — seeded discrete-event simulator with
   configurable latency, message loss, duplication, reordering, and *network
   partitions* via a connectivity matrix. Same seed ⇒ identical run.
3. **Safety invariant monitor** — runtime checks of Raft's five canonical safety
   properties over global state, raising a precise violation (with the offending
   nodes/indices) the instant any is broken.
4. **Fault injection + chaos driver** — crash/restart nodes, heal/cut partitions,
   and a randomized chaos generator that injects a stream of faults while the
   invariant monitor watches. Survives a fully randomized fault storm.

### Stretch
5. **Linearizability checker** — record every client op (propose/read) with
   call/return windows and verify the committed history is linearizable against a
   sequential KV spec (catches stale reads / split-brain writes).
6. **Live ASCII cluster dashboard** — a terminal animation showing each node's
   role, term, log length, commit index, and in-flight messages as time advances.
7. **Log compaction / snapshots** — snapshot the state machine, truncate the log,
   and bring a lagging/restarted follower up to date via InstallSnapshot.

## Correctness gates
- A quiet 5-node cluster elects exactly one leader and converges in bounded ticks.
- Writes proposed to the leader are committed and identical on all live nodes.
- Under randomized chaos (crashes + partitions + loss) across many seeds, **zero**
  safety-invariant violations and a **linearizable** client history.
- Deterministic replay: rerunning a seed reproduces the byte-identical event log.
```
```
