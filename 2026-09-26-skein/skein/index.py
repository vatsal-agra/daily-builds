"""In-memory indexes: a label -> node-id index and per-(label, property)
sorted indexes supporting equality and range lookups.
"""
import bisect

NEG = float("-inf")
POS = float("inf")


class LabelIndex:
    def __init__(self):
        self._map = {}

    def add(self, node_id, labels):
        for label in labels:
            self._map.setdefault(label, set()).add(node_id)

    def remove(self, node_id, labels):
        for label in labels:
            bucket = self._map.get(label)
            if bucket is not None:
                bucket.discard(node_id)
                if not bucket:
                    del self._map[label]

    def get(self, label):
        return frozenset(self._map.get(label, ()))

    def labels(self):
        return list(self._map.keys())

    def has_label(self, label):
        return label in self._map


def values_equal(a, b) -> bool:
    """Equality consistent with PropertyIndex's ordering: bool, number,
    and string form distinct rank groups (Python's `True == 1` does NOT
    hold here). Used for pattern property-map filters so an index-backed
    lookup and a full scan of the same filter always agree -- without
    this, `{active: 1}` would match a `True` property under a scan
    (Python equality) but not under an index (rank-separated), a silent
    divergence between two supposedly-equivalent query plans.
    """
    return _rank_val(a) == _rank_val(b)


def _rank_val(value):
    """A total order across heterogeneous property types: None < bool <
    number < string. Keeps a single sorted index usable for any column
    without Python raising on cross-type comparisons.
    """
    if value is None:
        return (0, 0)
    if isinstance(value, bool):
        return (1, int(value))
    if isinstance(value, (int, float)):
        return (2, float(value))
    return (3, str(value))


class PropertyIndex:
    """Sorted (rank, value, node_id) triples supporting O(log n) equality
    and range queries via bisect. Only meaningful ordering is within a
    single value type; that's the common case for a real property column.
    """

    def __init__(self):
        self._entries = []

    def __len__(self):
        return len(self._entries)

    def _key(self, value, node_id):
        rank, val = _rank_val(value)
        return (rank, val, node_id)

    def add(self, value, node_id):
        key = self._key(value, node_id)
        i = bisect.bisect_left(self._entries, key)
        if i < len(self._entries) and self._entries[i] == key:
            return  # already present: keeps replay of an interrupted
            # checkpoint (snapshot written, WAL not yet truncated before a
            # crash) idempotent instead of inserting a ghost duplicate.
        self._entries.insert(i, key)

    def remove(self, value, node_id):
        key = self._key(value, node_id)
        i = bisect.bisect_left(self._entries, key)
        if i < len(self._entries) and self._entries[i] == key:
            self._entries.pop(i)
            return
        # Defensive fallback: should not trigger in normal operation, but
        # guards against ever silently leaving a stale index entry behind.
        for j, entry in enumerate(self._entries):
            if entry[2] == node_id and entry[:2] == (self._key(value, node_id)[0], self._key(value, node_id)[1]):
                self._entries.pop(j)
                return

    def eq(self, value):
        rank, val = _rank_val(value)
        lo = bisect.bisect_left(self._entries, (rank, val, NEG))
        hi = bisect.bisect_right(self._entries, (rank, val, POS))
        return [e[2] for e in self._entries[lo:hi]]

    def range(self, gt=None, gte=None, lt=None, lte=None):
        lo_idx, hi_idx = 0, len(self._entries)
        if gte is not None:
            rank, val = _rank_val(gte)
            lo_idx = max(lo_idx, bisect.bisect_left(self._entries, (rank, val, NEG)))
        if gt is not None:
            rank, val = _rank_val(gt)
            lo_idx = max(lo_idx, bisect.bisect_right(self._entries, (rank, val, POS)))
        if lte is not None:
            rank, val = _rank_val(lte)
            hi_idx = min(hi_idx, bisect.bisect_right(self._entries, (rank, val, POS)))
        if lt is not None:
            rank, val = _rank_val(lt)
            hi_idx = min(hi_idx, bisect.bisect_left(self._entries, (rank, val, NEG)))
        return [e[2] for e in self._entries[lo_idx:hi_idx]]
