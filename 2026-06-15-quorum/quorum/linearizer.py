"""Linearizability checker for the recorded client-operation history.

A history is *linearizable* if the concurrent operations can be ordered into a
single sequential history that (a) respects real-time order — if op A returns
before op B is called, A precedes B — and (b) matches a sequential specification
of the data type (here, a key/value store).

We use the Wing & Gong search (as popularized by Lowe's algorithm): repeatedly
pick an operation that *could* be linearized next — one that no still-pending
operation must precede — apply it to the model, and recurse, backtracking on
mismatch. Memoization on (remaining-ops, model-state) keeps it tractable.
"""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class HEvent:
    op_id: int
    command: tuple        # ("put", k, v) | ("get", k) | ("del", k)
    result: object
    call: int
    ret: int


def _apply(state: dict, command: tuple):
    """Apply a command to the sequential KV spec; return (new_state, result)."""
    op = command[0]
    if op == "put":
        ns = dict(state)
        ns[command[1]] = command[2]
        return ns, "ok"
    if op == "get":
        return state, state.get(command[1])
    if op == "del":
        ns = dict(state)
        existed = command[1] in ns
        ns.pop(command[1], None)
        return ns, ("ok" if existed else "absent")
    return state, None


class LinearizabilityChecker:
    def __init__(self):
        self.counterexample: list[int] | None = None

    def check(self, events: list[HEvent]) -> bool:
        # Sort for determinism; the search itself explores all valid orders.
        events = sorted(events, key=lambda e: (e.call, e.ret, e.op_id))
        memo: set = set()

        def state_key(state):
            return tuple(sorted(state.items()))

        def search(remaining: tuple, state: dict, prefix: tuple) -> bool:
            if not remaining:
                return True
            mk = (remaining, state_key(state))
            if mk in memo:
                return False
            # Eligible ops: those that no still-pending op must precede. An op o'
            # must precede o iff o'.ret < o.call. So o is eligible iff its call is
            # not after the earliest return among the remaining ops.
            min_ret = min(events_by_id[i].ret for i in remaining)
            progressed = False
            for oid in remaining:
                ev = events_by_id[oid]
                if ev.call > min_ret:
                    continue  # some op must come before this one
                new_state, result = _apply(state, ev.command)
                if result != ev.result:
                    continue  # violates the sequential spec
                progressed = True
                rest = tuple(x for x in remaining if x != oid)
                if search(rest, new_state, prefix + (oid,)):
                    return True
            if not progressed:
                # No eligible op matched the spec: this prefix is the witness.
                self.counterexample = list(prefix)
            memo.add(mk)
            return False

        events_by_id = {e.op_id: e for e in events}
        ok = search(tuple(e.op_id for e in events), {}, ())
        return ok


def history_from_ops(ops) -> list[HEvent]:
    """Build a linearizability history from committed ClientOps."""
    out = []
    for op in ops:
        if not op.committed:
            continue
        out.append(
            HEvent(
                op_id=op.op_id,
                command=op.command,
                result=op.result,
                call=op.call_time,
                ret=op.return_time if op.return_time is not None else op.call_time,
            )
        )
    return out
