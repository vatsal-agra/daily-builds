"""Unique, totally-ordered character identifiers.

Every character ever inserted into a Skein document gets a globally
unique ID: a (counter, site) pair minted by a per-site Lamport-style
clock. The clock always advances past the highest counter the site has
ever *seen* (locally minted or received from a remote op), which keeps
IDs roughly time-ordered without any coordination between sites.

The ID's only job beyond uniqueness is providing a **total order** so
that concurrent inserts at the same position resolve deterministically,
identically, on every replica, without any replica talking to another
to agree on who "won". Python's built-in tuple comparison (counter
first, then site as a tiebreaker) gives exactly that.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class CharId:
    """A globally unique, totally-ordered character identifier."""

    counter: int
    site: str

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"{self.site}:{self.counter}"


class LamportClock:
    """Per-site monotonic counter used to mint CharIds.

    Advances past any counter value it observes (locally or remotely),
    which is the standard Lamport-clock update rule: local tick takes
    max(current, 0) + 1; observing a remote counter c bumps the clock to
    at least c (never generating a duplicate or a counter that could
    ever look "older" than something already seen).
    """

    def __init__(self, site_id: str):
        self.site_id = site_id
        self._counter = 0

    def tick(self) -> CharId:
        self._counter += 1
        return CharId(self._counter, self.site_id)

    def observe(self, other_counter: int) -> None:
        if other_counter > self._counter:
            self._counter = other_counter
