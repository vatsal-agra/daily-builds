"""Consistent hashing ring with virtual nodes.

Keys and nodes are hashed onto a fixed 160-bit ring (SHA-1). Each physical
node owns `vnodes` positions on the ring so that adding or removing one
physical node only reshuffles roughly `1/num_nodes` of the keyspace instead
of everything (the whole point of consistent hashing over plain `hash(key)
% num_nodes`).
"""
import bisect
import hashlib


def _hash(s):
    return int(hashlib.sha1(s.encode("utf-8")).hexdigest(), 16)


class HashRing:
    def __init__(self, vnodes=32):
        if vnodes < 1:
            raise ValueError("vnodes must be >= 1")
        self.vnodes = vnodes
        self._points = []  # sorted list of hash values
        self._owners = {}  # hash value -> physical node_id
        self.physical_nodes = set()

    def add_node(self, node_id):
        if node_id in self.physical_nodes:
            return
        self.physical_nodes.add(node_id)
        for i in range(self.vnodes):
            h = _hash(f"{node_id}#{i}")
            # Extremely unlikely SHA-1 collision between two distinct vnodes;
            # if it ever happens, keep the ring's invariant (unique points)
            # by nudging deterministically rather than silently dropping one.
            while h in self._owners:
                h += 1
            bisect.insort(self._points, h)
            self._owners[h] = node_id

    def remove_node(self, node_id):
        if node_id not in self.physical_nodes:
            return
        self.physical_nodes.discard(node_id)
        for i in range(self.vnodes):
            h = _hash(f"{node_id}#{i}")
            while h in self._owners and self._owners[h] != node_id:
                h += 1
            if h in self._owners:
                idx = bisect.bisect_left(self._points, h)
                if idx < len(self._points) and self._points[idx] == h:
                    del self._points[idx]
                del self._owners[h]

    def _walk_order(self, key):
        """Physical node ids in ring order starting at key's position, deduped."""
        if not self._points:
            return []
        h = _hash(key)
        start = bisect.bisect_right(self._points, h) % len(self._points)
        seen = set()
        order = []
        for i in range(len(self._points)):
            point = self._points[(start + i) % len(self._points)]
            node_id = self._owners[point]
            if node_id not in seen:
                seen.add(node_id)
                order.append(node_id)
        return order

    def replicas_for(self, key, n):
        """First n distinct physical nodes walking clockwise from key's hash."""
        return self._walk_order(key)[:n]

    def preference_list(self, key):
        """All physical nodes in ring order for key (used for hinted handoff)."""
        return self._walk_order(key)

    def __len__(self):
        return len(self.physical_nodes)
