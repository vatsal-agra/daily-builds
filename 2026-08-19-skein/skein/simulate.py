"""Orchestrates N Sites talking over a SimNetwork.

Also keeps `all_ops`: the complete list of every op any site has ever
locally produced, in the order Python actually called type_at/delete_at
— which is always a causally valid order (a site can only ever
reference characters already present in its own local state), even
though the real sites receive those same ops through the network in a
totally different, chaos-scrambled order. `convergence.py` replays
`all_ops` through the independent OracleRGA to get a ground-truth
answer to check every site's chaos-scrambled result against.
"""

from __future__ import annotations

import random
from typing import Dict, List, Optional

from .network import SimNetwork
from .site import Site


class Simulation:
    def __init__(self, site_ids: List[str], seed: int = 0, latency_range=(1, 3), drop_prob: float = 0.0, dup_prob: float = 0.0):
        self.sites: Dict[str, Site] = {sid: Site(sid) for sid in site_ids}
        self.network = SimNetwork(
            site_ids=list(site_ids), seed=seed, latency_range=latency_range, drop_prob=drop_prob, dup_prob=dup_prob
        )
        self.all_ops: List[object] = []
        self.rng = random.Random(seed ^ 0x5EED)  # separate stream from the network's own rng

    # -- edits ------------------------------------------------------------

    def type_at(self, site_id: str, pos: int, char: str):
        op = self.sites[site_id].type_at(pos, char)
        self.all_ops.append(op)
        self.network.send(site_id, op)
        return op

    def type_str(self, site_id: str, pos: int, text: str):
        ops = []
        for offset, ch in enumerate(text):
            ops.append(self.type_at(site_id, pos + offset, ch))
        return ops

    def delete_at(self, site_id: str, pos: int):
        op = self.sites[site_id].delete_at(pos)
        self.all_ops.append(op)
        self.network.send(site_id, op)
        return op

    # -- network control ----------------------------------------------------

    def partition(self, site_id: str) -> None:
        self.network.partition(site_id)

    def heal(self, site_id: str) -> None:
        """Reconnect `site_id` and run a full anti-entropy resync: every
        site (not just the one reconnecting) gets resent the complete op
        history. That covers both directions a real partition breaks —
        what `site_id` missed from everyone else, *and* what `site_id`
        itself produced while cut off, which the network dropped outright
        rather than queuing (see SimNetwork.send) and so no one else has
        ever seen yet. Idempotent apply means resending ops a site
        already has is harmless — this is not "cheating," it's exactly
        what a real system's reconciliation/gossip round does."""
        self.network.heal(site_id)
        for sid in self.sites:
            self.network.resync(sid, list(self.all_ops))

    def heal_all(self) -> None:
        for sid in list(self.sites):
            self.heal(sid)

    def step(self) -> int:
        """Advance the network one tick, delivering any ready messages.
        Returns how many messages were delivered."""
        delivered = self.network.step()
        for dest, op in delivered:
            self.sites[dest].receive(op)
        return len(delivered)

    def drain(self) -> int:
        """Run until the network is fully empty. Returns total messages
        delivered."""
        delivered = self.network.drain()
        for dest, op in delivered:
            self.sites[dest].receive(op)
        return len(delivered)

    # -- convenience ----------------------------------------------------------

    def texts(self) -> Dict[str, str]:
        return {sid: s.text for sid, s in self.sites.items()}

    def converged(self) -> bool:
        texts = list(self.texts().values())
        if any(self.sites[sid].has_pending() for sid in self.sites):
            return False
        return len(set(texts)) <= 1

    def random_edit(self, site_id: Optional[str] = None) -> object:
        """Perform one random local edit (insert or, if there's text to
        delete, sometimes delete) at a random site — used by the chaos
        fuzzer. Returns the op produced."""
        site_id = site_id or self.rng.choice(list(self.sites))
        site = self.sites[site_id]
        n = len(site.text)
        if n > 0 and self.rng.random() < 0.3:
            return self.delete_at(site_id, self.rng.randrange(n))
        pos = self.rng.randint(0, n)
        char = self.rng.choice("abcdefghijklmnopqrstuvwxyz ")
        return self.type_at(site_id, pos, char)
