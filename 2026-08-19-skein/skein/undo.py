"""Per-site local undo/redo that stays correct under remote interleaving.

Plain "undo the last thing you typed" is harder than it sounds on top
of a CRDT: the character you want to remove may no longer sit at any
particular *position* by the time you press undo, because a remote
edit could have inserted or deleted text anywhere around it in the
meantime. Position-based undo (record "index 5" and delete index 5
later) would silently remove the wrong character.

This implementation instead tracks each of the site's own edits as a
**toggle between two states**, addressed entirely by id/origin, never
by position:

  * an insert you made is "currently present, with this id" — undoing
    it deletes that exact id (wherever it now lives in the document,
    regardless of anything else that happened around it);
  * a delete you made is "currently absent, with this original char and
    origin" — undoing it re-inserts a **new** node with that char right
    after that origin.

That second point is an honest CRDT constraint, not an oversight: a
tombstoned id is permanently gone (see rga.py) — CRDTs never resurrect
an id, they mint a fresh one. So "redo" doesn't restore the *exact*
same node either; it re-establishes the same effect (same character,
same origin) as a new op, which — like any concurrent insert at that
spot — is subject to the same deterministic tie-break against whatever
else has since been inserted at that origin in the meantime. Disclosed
in REVIEW.md and demonstrated in the tests rather than glossed over.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional

from .ids import CharId
from .ops import DeleteOp, InsertOp
from .rga import RGA


@dataclass
class _ToggleEntry:
    char: str
    origin: Optional[CharId]
    current_id: Optional[CharId]  # None means "currently deleted/absent"


class UndoManager:
    """One of these per Site, tracking only *that site's own* local
    edits — never remote ones, which is the entire point."""

    def __init__(self, rga: RGA):
        self.rga = rga
        self.undo_stack: List[_ToggleEntry] = []
        self.redo_stack: List[_ToggleEntry] = []

    # -- called by Site right after a fresh (non-undo/redo) local edit ---

    def record_insert(self, op: InsertOp) -> None:
        self.undo_stack.append(_ToggleEntry(char=op.char, origin=op.origin, current_id=op.id))
        self.redo_stack.clear()  # a fresh edit invalidates old redo history

    def record_delete(self, char: str, origin: Optional[CharId]) -> None:
        self.undo_stack.append(_ToggleEntry(char=char, origin=origin, current_id=None))
        self.redo_stack.clear()

    # -- the actual commands ------------------------------------------------

    def can_undo(self) -> bool:
        return bool(self.undo_stack)

    def can_redo(self) -> bool:
        return bool(self.redo_stack)

    def undo(self):
        if not self.undo_stack:
            return None
        entry = self.undo_stack.pop()
        op = self._flip(entry)
        self.redo_stack.append(entry)
        return op

    def redo(self):
        if not self.redo_stack:
            return None
        entry = self.redo_stack.pop()
        op = self._flip(entry)
        self.undo_stack.append(entry)
        return op

    def _flip(self, entry: _ToggleEntry):
        if entry.current_id is not None:
            # currently present -> remove it (idempotent even if some
            # remote site independently deleted this exact character
            # first — undo still "succeeds," the character is just
            # already gone, same as a real editor racing a peer)
            op = DeleteOp(id=entry.current_id)
            self.rga.apply(op)
            entry.current_id = None
        else:
            # currently absent -> bring it back as a brand-new node
            op = self.rga.insert_after(entry.origin, entry.char)
            entry.current_id = op.id
        return op
