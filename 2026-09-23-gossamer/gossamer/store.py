"""Per-node local storage with causal (vector-clock) conflict resolution.

A key maps to a small *antichain* of mutually-concurrent siblings: values
with no causal relationship to each other. Writing a value that causally
descends every current sibling replaces them all. Writing a value that is
causally descended by an existing sibling is a no-op (the write is stale).
Writing a value concurrent with the current siblings adds a new sibling
instead of silently overwriting -- this is the one behavior that makes a
Dynamo-style store different from plain last-write-wins.
"""
import threading
import time

from .vclock import ANCESTOR, DESCENDS, EQUAL


def reduce_siblings(items):
    """Reduce a flat list of (value, VectorClock, ts) to the minimal antichain
    of causally-maximal, pairwise-concurrent siblings."""
    result = []
    for value, vclock, ts in items:
        dominated = False
        kept = []
        for rv, rvc, rts in result:
            cmp = vclock.compare(rvc)
            if cmp == ANCESTOR:
                dominated = True
                kept.append((rv, rvc, rts))
            elif cmp in (DESCENDS, EQUAL):
                continue  # existing sibling superseded by the incoming one
            else:
                kept.append((rv, rvc, rts))
        if not dominated:
            kept.append((value, vclock, ts))
        result = kept
    return result


class LocalStore:
    def __init__(self):
        self._data = {}  # key -> list[(value, VectorClock, ts)]
        self._lock = threading.RLock()

    def put(self, key, value, vclock, ts=None):
        """Returns (accepted, siblings_after). accepted is False iff the
        write was causally stale (dominated by an existing sibling)."""
        item = (value, vclock, ts if ts is not None else time.time())
        with self._lock:
            existing = self._data.get(key, [])
            reduced = reduce_siblings(existing + [item])
            self._data[key] = reduced
            accepted = any(v is item[0] and vc == item[1] for v, vc, _ in reduced)
            return accepted, list(reduced)

    def get(self, key):
        with self._lock:
            return list(self._data.get(key, []))

    def keys(self):
        with self._lock:
            return list(self._data.keys())

    def delete_key(self, key):
        with self._lock:
            self._data.pop(key, None)

    def snapshot(self):
        with self._lock:
            return {k: list(v) for k, v in self._data.items()}

    def __len__(self):
        with self._lock:
            return len(self._data)
