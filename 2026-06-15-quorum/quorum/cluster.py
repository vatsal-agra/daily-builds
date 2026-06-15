"""The cluster: wires N Raft nodes to the deterministic network, advances time,
applies committed entries, and records a client-operation history for the
linearizability checker.
"""

from __future__ import annotations

import random
from dataclasses import dataclass, field
from typing import Optional

from .raft import Node, Config, Role
from .network import Network, NetConfig
from .invariants import SafetyMonitor


@dataclass
class ClientOp:
    op_id: int
    command: tuple
    node: int            # node it was submitted to
    term: int            # term in which it was appended
    index: int           # log index it was appended at
    call_time: int
    return_time: Optional[int] = None
    result: object = None
    committed: bool = False


class Cluster:
    def __init__(self, n: int = 5, seed: int = 0,
                 config: Optional[Config] = None,
                 net_config: Optional[NetConfig] = None):
        self.n = n
        self.rng = random.Random(seed)
        # Independent RNG streams keep node timers and network choices from
        # interfering, while staying fully seeded/deterministic.
        self.net = Network(random.Random(seed ^ 0x9E3779B9), net_config or NetConfig())
        cfg = config or Config()
        self.nodes: dict[int, Node] = {}
        ids = list(range(n))
        for i in ids:
            peers = [j for j in ids if j != i]
            node_rng = random.Random((seed << 8) ^ (i + 1) * 0x1000193)
            self.nodes[i] = Node(i, peers, node_rng, cfg)
        self.alive: set[int] = set(ids)
        self.time = 0
        self.monitor = SafetyMonitor()

        # Client bookkeeping.
        self._next_op_id = 0
        self.ops: list[ClientOp] = []
        self._pending: dict[tuple[int, int], ClientOp] = {}  # (index, term) -> op
        self.last_known_leader: Optional[int] = None

    # ------------------------------------------------------------------ #
    # Fault injection
    # ------------------------------------------------------------------ #
    def crash(self, node_id: int):
        self.alive.discard(node_id)
        self.net.crash(node_id)

    def restart(self, node_id: int):
        self.alive.add(node_id)
        self.net.restart(node_id)
        self.nodes[node_id].on_restart()

    def partition(self, groups: list[set[int]]):
        self.net.set_partitions(groups)

    def heal(self):
        self.net.heal()

    # ------------------------------------------------------------------ #
    # Client API
    # ------------------------------------------------------------------ #
    def leader(self) -> Optional[int]:
        """Return a live node that currently believes it is leader. When several
        do (e.g. a stale leader stranded in a minority partition alongside a fresh
        one), prefer the highest term — the legitimate leader a real client would
        be redirected to. Ties break on lowest id for determinism."""
        cands = [
            nid for nid in sorted(self.alive)
            if self.nodes[nid].role == Role.LEADER
        ]
        if not cands:
            return None
        return max(cands, key=lambda nid: (self.nodes[nid].current_term, -nid))

    def client_request(self, command: tuple) -> Optional[ClientOp]:
        """Submit a command to the current leader. Returns the ClientOp if a
        leader accepted it (appended to its log), else None."""
        leader = self.leader()
        if leader is None:
            return None
        node = self.nodes[leader]
        accepted, index = node.propose(command)
        if not accepted:
            return None
        op = ClientOp(
            op_id=self._next_op_id,
            command=command,
            node=leader,
            term=node.current_term,
            index=index,
            call_time=self.time,
        )
        self._next_op_id += 1
        self.ops.append(op)
        self._pending[(index, op.term)] = op
        self.last_known_leader = leader
        # Replicate immediately for responsiveness.
        for env in node.replicate_now():
            self.net.send(env, self.time)
        return op

    # ------------------------------------------------------------------ #
    # Time
    # ------------------------------------------------------------------ #
    def step(self):
        self.time += 1
        t = self.time

        # 1. Deliver due messages to their destinations.
        due = self.net.deliver_due(t)
        outgoing = []
        for env in due:
            if env.dst not in self.alive:
                continue
            outgoing.extend(self.nodes[env.dst].step(env))

        # 2. Tick every live node.
        for nid in sorted(self.alive):
            outgoing.extend(self.nodes[nid].tick())

        # 3. Send everything produced this step.
        for env in outgoing:
            if env.src in self.alive:
                self.net.send(env, t)

        # 4. Apply committed entries and resolve client ops.
        for nid in sorted(self.alive):
            node = self.nodes[nid]
            for index, entry, result in node.apply_committed():
                self.monitor.record_applied(nid, index, entry.command, result)
                key = (index, entry.term)
                op = self._pending.get(key)
                if op is not None and not op.committed:
                    op.committed = True
                    op.result = result
                    op.return_time = t
                    del self._pending[key]

        # 5. Detect ops whose slot was overwritten by a different entry
        #    (they definitively did not commit).
        self._reap_lost_ops()

        # 6. Global safety check.
        self.monitor.check(self.nodes, self.alive)

    def _reap_lost_ops(self):
        lost = []
        for key, op in self._pending.items():
            index, term = key
            # If some live node has a *different* term committed at this index,
            # this op's entry can never commit.
            for nid in self.alive:
                node = self.nodes[nid]
                if index <= node.commit_index and index <= node.last_log_index():
                    e = node.entry_at(index)
                    if e is not None and e.term != term:
                        lost.append(key)
                        break
        for key in lost:
            op = self._pending.pop(key)
            op.committed = False
            op.return_time = self.time  # failed/aborted at this time

    def run(self, ticks: int):
        for _ in range(ticks):
            self.step()

    def run_until_quiescent(self, max_ticks: int = 400) -> bool:
        """Heal everything and run until all live nodes agree on commit index and
        no messages are in flight. Returns True if it converged."""
        self.heal()
        for _ in range(max_ticks):
            self.step()
            if self._quiescent():
                return True
        return self._quiescent()

    def _quiescent(self):
        live = [self.nodes[i] for i in self.alive]
        if not live:
            return True
        leaders = [n for n in live if n.role == Role.LEADER]
        if len(leaders) != 1:
            return False
        leader = leaders[0]
        # Heartbeats keep messages perpetually in flight, so quiescence is defined
        # by agreement, not an empty network: the leader has committed its whole
        # log and every live node matches it.
        if leader.commit_index != leader.last_log_index():
            return False
        for n in live:
            if n.commit_index != leader.commit_index:
                return False
            if n.last_log_index() != leader.last_log_index():
                return False
        return True

    # ------------------------------------------------------------------ #
    # Introspection
    # ------------------------------------------------------------------ #
    def committed_history(self) -> list[ClientOp]:
        """Ops that definitively committed, in commit order."""
        return sorted(
            [op for op in self.ops if op.committed],
            key=lambda o: (o.index, o.return_time or 0),
        )

    def kv_snapshot(self, node_id: int) -> dict:
        return dict(self.nodes[node_id].kv)

    def summary(self) -> dict:
        leader = self.leader()
        return {
            "time": self.time,
            "leader": leader,
            "term": self.nodes[leader].current_term if leader is not None else None,
            "alive": sorted(self.alive),
            "commit_index": {i: self.nodes[i].commit_index for i in sorted(self.alive)},
            "log_len": {i: self.nodes[i].last_log_index() for i in sorted(self.alive)},
            "ops_total": len(self.ops),
            "ops_committed": sum(1 for o in self.ops if o.committed),
            "net": {
                "sent": self.net.sent,
                "delivered": self.net.delivered,
                "dropped": self.net.dropped,
                "duplicated": self.net.duplicated,
                "in_flight": self.net.in_flight(),
            },
        }
