"""
rga.py — a from-scratch Replicated Growable Array (RGA) CRDT.

RGA (Roh, Jeon, Kim & Lee, 2011, "Replicated abstract data types: Building
blocks for collaborative applications") represents a sequence (here: the
characters of a text document) as a list of tombstone-capable nodes. Every
node has a globally-unique id `(counter, site_id)` and an `origin` — the id
of the node it was inserted immediately to the right of at the moment it
was created (or `None` for "the very start of the document").

The key trick that makes two independently-edited replicas converge to the
*same* sequence without ever talking to each other during the edit is the
`_integrate` placement rule below: when two sites concurrently insert right
after the same origin, every replica breaks the tie the same deterministic
way (by comparing ids), so however the two inserts arrive — in whichever
order, with whatever delay, even delivered twice — every replica ends up
placing them in the identical relative order.

Deletes are tombstones (`deleted=True`), never physically removed, because
a later, concurrently-created insert might still reference a deleted node
as its origin — removing the node would break that reference.

This module is deliberately self-contained (no threads, no network, no
wall-clock) so it can be tested as pure data-in/data-out, and so it has an
exact 1:1 JS port in static/rga.js for the browser.
"""

from __future__ import annotations


def _id_of(x):
    """Normalize an id to a hashable tuple; accepts a 2-list (from JSON/the
    network) or a 2-tuple (from local Python code) or None."""
    if x is None:
        return None
    return (x[0], x[1])


def _id_greater(a, b):
    """Deterministic total order over ids: higher counter wins; the
    site_id (a string) is the tiebreak for same-counter ids from different
    sites, which can genuinely happen (two sites both make their Nth local
    edit). Every replica — Python or JS — must use this exact rule."""
    if a[0] != b[0]:
        return a[0] > b[0]
    return a[1] > b[1]


class RGADocument:
    """A single site's replica of a shared text document."""

    def __init__(self, site_id):
        self.site_id = site_id
        self._counter = 0
        self.sequence = []          # ordered list of node dicts, tombstones included
        self.by_id = {}             # id tuple -> node dict (same object as in `sequence`)
        self._index = {}            # id tuple -> current index in `sequence`

    # ---- id allocation -----------------------------------------------

    def _next_id(self):
        self._counter += 1
        return (self._counter, self.site_id)

    # ---- the RGA placement algorithm ----------------------------------

    def _reindex_from(self, start):
        for i in range(start, len(self.sequence)):
            self._index[self.sequence[i]["id"]] = i

    def _integrate(self, node):
        """Insert `node` (already carrying its final id/origin/value) into
        `self.sequence` at the position the RGA algorithm dictates, given
        whatever nodes are already present locally."""
        origin = node["origin"]
        left_idx = self._index[origin] if origin is not None else -1
        i = left_idx + 1
        n = len(self.sequence)
        while i < n:
            other = self.sequence[i]
            other_origin = other["origin"]
            other_origin_idx = self._index[other_origin] if other_origin is not None else -1
            if other_origin_idx < left_idx:
                # `other` descends from something left of our own origin —
                # we've walked past our whole "insert zone"; stop here.
                break
            if other_origin_idx == left_idx:
                # A direct sibling: another node also inserted immediately
                # after our origin. Break the tie deterministically —
                # the higher id stays closer to the origin.
                if _id_greater(other["id"], node["id"]):
                    i += 1
                    continue
                break
            # other_origin_idx > left_idx: `other` is nested under a
            # sibling (or a descendant of one) that sits to our right —
            # skip over that whole subtree, it doesn't compete with us.
            i += 1
        self.sequence.insert(i, node)
        self.by_id[node["id"]] = node
        self._reindex_from(i)

    # ---- local edits (this site typing) --------------------------------

    def _origin_for_visible_index(self, index):
        if index == 0:
            return None
        count = 0
        for node in self.sequence:
            if not node["deleted"]:
                count += 1
                if count == index:
                    return node["id"]
        raise IndexError(f"insert index {index} out of range (doc length {self.visible_length()})")

    def _visible_node_at(self, index):
        count = -1
        for node in self.sequence:
            if not node["deleted"]:
                count += 1
                if count == index:
                    return node
        raise IndexError(f"delete index {index} out of range (doc length {self.visible_length()})")

    def local_insert(self, index, value):
        """Insert a single character `value` at visible position `index`.
        Returns the op (a plain, JSON-serializable dict) to broadcast."""
        if len(value) != 1:
            raise ValueError("local_insert takes exactly one character")
        origin = self._origin_for_visible_index(index)
        node_id = self._next_id()
        node = {"id": node_id, "origin": origin, "value": value, "deleted": False}
        self._integrate(node)
        return {
            "type": "insert",
            "id": list(node_id),
            "origin": list(origin) if origin is not None else None,
            "value": value,
        }

    def local_delete(self, index):
        """Tombstone the character currently at visible position `index`.
        Returns the op to broadcast.

        Note that the returned op's own `id` is a *freshly allocated* id,
        distinct from the `target` node's id — a delete/restore op needs
        its own identity because the same node can legitimately be
        deleted, undone (restored), and deleted again over its lifetime
        (see undo/redo below); if a delete op reused its target's id, the
        second delete of the same node would be indistinguishable from a
        duplicate network delivery of the first one and get silently
        dropped by the dedup logic in site.py."""
        node = self._visible_node_at(index)
        node["deleted"] = True
        op_id = self._next_id()
        return {"type": "delete", "id": list(op_id), "target": list(node["id"])}

    # ---- id-targeted edits (used by undo/redo, not the live editor) ----
    #
    # A normal edit targets a *visible position* because that's what typing
    # means. Undo is different: "undo the character I inserted 47 edits
    # ago" has to keep meaning the same physical character no matter how
    # much the document has moved around since — including edits from
    # other peers landing in between. So undo/redo target a node **id**
    # directly rather than a position, and are safe no-ops if the node is
    # already in the state being asked for (e.g. undoing your insert after
    # someone else already deleted that same character).

    def delete_by_id(self, node_id):
        node = self.by_id[_id_of(node_id)]
        node["deleted"] = True
        op_id = self._next_id()
        return {"type": "delete", "id": list(op_id), "target": list(node["id"])}

    def restore_by_id(self, node_id):
        node = self.by_id[_id_of(node_id)]
        node["deleted"] = False
        op_id = self._next_id()
        return {"type": "restore", "id": list(op_id), "target": list(node["id"])}

    # ---- applying ops received from other sites ------------------------

    def apply_remote_op(self, op):
        """Apply an op produced by (a possibly different) `local_insert` /
        `local_delete` / this same method elsewhere. Returns True if the
        op was applied, False if it can't be applied yet because its
        causal dependency (the origin node for an insert, or the target
        node for a delete) hasn't arrived at this replica yet — the
        caller is expected to buffer and retry such ops. Applying the
        same insert op twice is a safe no-op (idempotent), which matters
        because the network may duplicate messages."""
        if op["type"] == "insert":
            node_id = _id_of(op["id"])
            if node_id in self.by_id:
                return True  # already have it — duplicate delivery
            origin = _id_of(op["origin"])
            if origin is not None and origin not in self.by_id:
                return False  # causal dependency not met yet
            node = {"id": node_id, "origin": origin, "value": op["value"], "deleted": False}
            self._integrate(node)
            return True
        elif op["type"] == "delete":
            target = _id_of(op["target"])
            node = self.by_id.get(target)
            if node is None:
                return False  # the insert that created the target hasn't arrived yet
            node["deleted"] = True
            return True
        elif op["type"] == "restore":
            # the undo/redo counterpart to "delete": un-tombstone a node.
            # Same causal-dependency rule as delete — buffer until the
            # insert that created the target node has arrived.
            target = _id_of(op["target"])
            node = self.by_id.get(target)
            if node is None:
                return False
            node["deleted"] = False
            return True
        raise ValueError(f"unknown op type: {op['type']!r}")

    # ---- reading ---------------------------------------------------------

    def to_string(self):
        return "".join(n["value"] for n in self.sequence if not n["deleted"])

    def visible_length(self):
        return sum(1 for n in self.sequence if not n["deleted"])

    def snapshot(self):
        """A deep, JSON-safe snapshot of every node (including tombstones)
        for debugging / the web UI's raw-state inspector."""
        return [
            {"id": list(n["id"]), "origin": list(n["origin"]) if n["origin"] else None,
             "value": n["value"], "deleted": n["deleted"]}
            for n in self.sequence
        ]
