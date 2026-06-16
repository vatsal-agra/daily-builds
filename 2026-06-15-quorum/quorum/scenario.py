"""Scripted scenarios: a tiny timed-action format and a runner.

A scenario is a list of ``(tick, action)`` pairs. Actions are simple tuples that
the runner interprets against a Cluster. This lets us encode the classic Raft
"hard cases" deterministically and assert that safety holds.

Actions:
  ("propose", command)            submit a client command to the current leader
  ("crash", node_id)              crash a node
  ("restart", node_id)            restart a crashed node
  ("partition", [set, set, ...])  install a network partition
  ("heal",)                       remove all partitions
  ("isolate_leader",)             partition the current leader into a minority
"""

from __future__ import annotations

from .cluster import Cluster
from .raft import Config, Role
from .network import NetConfig
from .linearizer import LinearizabilityChecker, history_from_ops
from .invariants import SafetyViolation


def _isolate_leader(cluster: Cluster):
    leader = cluster.leader()
    if leader is None:
        return
    ids = sorted(cluster.nodes)
    others = [i for i in ids if i != leader]
    minority = {leader, others[0]}
    majority = set(ids) - minority
    cluster.partition([minority, majority])


def run_scenario(name: str, verbose: bool = False) -> dict:
    spec = SCENARIOS[name]
    cluster = Cluster(
        n=spec.get("n", 5),
        seed=spec.get("seed", 0),
        config=Config(election_min=8, election_max=16, heartbeat_interval=1),
        net_config=NetConfig(latency_min=1, latency_max=3,
                             loss_prob=spec.get("loss", 0.0),
                             dup_prob=spec.get("dup", 0.0)),
    )
    actions = sorted(spec["actions"], key=lambda x: x[0])
    total_ticks = spec.get("ticks", 800)
    ai = 0
    violation = None
    safety_ok = True

    if verbose:
        print(f"Scenario '{name}': {spec.get('desc','')}")

    try:
        for t in range(1, total_ticks + 1):
            while ai < len(actions) and actions[ai][0] == t:
                _, action = actions[ai]
                _apply_action(cluster, action, verbose)
                ai += 1
            cluster.step()
        # settle
        for i in list(cluster.nodes):
            if i not in cluster.alive:
                cluster.restart(i)
        settled = cluster.run_until_quiescent(max_ticks=600)
    except SafetyViolation as e:
        safety_ok = False
        violation = str(e)
        settled = False

    linearizable = True
    if safety_ok:
        checker = LinearizabilityChecker()
        hist = history_from_ops(cluster.committed_history())
        linearizable = checker.check(hist)
        if not linearizable:
            violation = "non-linearizable history"

    if verbose:
        leader = cluster.leader()
        print(f"  final leader = {leader}, "
              f"kv = {cluster.kv_snapshot(leader) if leader is not None else '{}'}")
        print(f"  settled = {settled}, ops = "
              f"{sum(1 for o in cluster.ops if o.committed)}/{len(cluster.ops)}")

    return {
        "safety_ok": safety_ok,
        "linearizable": linearizable,
        "violation": violation,
        "settled": settled,
        "ops_total": len(cluster.ops),
        "ops_committed": sum(1 for o in cluster.ops if o.committed),
    }


def _apply_action(cluster: Cluster, action, verbose):
    kind = action[0]
    if kind == "propose":
        op = cluster.client_request(action[1])
        if verbose:
            ok = "accepted" if op else "no leader (dropped)"
            print(f"  t={cluster.time}: propose {action[1]} -> {ok}")
    elif kind == "crash":
        cluster.crash(action[1])
        if verbose:
            print(f"  t={cluster.time}: crash node {action[1]}")
    elif kind == "restart":
        cluster.restart(action[1])
        if verbose:
            print(f"  t={cluster.time}: restart node {action[1]}")
    elif kind == "partition":
        cluster.partition([set(g) for g in action[1]])
        if verbose:
            print(f"  t={cluster.time}: partition {action[1]}")
    elif kind == "heal":
        cluster.heal()
        if verbose:
            print(f"  t={cluster.time}: heal network")
    elif kind == "isolate_leader":
        _isolate_leader(cluster)
        if verbose:
            print(f"  t={cluster.time}: isolate current leader")


# --------------------------------------------------------------------------- #
# Built-in scenarios — the classic Raft hard cases.
# --------------------------------------------------------------------------- #
SCENARIOS = {
    "split_brain": {
        "desc": "Old leader isolated in a minority keeps accepting writes that "
                "must never commit; majority elects a new leader.",
        "n": 5, "seed": 1, "ticks": 700,
        "actions": [
            (30, ("propose", ("put", "a", 1))),
            (50, ("propose", ("put", "b", 2))),
            (80, ("isolate_leader",)),
            (90, ("propose", ("put", "ghost", 666))),   # to stale leader; must abort
            (120, ("propose", ("put", "ghost", 667))),
            (160, ("propose", ("put", "c", 3))),          # to new leader; must commit
            (220, ("propose", ("put", "d", 4))),
            (300, ("heal",)),
            (360, ("propose", ("put", "e", 5))),
        ],
    },
    "leader_crash": {
        "desc": "Leader crashes mid-stream; a new leader takes over and writes "
                "continue, then the old leader rejoins.",
        "n": 5, "seed": 2, "ticks": 700,
        "actions": [
            (30, ("propose", ("put", "a", 1))),
            (60, ("crash", 0)), (60, ("crash", 1)),   # may include the leader
            (130, ("propose", ("put", "b", 2))),
            (180, ("propose", ("put", "c", 3))),
            (240, ("restart", 0)), (260, ("restart", 1)),
            (320, ("propose", ("put", "d", 4))),
        ],
    },
    "rolling_restart": {
        "desc": "Rolling restart: each node crashes and restarts in turn while a "
                "steady stream of writes continues.",
        "n": 5, "seed": 3, "ticks": 900,
        "actions": [
            (20, ("propose", ("put", "k", 0))),
            (40, ("crash", 0)), (110, ("restart", 0)),
            (140, ("crash", 1)), (210, ("restart", 1)),
            (240, ("crash", 2)), (310, ("restart", 2)),
            (340, ("crash", 3)), (410, ("restart", 3)),
            (440, ("crash", 4)), (510, ("restart", 4)),
            (300, ("propose", ("put", "k", 1))),
            (450, ("propose", ("put", "k", 2))),
            (550, ("propose", ("put", "k", 3))),
        ],
    },
    "flapping_partition": {
        "desc": "Network partition flaps open and closed repeatedly under write "
                "load with message loss.",
        "n": 5, "seed": 4, "ticks": 900, "loss": 0.08, "dup": 0.05,
        "actions": [
            (30, ("propose", ("put", "a", 1))),
            (80, ("partition", [{0, 1}, {2, 3, 4}])),
            (120, ("propose", ("put", "b", 2))),
            (160, ("heal",)),
            (200, ("partition", [{0, 1, 2}, {3, 4}])),
            (260, ("propose", ("put", "c", 3))),
            (300, ("heal",)),
            (340, ("partition", [{0}, {1, 2}, {3, 4}])),
            (420, ("heal",)),
            (460, ("propose", ("put", "d", 4))),
        ],
    },
}
