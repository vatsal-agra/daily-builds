"""The RGA (Replicated Growable Array) sequence CRDT.

Modeled as a tree: every node's `children` are the characters that were
ever inserted *immediately after* it, kept sorted by id descending (the
deterministic tie-break: among characters inserted at the same spot,
the one with the higher id — i.e. whichever site "wins" the comparison
— sits first). The document text is the pre-order traversal of the
tree rooted at a virtual ROOT, skipping tombstoned nodes but always
descending into their children (a delete must never hide text that was
concurrently inserted after the deleted character).

This tree formulation is a faithful RGA: two replicas that have applied
the exact same set of insert/delete operations — in *any* order, any
number of times each — build the identical tree, because:

  * an insert only ever depends on its `origin` id already being
    present (checked and, if missing, buffered — see `pending` below);
  * inserting a child under a given parent is decided purely by
    (parent id, new id) — never by what else has already happened
    under sibling parents, so unrelated concurrent inserts can't
    perturb each other's relative order;
  * delete just flips a boolean on an existing node, which is
    commutative, associative, and idempotent by construction.

That's the whole Strong Eventual Consistency argument for this data
structure; `convergence.py` puts it under randomized test instead of
just asserting it in a docstring.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Dict, List, Optional

from .ids import CharId, LamportClock
from .ops import DeleteOp, InsertOp


@dataclass
class _Node:
    id: CharId
    char: str
    origin: Optional[CharId]
    tombstone: bool = False
    children: List[CharId] = field(default_factory=list)


class CausalityError(RuntimeError):
    """Raised only by strict/offline helpers that require ops to arrive
    in a causally valid order; RGA.apply() itself never raises this —
    it buffers instead. Kept for the reference oracle in oracle.py."""


class RGA:
    """One replica of a Skein document."""

    def __init__(self, site_id: str):
        self.site_id = site_id
        self.clock = LamportClock(site_id)
        self._nodes: Dict[CharId, _Node] = {}
        self._root_children: List[CharId] = []
        # ops waiting on a dependency (origin, for inserts; target, for
        # deletes) that hasn't arrived at this replica yet.
        self._pending: Dict[CharId, List[object]] = {}

    # -- local edits (called by Site on behalf of the "user") ----------

    def local_insert(self, pos: int, char: str) -> InsertOp:
        """Insert `char` at visible position `pos`. Returns the op to
        broadcast (already applied locally)."""
        visible = self._visible_ids()
        if not 0 <= pos <= len(visible):
            raise IndexError(f"insert position {pos} out of range [0, {len(visible)}]")
        origin = visible[pos - 1] if pos > 0 else None
        return self.insert_after(origin, char)

    def insert_after(self, origin: Optional[CharId], char: str) -> InsertOp:
        """Insert `char` immediately after the node `origin` (or at the
        very start of the document if `origin` is None), addressing the
        insertion point by id rather than by visible position. Used
        directly by `local_insert` and by `undo.py` (re-inserting an
        undone deletion has to land next to where the character actually
        was, which a position number can't reliably express once other
        edits have moved things around)."""
        if len(char) != 1:
            raise ValueError(f"insert_after char must be a single character, got {char!r}")
        op = InsertOp(id=self.clock.tick(), char=char, origin=origin)
        self.apply(op)
        return op

    def local_delete(self, pos: int) -> DeleteOp:
        """Delete the character at visible position `pos`. Returns the
        op to broadcast (already applied locally)."""
        visible = self._visible_ids()
        if not 0 <= pos < len(visible):
            raise IndexError(f"delete position {pos} out of range [0, {len(visible) - 1}]")
        op = DeleteOp(id=visible[pos])
        self.apply(op)
        return op

    # -- remote/replay application --------------------------------------

    def apply(self, op) -> None:
        """Apply a (possibly out-of-order, possibly duplicate) remote op —
        or a local one; local_insert/local_delete route through here too.
        Safe to call with the same op more than once.

        Applying one op can unblock a whole chain of previously-buffered
        ops waiting on it (e.g. a long typed passage delivered in exactly
        reverse order unblocks one more character with every op applied).
        That cascade is driven by an explicit worklist, deliberately
        *not* recursion — a naive "apply, then recursively replay
        whatever that unblocked" implementation blows Python's recursion
        limit on any such chain longer than ~1000, which a real typing
        session or a sufficiently adversarial delivery order reaches
        easily."""
        if not isinstance(op, (InsertOp, DeleteOp)):
            raise TypeError(f"unknown op type: {type(op)!r}")

        worklist = [op]
        while worklist:
            current = worklist.pop()
            if isinstance(current, InsertOp):
                self.clock.observe(current.id.counter)
                newly_available = self._try_apply_insert(current)
                if newly_available is not None:
                    worklist.extend(self._pending.pop(newly_available, ()))
            else:
                self._try_apply_delete(current)

    def has_pending(self) -> bool:
        """True if this replica is holding ops that are still waiting on
        a causal dependency it hasn't seen yet (a real bug if still true
        after a simulation has fully drained its network)."""
        return bool(self._pending)

    # -- internals --------------------------------------------------------

    def _try_apply_insert(self, op: InsertOp) -> Optional[CharId]:
        """Returns op.id if this call newly created that node (so the
        caller should replay anything pending on it), or None if it was
        a duplicate (already present) or had to be buffered."""
        if op.id in self._nodes:
            return None  # duplicate delivery — idempotent no-op
        parent_children = self._children_of(op.origin)
        if parent_children is None:
            self._pending.setdefault(op.origin, []).append(op)
            return None
        node = _Node(id=op.id, char=op.char, origin=op.origin)
        self._nodes[op.id] = node
        _sorted_insert_desc(parent_children, op.id)
        return op.id

    def _try_apply_delete(self, op: DeleteOp) -> None:
        node = self._nodes.get(op.id)
        if node is None:
            self._pending.setdefault(op.id, []).append(op)
            return
        node.tombstone = True  # idempotent — fine if already tombstoned

    def _children_of(self, origin: Optional[CharId]) -> Optional[List[CharId]]:
        if origin is None:
            return self._root_children
        node = self._nodes.get(origin)
        return None if node is None else node.children

    def _visible_ids(self) -> List[CharId]:
        return [cid for cid in self._preorder() if not self._nodes[cid].tombstone]

    def _preorder(self) -> List[CharId]:
        """Iterative pre-order traversal (never recursive: a document
        typed straight through — the common case — chains each new
        character under the previous one, so a recursive traversal
        would blow Python's recursion limit on anything longer than
        ~1000 characters)."""
        out: List[CharId] = []
        stack = list(reversed(self._root_children))
        while stack:
            cid = stack.pop()
            out.append(cid)
            node = self._nodes[cid]
            if node.children:
                stack.extend(reversed(node.children))
        return out

    # -- read-only views --------------------------------------------------

    @property
    def text(self) -> str:
        return "".join(self._nodes[cid].char for cid in self._preorder() if not self._nodes[cid].tombstone)

    def __len__(self) -> int:
        return len(self._visible_ids())

    def char_and_origin(self, char_id: CharId):
        """(char, origin) for a node that exists locally, tombstoned or
        not — tombstoning only flips a flag, it never forgets the
        character's value or where it was, which is exactly what
        `undo.py` needs to know how to bring a deleted character back."""
        node = self._nodes[char_id]
        return node.char, node.origin

    def node_count(self) -> int:
        """Total nodes including tombstones — useful for tombstone-growth
        inspection/tests."""
        return len(self._nodes)


def _sorted_insert_desc(ids: List[CharId], new_id: CharId) -> None:
    """Insert `new_id` into `ids`, which is (and remains) sorted by id
    descending. O(n) — fine at this project's scale; a production RGA
    would use a balanced structure per parent."""
    i = 0
    while i < len(ids) and ids[i] > new_id:
        i += 1
    ids.insert(i, new_id)
