"""Tit-for-tat reciprocal choking: BitTorrent's actual answer to "why would
a selfish, self-interested peer ever bother uploading to anyone else." The
rule is simple and entirely local -- no coordinator, no trust, no
reputation system -- unchoke whoever has been giving *you* the most data
lately, and keep one rotating "optimistic" slot open so a brand-new or
currently-unproven peer still gets an occasional chance to prove itself
(otherwise a fresh peer with zero history could never bootstrap its way
into anyone's good graces).

`compute_unchoke_set` is the pure, stateless algorithm -- independently
testable against synthetic rates, no sockets, no timers. `TitForTatChokePolicy`
wraps it with the real bookkeeping a running node needs (sampling
PieceManager's byte counters over time to get an actual rate, rotating the
optimistic slot on a timer) and plugs directly into Node's existing
`choke_policy` hook from Phase 2 -- the loop mechanics in node.py that
apply whatever set this returns didn't need to change at all.
"""
from __future__ import annotations

import random
import time
from typing import Dict, Optional, Set, Tuple

DEFAULT_MAX_UNCHOKED = 4
DEFAULT_OPTIMISTIC_SLOTS = 1
DEFAULT_OPTIMISTIC_ROTATE_TICKS = 3  # rotate the optimistic slot every N choke-loop ticks


def compute_unchoke_set(
    download_rates: Dict[bytes, float],
    interested_peers: Set[bytes],
    max_unchoked: int = DEFAULT_MAX_UNCHOKED,
    optimistic_slots: int = DEFAULT_OPTIMISTIC_SLOTS,
    previous_optimistic: Optional[bytes] = None,
    rng: random.Random = random,
) -> Tuple[Set[bytes], Optional[bytes]]:
    """Pick who to unchoke this tick.

    `download_rates`: peer_id -> recent bytes/sec this peer has given us.
    Peers with no entry (never downloaded from) are treated as rate 0, not
    excluded -- a rate-0 peer can still win the optimistic slot.
    `interested_peers`: only peers who've told us they want something from
    us are even candidates; unchoking someone with no use for it is a
    wasted slot.

    Returns (unchoked_set, chosen_optimistic_peer_or_None).
    """
    if not interested_peers:
        return set(), None
    regular_slots = max(0, max_unchoked - optimistic_slots)
    # Rank by rate descending; break ties on peer_id so the ranking (and
    # therefore any test asserting on it) is deterministic, not dependent
    # on dict iteration order.
    ranked = sorted(interested_peers, key=lambda p: (-download_rates.get(p, 0.0), p))
    regular = set(ranked[:regular_slots])
    remaining = [p for p in ranked if p not in regular]

    optimistic = None
    if optimistic_slots > 0 and remaining:
        if previous_optimistic in remaining:
            optimistic = previous_optimistic  # keep it stable until the caller decides to rotate
        else:
            optimistic = rng.choice(remaining)

    unchoked = regular | ({optimistic} if optimistic else set())
    return unchoked, optimistic


class TitForTatChokePolicy:
    """A stateful ChokePolicy (matching node.ChokePolicy's call signature)
    that samples PieceManager's byte counters over wall-clock time to
    derive real download rates, then applies compute_unchoke_set. One
    instance per Node -- it's stateful (previous byte snapshot, current
    optimistic peer, tick counter), so it must never be shared between
    nodes."""

    def __init__(
        self,
        max_unchoked: int = DEFAULT_MAX_UNCHOKED,
        optimistic_slots: int = DEFAULT_OPTIMISTIC_SLOTS,
        rotate_every: int = DEFAULT_OPTIMISTIC_ROTATE_TICKS,
        seed: Optional[int] = None,
    ):
        self.max_unchoked = max_unchoked
        self.optimistic_slots = optimistic_slots
        self.rotate_every = rotate_every
        self._rng = random.Random(seed)
        self._prev_bytes: Dict[bytes, int] = {}
        self._prev_time: Optional[float] = None
        self._optimistic: Optional[bytes] = None
        self._tick = 0

    def __call__(self, connections: dict, piece_manager) -> Set[bytes]:
        now = time.monotonic()
        elapsed = (now - self._prev_time) if self._prev_time is not None else None
        current_bytes = dict(piece_manager.bytes_downloaded_from)

        rates: Dict[bytes, float] = {}
        if elapsed and elapsed > 0:
            for peer_id in connections:
                delta = current_bytes.get(peer_id, 0) - self._prev_bytes.get(peer_id, 0)
                rates[peer_id] = max(0, delta) / elapsed
        self._prev_bytes = current_bytes
        self._prev_time = now

        interested = {pid for pid, conn in connections.items() if conn.peer_interested}
        self._tick += 1
        due_for_rotation = self._tick % self.rotate_every == 0
        prev_opt = None if due_for_rotation else self._optimistic

        unchoked, optimistic = compute_unchoke_set(
            rates, interested, self.max_unchoked, self.optimistic_slots, previous_optimistic=prev_opt, rng=self._rng
        )
        self._optimistic = optimistic
        return unchoked
