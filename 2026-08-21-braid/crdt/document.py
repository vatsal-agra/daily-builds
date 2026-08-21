"""Document — a nested, multi-type CRDT container ("mini Automerge").

A real collaborative document is rarely *just* text. `Document` is an
OR-Map-style container of named fields, where each field is its own
independently-correct CRDT: `RGA` text blocks (op-based), `PNCounter`
and `ORSet` (state-based), and `LWWRegister` (a small op-based CRDT
introduced here for single-value fields like a title). Mixing an
op-based sequence CRDT with state-based counters/sets in one document is
exactly what production systems like Automerge do — different data
shapes call for different CRDT strategies, and a real "document" CRDT is
a composition of several primitive CRDTs, not one universal algorithm.

Sync is uniformly state-based at the `Document` level (`state()` /
`merge()`) even for the op-based `text` fields — shipping a text field's
full `op_log` and replaying it through `apply_remote` (idempotent for
anything already known) *is* a legitimate state-sync mechanism for an
op-based CRDT, the same trick `server/braid_server.py`'s live
anti-entropy pass uses. This keeps one consistent merge interface across
every field type instead of a different sync protocol per kind.

Known, accepted limitation: concurrently creating two *different-typed*
fields under the *same* name is a genuine schema conflict this module
doesn't resolve (it raises) — real Automerge-style systems have their
own conflict-registers for exactly this case; out of scope here, and
documented rather than silently mishandled.
"""

from __future__ import annotations

from .clock import CausalDeliveryBuffer, LamportClock
from .counter import PNCounter
from .orset import ORSet
from .rga import RGA


class LWWRegister:
    """A single-value op-based CRDT: last write wins, ties broken by the
    writer's own Lamport id (same tie-break style as RGA node ids)."""

    def __init__(self, peer_id: str):
        self.peer_id = peer_id
        self.clock = LamportClock(peer_id)
        self._value = None
        self._id = None

    def set(self, value) -> dict:
        op_id = (self.clock.tick(), self.peer_id)
        self._apply(value, op_id)
        return {"value": value, "id": list(op_id)}

    def apply_remote(self, op: dict) -> None:
        op_id = tuple(op["id"])
        self.clock.observe(op_id[0])
        self._apply(op["value"], op_id)

    def _apply(self, value, op_id) -> None:
        if self._id is None or op_id > self._id:
            self._value = value
            self._id = op_id

    def get(self):
        return self._value


_KIND_CTORS = {
    "text": RGA,
    "counter": PNCounter,
    "set": ORSet,
    "register": LWWRegister,
}


class Document:
    def __init__(self, peer_id: str):
        self.peer_id = peer_id
        self.fields: dict = {}  # name -> (kind, instance)

    def add_text(self, name: str) -> RGA:
        return self._add(name, "text")

    def add_counter(self, name: str) -> PNCounter:
        return self._add(name, "counter")

    def add_set(self, name: str) -> ORSet:
        return self._add(name, "set")

    def add_register(self, name: str) -> LWWRegister:
        return self._add(name, "register")

    def _add(self, name: str, kind: str):
        if name in self.fields:
            existing_kind, instance = self.fields[name]
            if existing_kind != kind:
                raise TypeError(f"field {name!r} already exists as {existing_kind!r}, not {kind!r}")
            return instance
        instance = _KIND_CTORS[kind](self.peer_id)
        self.fields[name] = (kind, instance)
        return instance

    def field(self, name: str):
        return self.fields[name][1]

    def snapshot(self) -> dict:
        """Human-readable current value of every field."""
        out = {}
        for name, (kind, inst) in self.fields.items():
            if kind == "text":
                out[name] = inst.text()
            elif kind == "counter":
                out[name] = inst.value()
            elif kind == "set":
                out[name] = inst.values()
            elif kind == "register":
                out[name] = inst.get()
        return out

    # ------------------------------------------------------------------
    # state-based sync (uniform across all field kinds)
    # ------------------------------------------------------------------

    def state(self) -> dict:
        out = {}
        for name, (kind, inst) in self.fields.items():
            if kind == "text":
                out[name] = {"kind": "text", "ops": list(inst.op_log)}
            elif kind == "counter":
                out[name] = {"kind": "counter", "state": inst.state()}
            elif kind == "set":
                out[name] = {"kind": "set", "state": inst.state()}
            elif kind == "register":
                out[name] = {
                    "kind": "register",
                    "id": list(inst._id) if inst._id is not None else None,
                    "value": inst._value,
                }
        return out

    def merge(self, other_state: dict) -> None:
        for name, field_state in other_state.items():
            kind = field_state["kind"]
            if name not in self.fields:
                self._add(name, kind)
            existing_kind, inst = self.fields[name]
            if existing_kind != kind:
                raise TypeError(
                    f"schema conflict on field {name!r}: local={existing_kind!r} remote={kind!r} "
                    f"(concurrent different-typed field creation — see module docstring)"
                )
            if kind == "text":
                buf = CausalDeliveryBuffer(inst.has_id)
                for op in field_state["ops"]:
                    buf.submit(op, inst.apply_remote)
            elif kind in ("counter", "set"):
                inst.merge(field_state["state"])
            elif kind == "register":
                if field_state["id"] is not None:
                    inst._apply(field_state["value"], tuple(field_state["id"]))

    def __repr__(self):
        return f"Document({self.snapshot()!r})"
