"""
network.py — a deterministic, seeded, adversarial network simulator.

This is a discrete-event simulation (a priority queue of `(deliver_tick,
seq, message)` events) with no threads, no sockets, and no wall-clock — the
same design idea as this repo's Raft simulator (Quorum, 2026-06-15): given
a seed, a run replays byte-for-byte, so any convergence failure it finds is
100% reproducible by re-running the same seed.

It models four independent kinds of chaos:
  * latency   — every message takes a random number of ticks to arrive
  * reordering — messages sent close together can and do arrive out of order
                (this falls out naturally from randomized per-message latency)
  * duplication — a message is randomly delivered twice
  * loss       — a message is randomly dropped and never arrives at all
  * partition  — while two sites are partitioned, messages between them are
                held (not lost) and released with fresh latency once healed

A CRDT only promises convergence for ops that are *eventually delivered* —
permanent loss of an update is a transport-layer failure no data structure
can paper over. So `drop_prob` models a genuinely lossy point-to-point
link, and `Simulation.run` compensates for it with periodic anti-entropy
gossip rounds (each site periodically pulls whatever ops a random peer has
that it doesn't), exactly like real CRDT deployments (Yjs providers,
Automerge sync, Riak read-repair) layer a reliable-eventually-delivered
broadcast on top of an unreliable transport. That combination — not the
raw point-to-point link — is what the convergence proof relies on.
"""

import heapq
import random

from crdt.site import Site


class Network:
    def __init__(self, seed, latency_range=(1, 6), dup_prob=0.08, drop_prob=0.1):
        self.rng = random.Random(seed)
        self.latency_range = latency_range
        self.dup_prob = dup_prob
        self.drop_prob = drop_prob
        self.tick = 0
        self._seq = 0
        self._heap = []            # (deliver_tick, seq, from_id, to_id, payload)
        self._partitions = set()   # frozenset({a, b}) pairs currently split
        self._held = []            # messages queued behind an active partition

    # ---- partition control -----------------------------------------------

    def partition(self, site_a, site_b):
        self._partitions.add(frozenset((site_a, site_b)))

    def heal(self, site_a, site_b):
        pair = frozenset((site_a, site_b))
        self._partitions.discard(pair)
        still_held = []
        for (a, b, payload) in self._held:
            if frozenset((a, b)) == pair:
                self._schedule(a, b, payload)
            else:
                still_held.append((a, b, payload))
        self._held = still_held

    def is_partitioned(self, a, b):
        return frozenset((a, b)) in self._partitions

    # ---- sending -----------------------------------------------------------

    def send(self, from_id, to_id, payload):
        if self.is_partitioned(from_id, to_id):
            self._held.append((from_id, to_id, payload))
            return
        if self.rng.random() < self.drop_prob:
            return  # genuinely, permanently lost
        self._schedule(from_id, to_id, payload)
        if self.rng.random() < self.dup_prob:
            self._schedule(from_id, to_id, payload)  # duplicate delivery

    def _schedule(self, from_id, to_id, payload):
        lo, hi = self.latency_range
        delay = self.rng.randint(lo, hi)
        self._seq += 1
        heapq.heappush(self._heap, (self.tick + delay, self._seq, from_id, to_id, payload))

    # ---- draining ------------------------------------------------------------

    def advance(self, ticks=1):
        """Advance the clock by `ticks`, returning every (to_id, payload)
        delivered along the way."""
        delivered = []
        target = self.tick + ticks
        while self._heap and self._heap[0][0] <= target:
            deliver_tick, _, _from_id, to_id, payload = heapq.heappop(self._heap)
            delivered.append((to_id, payload))
        self.tick = target
        return delivered

    def pending_count(self):
        return len(self._heap) + len(self._held)


class Simulation:
    """Drives N `Site` replicas through randomized concurrent edits over a
    `Network`, plus periodic anti-entropy gossip, and can report whether
    they converge."""

    def __init__(self, seed, num_sites=4, gossip_every=8):
        if num_sites < 2:
            raise ValueError(
                f"Simulation needs at least 2 sites to simulate anything (got {num_sites}). "
                "Convergence between replicas is meaningless with fewer than two replicas."
            )
        self.seed = seed
        self.rng = random.Random(seed ^ 0xB1AAD)
        self.net = Network(seed)
        self.site_ids = [chr(ord("A") + i) for i in range(num_sites)]
        self.sites = {sid: Site(sid) for sid in self.site_ids}
        self.gossip_every = gossip_every
        self.history = []  # human-readable log of what happened, for reports

    def _broadcast(self, from_id, op):
        for to_id in self.site_ids:
            if to_id != from_id:
                self.net.send(from_id, to_id, ("op", op))

    def random_edit(self, site_id):
        s = self.sites[site_id]
        length = s.doc.visible_length()
        if length == 0 or self.rng.random() < 0.75:
            idx = self.rng.randint(0, length)
            ch = self.rng.choice("abcdefghij")
            op = s.type_insert(idx, ch)
            self.history.append(f"t={self.net.tick} {site_id} insert {ch!r} @ {idx}")
        else:
            idx = self.rng.randint(0, length - 1)
            op = s.type_delete(idx)
            self.history.append(f"t={self.net.tick} {site_id} delete @ {idx}")
        self._broadcast(site_id, op)
        return op

    def run(self, num_ops, settle_ticks=40):
        """Issue `num_ops` random edits at random sites over time, running
        periodic gossip, then let the network fully drain. Returns a dict
        with the final per-site text and whether they converged."""
        op_ticks = sorted(self.rng.randint(0, num_ops * 3) for _ in range(num_ops))
        next_gossip = self.gossip_every
        op_i = 0
        end_tick = (op_ticks[-1] if op_ticks else 0) + settle_ticks

        while self.net.tick < end_tick or self.net.pending_count() > 0:
            # issue any ops scheduled for "now"
            while op_i < len(op_ticks) and op_ticks[op_i] <= self.net.tick:
                sid = self.rng.choice(self.site_ids)
                self.random_edit(sid)
                op_i += 1
            if self.net.tick >= next_gossip:
                self._gossip_two_way()
                next_gossip = self.net.tick + self.gossip_every
            delivered = self.net.advance(1)
            for to_id, payload in delivered:
                self._deliver_full(to_id, payload)
            if self.net.tick > end_tick + 500:
                break  # safety valve against a runaway loop

        texts = {sid: s.text() for sid, s in self.sites.items()}
        settled = all(s.is_settled() for s in self.sites.values())
        converged = settled and len(set(texts.values())) == 1
        return {
            "texts": texts,
            "settled": settled,
            "converged": converged,
            "ticks": self.net.tick,
            "history": self.history,
        }

    def _gossip_two_way(self):
        """Each site asks a random peer for whatever ops it's missing.
        This is a direct in-process pull (no separate request/response
        network hop) — it still goes through `Network.send` per resulting
        op, so gossiped ops are just as subject to latency/loss/duplication
        as directly-broadcast ones."""
        for sid in self.site_ids:
            peer_id = self.rng.choice([p for p in self.site_ids if p != sid])
            site, peer = self.sites[sid], self.sites[peer_id]
            for op in peer.missing_ops_for(site.applied_ids):
                self.net.send(peer_id, sid, ("op", op))

    def _deliver_full(self, to_id, payload):
        kind, body = payload
        if kind != "op":
            return
        site = self.sites[to_id]
        if site._try_apply(body):
            site._drain_pending()
        else:
            site.buffer(body)
