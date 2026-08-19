"""An independent, deliberately differently-coded reference RGA.

`rga.py` builds a parent→children tree. This oracle instead maintains
one flat array and does the classic RGA *linear right-scan* insertion:
walk right from the origin's position while the next element is part
of the same "concurrent insertion group" (its own origin sits at or
after the insertion point) and outranks the new id; stop and splice in
otherwise. Same specification, unrelated code path — sharing no helper
functions with `rga.py` — so that `tests/test_convergence.py` compares
two genuinely independent implementations rather than a single
implementation against itself.

Unlike RGA.apply(), this oracle is intentionally strict: it raises
CausalityError if fed an op before its dependency, rather than
buffering. Callers (the convergence harness) are expected to feed ops
in a single globally causally-valid order — the order in which the
simulation actually created them, which is always valid because a site
can only ever reference its own already-applied state.
"""

from __future__ import annotations

from typing import Dict, List, Optional

from .ids import CharId
from .ops import DeleteOp, InsertOp
from .rga import CausalityError


class OracleRGA:
    def __init__(self) -> None:
        self._seq: List[dict] = []  # [{id, char, origin, tombstone}, ...]
        self._index: Dict[CharId, int] = {}

    def apply(self, op) -> None:
        if isinstance(op, InsertOp):
            self._apply_insert(op)
        elif isinstance(op, DeleteOp):
            self._apply_delete(op)
        else:
            raise TypeError(f"unknown op type: {type(op)!r}")

    def _apply_insert(self, op: InsertOp) -> None:
        if op.id in self._index:
            return  # idempotent
        origin_pos = -1
        if op.origin is not None:
            if op.origin not in self._index:
                raise CausalityError(f"oracle received {op.id!r} before its origin {op.origin!r}")
            origin_pos = self._index[op.origin]

        i = origin_pos + 1
        while i < len(self._seq):
            nxt = self._seq[i]
            nxt_origin_pos = -1 if nxt["origin"] is None else self._index[nxt["origin"]]
            if nxt_origin_pos < origin_pos:
                break  # nxt belongs to an earlier branch — stop, insert here
            if nxt["id"] > op.id:
                i += 1
                continue
            break

        self._seq.insert(i, {"id": op.id, "char": op.char, "origin": op.origin, "tombstone": False})
        self._reindex_from(i)

    def _apply_delete(self, op: DeleteOp) -> None:
        pos = self._index.get(op.id)
        if pos is None:
            raise CausalityError(f"oracle received a delete of {op.id!r} before its insert")
        self._seq[pos]["tombstone"] = True

    def _reindex_from(self, start: int) -> None:
        for i in range(start, len(self._seq)):
            self._index[self._seq[i]["id"]] = i

    @property
    def text(self) -> str:
        return "".join(n["char"] for n in self._seq if not n["tombstone"])
