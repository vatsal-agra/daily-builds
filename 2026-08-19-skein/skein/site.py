"""A Site: one user's replica plus their outgoing edit log and their own
local undo/redo history."""

from __future__ import annotations

from typing import List, Optional

from .rga import RGA
from .undo import UndoManager


class Site:
    def __init__(self, site_id: str):
        self.site_id = site_id
        self.rga = RGA(site_id)
        self.log: List[object] = []  # every op this site has ever locally produced
        self.undo_mgr = UndoManager(self.rga)

    # -- the "user" API ---------------------------------------------------

    def type_at(self, pos: int, char: str):
        op = self.rga.local_insert(pos, char)
        self.log.append(op)
        self.undo_mgr.record_insert(op)
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
        char, origin = self.rga.char_and_origin(op.id)
        self.log.append(op)
        self.undo_mgr.record_delete(char, origin)
        return op

    def undo(self):
        """Undo this site's own most recent not-yet-undone local edit.
        Returns the op produced (to broadcast), or None if there's
        nothing left to undo."""
        op = self.undo_mgr.undo()
        if op is not None:
            self.log.append(op)
        return op

    def redo(self):
        """Redo this site's own most recently undone edit. Returns the
        op produced (to broadcast), or None if there's nothing to redo."""
        op = self.undo_mgr.redo()
        if op is not None:
            self.log.append(op)
        return op

    def can_undo(self) -> bool:
        return self.undo_mgr.can_undo()

    def can_redo(self) -> bool:
        return self.undo_mgr.can_redo()

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
