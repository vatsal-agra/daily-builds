"""
site.py — a Site wraps one RGADocument with the causal-delivery machinery
a real peer needs: a pending-ops buffer for ops that arrive before their
dependency, an append-only op log (used for anti-entropy gossip), and a
CRDT-aware local undo/redo stack.
"""

from crdt.rga import RGADocument


class Site:
    def __init__(self, site_id):
        self.site_id = site_id
        self.doc = RGADocument(site_id)
        self.pending = []          # ops waiting on a causal dependency
        self.op_log = []           # every op ever applied here, in application order
        self.applied_ids = set()   # (type, id) keys already applied (local or remote)
        self.undo_stack = []       # this site's own local edits, most recent last
        self.redo_stack = []

    # ---- local typing ---------------------------------------------------

    def _record_local(self, op):
        self.applied_ids.add(self._op_key(op))
        self.op_log.append(op)

    def type_insert(self, index, value):
        op = self.doc.local_insert(index, value)
        self._record_local(op)
        self.undo_stack.append({"kind": "insert", "node_ids": [tuple(op["id"])]})
        self.redo_stack.clear()
        return op

    def type_delete(self, index):
        op = self.doc.local_delete(index)
        self._record_local(op)
        # a delete op's own `id` is a fresh op-identity, not the node it
        # acts on — the undo stack needs the *target* node id.
        self.undo_stack.append({"kind": "delete", "node_ids": [tuple(op["target"])]})
        self.redo_stack.clear()
        return op

    def type_text(self, index, text):
        """Insert a multi-character string starting at `index` (typing
        fast, or pasting) as a single grouped undo action — one undo
        removes the whole run, not one character at a time."""
        ops = []
        node_ids = []
        for offset, ch in enumerate(text):
            op = self.doc.local_insert(index + offset, ch)
            self._record_local(op)
            ops.append(op)
            node_ids.append(tuple(op["id"]))
        if node_ids:
            self.undo_stack.append({"kind": "insert", "node_ids": node_ids})
            self.redo_stack.clear()
        return ops

    def type_delete_range(self, index, count):
        """Delete `count` characters starting at `index`, grouped as a
        single undo action. Deleting shifts everything after `index` left
        by one each time, so every deletion in the range targets the same
        visible index."""
        ops = []
        node_ids = []
        for _ in range(count):
            op = self.doc.local_delete(index)
            self._record_local(op)
            ops.append(op)
            node_ids.append(tuple(op["target"]))
        if node_ids:
            self.undo_stack.append({"kind": "delete", "node_ids": node_ids})
            self.redo_stack.clear()
        return ops

    # ---- CRDT-aware undo/redo ---------------------------------------------
    #
    # Undo targets the node **id** this site's own past op created or
    # tombstoned — never a document position — so it stays correct no
    # matter what remote edits (inserts, deletes, even other peers' own
    # undos) have landed in between. "Undo my insert" always means "delete
    # that exact character, wherever it now sits, in whatever it's now
    # surrounded by"; it is never "delete whatever the Nth character
    # happens to be right now."

    def undo(self):
        """Undo this site's own most recent not-yet-undone local edit
        (possibly a whole grouped paste/range as one action). Returns the
        list of compensating ops (already applied locally and broadcast-
        ready), or None if there's nothing left to undo."""
        if not self.undo_stack:
            return None
        entry = self.undo_stack.pop()
        compensate = self.doc.delete_by_id if entry["kind"] == "insert" else self.doc.restore_by_id
        ops = [compensate(nid) for nid in entry["node_ids"]]
        for op in ops:
            self._record_local(op)
        self.redo_stack.append(entry)
        return ops

    def redo(self):
        """Re-apply the most recently undone local edit. Returns the list
        of ops, or None if there's nothing to redo (including: a new
        local edit was made since the last undo, which clears the redo
        stack — the same rule every text editor uses)."""
        if not self.redo_stack:
            return None
        entry = self.redo_stack.pop()
        compensate = self.doc.restore_by_id if entry["kind"] == "insert" else self.doc.delete_by_id
        ops = [compensate(nid) for nid in entry["node_ids"]]
        for op in ops:
            self._record_local(op)
        self.undo_stack.append(entry)
        return ops

    def can_undo(self):
        return len(self.undo_stack) > 0

    def can_redo(self):
        return len(self.redo_stack) > 0

    # ---- receiving ops from the network ---------------------------------

    @staticmethod
    def _op_key(op):
        # Every op (insert, delete, restore) carries its own globally
        # unique `id`, allocated from the issuing site's counter — for
        # inserts that id also happens to name the node it creates; for
        # delete/restore it's the op's own identity, separate from the
        # `target` node it acts on (see rga.py's local_delete docstring
        # for why that separation matters once undo/redo can delete and
        # restore the same node more than once).
        return (op["type"], tuple(op["id"]))

    def receive(self, op):
        """Try to apply `op`; if its causal dependency hasn't arrived yet,
        buffer it and retry automatically whenever new ops land. Safe to
        call with a duplicate or already-applied op (no-op)."""
        if self._try_apply(op):
            self._drain_pending()
        else:
            self.buffer(op)

    def _try_apply(self, op):
        key = self._op_key(op)
        if key in self.applied_ids:
            return True  # duplicate delivery — already have it
        if not self.doc.apply_remote_op(op):
            return False  # dependency not met yet
        self.applied_ids.add(key)
        self.op_log.append(op)
        return True

    def _drain_pending(self):
        if not self.pending:
            return
        progressed = True
        while progressed and self.pending:
            progressed = False
            still_pending = []
            for op in self.pending:
                if self._try_apply(op):
                    progressed = True
                else:
                    still_pending.append(op)
            self.pending = still_pending

    def buffer(self, op):
        if self._op_key(op) in self.applied_ids:
            return
        self.pending.append(op)

    # ---- anti-entropy (gossip) -------------------------------------------

    def missing_ops_for(self, peer_applied_keys):
        """Ops this site has that `peer_applied_keys` (a set of (type, id)
        keys) doesn't."""
        return [op for op in self.op_log if self._op_key(op) not in peer_applied_keys]

    # ---- reading ------------------------------------------------------------

    def text(self):
        return self.doc.to_string()

    def is_settled(self):
        """True once every buffered op has been able to apply — i.e. this
        site has no outstanding causal gaps."""
        return len(self.pending) == 0
