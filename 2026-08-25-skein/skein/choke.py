"""Tit-for-tat choking: the algorithm that makes a BitTorrent swarm
converge on reciprocal, mutually-beneficial trading instead of pure
free-riding.

A peer connection is "choked" when we refuse to upload to it and
"unchoked" when we will. Real clients re-run this decision periodically:

  * Rank currently-interested peers by how much they've recently given
    *us* (download rate they contributed), and unchoke the top
    `MAX_UNCHOKED` of them — reciprocate with whoever is reciprocating.
  * Reserve one extra "optimistic unchoke" slot for a peer chosen
    without regard to rate (round-robin/random among the rest), so a
    new or currently-low-rate peer still gets a chance to prove itself
    and isn't permanently locked out just because it hasn't had an
    opportunity yet.
  * A pure seeder has no download rate to rank on, so it instead ranks
    by *upload rate it is delivering to each peer* — reward whoever is
    pulling data fastest, which in a real swarm tends to reward peers
    who are themselves circulating pieces well.

This module is the pure decision logic, deliberately separated from
socket/threading code so it can be unit-tested deterministically.
"""

from __future__ import annotations

import random
import time

MAX_UNCHOKED = 4          # "regular" reciprocal unchoke slots
OPTIMISTIC_SLOTS = 1       # slots given out without regard to rate
REEVALUATE_INTERVAL = 10.0  # seconds, matches real clients' ~10s cadence


class PeerStats:
    __slots__ = ("downloaded_from", "uploaded_to", "interested", "last_seen")

    def __init__(self):
        self.downloaded_from = 0  # bytes this peer has sent us
        self.uploaded_to = 0      # bytes we've sent this peer
        self.interested = False
        self.last_seen = 0.0


class ChokeManager:
    def __init__(self, is_seed: bool = False, rng: random.Random | None = None,
                 max_unchoked: int = MAX_UNCHOKED, optimistic_slots: int = OPTIMISTIC_SLOTS):
        self.is_seed = is_seed
        self._rng = rng or random.Random()
        self._stats: dict[str, PeerStats] = {}
        self._max_unchoked = max_unchoked
        self._optimistic_slots = optimistic_slots
        self._round = 0

    def _get(self, peer_id: str) -> PeerStats:
        return self._stats.setdefault(peer_id, PeerStats())

    def record_download(self, peer_id: str, nbytes: int) -> None:
        self._get(peer_id).downloaded_from += nbytes

    def record_upload(self, peer_id: str, nbytes: int) -> None:
        self._get(peer_id).uploaded_to += nbytes

    def set_interested(self, peer_id: str, interested: bool) -> None:
        self._get(peer_id).interested = interested

    def forget(self, peer_id: str) -> None:
        self._stats.pop(peer_id, None)

    def decide_unchoked(self, connected_peer_ids) -> set:
        """Return the set of peer_ids that should be unchoked this round.
        Everyone else should be choked. Only interested peers can ever be
        chosen (choking a disinterested peer costs nothing and unchoking
        one wastes a reciprocation slot).
        """
        self._round += 1
        interested = [
            pid for pid in connected_peer_ids
            if self._get(pid).interested
        ]
        if not interested:
            return set()

        rank_key = (
            (lambda pid: self._get(pid).uploaded_to)
            if self.is_seed else
            (lambda pid: self._get(pid).downloaded_from)
        )
        ranked = sorted(interested, key=rank_key, reverse=True)
        regular = ranked[: self._max_unchoked]

        remaining = [pid for pid in ranked if pid not in regular]
        optimistic = set()
        if remaining and self._optimistic_slots > 0:
            k = min(self._optimistic_slots, len(remaining))
            optimistic = set(self._rng.sample(remaining, k))

        return set(regular) | optimistic
