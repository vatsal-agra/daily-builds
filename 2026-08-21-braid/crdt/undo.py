"""CRDT-aware local undo/redo.

The naive approach — keep a stack of document *snapshots* and pop back to
the previous one — is wrong for a collaborative document: if a remote
peer's edit landed after your last local op, reverting to a snapshot
silently discards their work too. That's not "undo," that's data loss
with extra steps.

`UndoManager` instead undoes by generating and applying the semantic
*inverse* of your own most recent local op, against the *current*
document state:

- undo an insert -> delete that exact character (by node id, not index —
  its visible position may have moved since you typed it)
- undo a delete  -> undelete that exact character (via the LWW tombstone
  op `RGA.local_undelete_by_id` mints, so it composes correctly even if
  someone else concurrently deleted the same character — see
  `Node.tombstone_op_id` in `rga.py`)

Only your own ops are ever tracked or undone. A remote peer's edits are
never on your undo stack and are never reverted by your Ctrl+Z, no
matter when they arrived.
"""

from __future__ import annotations

from .rga import RGA


class UndoManager:
    def __init__(self, doc: RGA):
        self.doc = doc
        self._undo_stack: list = []  # entries: {"kind": "insert"|"delete", "target": id}
        self._redo_stack: list = []

    def record_local_op(self, op: dict) -> None:
        """Call this with every op `self.doc`'s local_insert/local_delete
        just returned, so it becomes undoable. Doing an original edit
        clears the redo stack (standard editor behavior: you can't redo
        something a fresh edit has now branched away from)."""
        if op["type"] == "insert":
            self._undo_stack.append({"kind": "insert", "target": op["id"]})
        elif op["type"] in ("delete", "undelete"):
            self._undo_stack.append({"kind": op["type"], "target": op["id"]})
        else:
            return
        self._redo_stack.clear()

    def can_undo(self) -> bool:
        return len(self._undo_stack) > 0

    def can_redo(self) -> bool:
        return len(self._redo_stack) > 0

    def undo(self):
        """Undo the most recent local op. Returns the generated inverse
        op (to broadcast), or None if there was nothing to undo."""
        if not self._undo_stack:
            return None
        entry = self._undo_stack.pop()
        inverse_op = self._apply_inverse(entry)
        self._redo_stack.append(entry)
        return inverse_op

    def redo(self):
        """Redo the most recently undone op. Returns the generated op (to
        broadcast), or None if there was nothing to redo."""
        if not self._redo_stack:
            return None
        entry = self._redo_stack.pop()
        redo_op = self._apply_forward(entry)
        self._undo_stack.append(entry)
        return redo_op

    # ------------------------------------------------------------------
    # "insert" and "undelete" are both *make-visible* actions (their
    # inverse hides the character); "delete" is the one *make-hidden*
    # action (its inverse shows it again). Every undo/redo step reduces
    # to "make this target visible" or "make this target hidden," and is
    # skipped as a no-op if the document has already concurrently reached
    # that state (e.g. someone else deleted the same character first) —
    # never forced, since forcing would blindly overwrite a concurrent
    # edit rather than compose with it.
    # ------------------------------------------------------------------

    def _show(self, target):
        if target not in self.doc.nodes or not self.doc.nodes[target].tombstone:
            return None
        return self.doc.local_undelete_by_id(target)

    def _hide(self, target):
        if target not in self.doc.nodes or self.doc.nodes[target].tombstone:
            return None
        return self.doc.local_delete_by_id(target)

    def _apply_inverse(self, entry: dict):
        target = entry["target"]
        makes_visible = entry["kind"] in ("insert", "undelete")
        return self._hide(target) if makes_visible else self._show(target)

    def _apply_forward(self, entry: dict):
        target = entry["target"]
        makes_visible = entry["kind"] in ("insert", "undelete")
        return self._show(target) if makes_visible else self._hide(target)
