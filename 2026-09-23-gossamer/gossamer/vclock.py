"""Vector clocks: real causal reasoning, not last-write-wins timestamps."""

EQUAL = "equal"
DESCENDS = "descends"       # self is strictly newer than other
ANCESTOR = "ancestor"       # self is strictly older than other
CONCURRENT = "concurrent"   # neither dominates -> a genuine conflict


class VectorClock:
    __slots__ = ("counters",)

    def __init__(self, counters=None):
        self.counters = dict(counters) if counters else {}

    def increment(self, node_id):
        c = dict(self.counters)
        c[node_id] = c.get(node_id, 0) + 1
        return VectorClock(c)

    def compare(self, other):
        self_ge_other = all(self.counters.get(k, 0) >= v for k, v in other.counters.items())
        other_ge_self = all(other.counters.get(k, 0) >= v for k, v in self.counters.items())
        if self_ge_other and other_ge_self:
            return EQUAL
        if self_ge_other:
            return DESCENDS
        if other_ge_self:
            return ANCESTOR
        return CONCURRENT

    def merge(self, other):
        keys = set(self.counters) | set(other.counters)
        return VectorClock({k: max(self.counters.get(k, 0), other.counters.get(k, 0)) for k in keys})

    @staticmethod
    def merge_all(clocks):
        result = VectorClock()
        for c in clocks:
            result = result.merge(c)
        return result

    def to_dict(self):
        return dict(self.counters)

    @classmethod
    def from_dict(cls, d):
        return cls(d)

    def __eq__(self, other):
        return isinstance(other, VectorClock) and self.counters == other.counters

    def __hash__(self):
        return hash(tuple(sorted(self.counters.items())))

    def __repr__(self):
        return f"VectorClock({self.counters!r})"
