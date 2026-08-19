"""A Site: one user's replica plus their outgoing edit log."""

from __future__ import annotations

from typing import List

from .rga import RGA


class Site:
    def __init__(self, site_id: str):
        self.site_id = site_id
        self.rga = RGA(site_id)
        self.log: List[object] = []  # every op this site has ever locally produced

    # -- the "user" API ---------------------------------------------------

    def type_at(self, pos: int, char: str):
        op = self.rga.local_insert(pos, char)
        self.log.append(op)
        return op

    def type_str(self, pos: int, text: str) -> list:
        """Convenience: insert a whole string starting at `pos`, one
        character at a time (each char gets its own id/op, matching a
        real user typing) — returns the list of ops produced."""
        ops = []
        for offset, ch in enumerate(text):
            ops.append(self.type_at(pos + offset, ch))
        return ops

    def delete_at(self, pos: int):
        op = self.rga.local_delete(pos)
        self.log.append(op)
        return op

    def receive(self, op) -> None:
        self.rga.apply(op)

    # -- read-only views ----------------------------------------------------

    @property
    def text(self) -> str:
        return self.rga.text

    def has_pending(self) -> bool:
        return self.rga.has_pending()

    def __repr__(self) -> str:  # pragma: no cover - cosmetic
        return f"Site({self.site_id!r}, text={self.text!r})"
