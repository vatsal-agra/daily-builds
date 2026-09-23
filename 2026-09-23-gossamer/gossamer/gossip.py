"""Heartbeat gossip + local failure detection.

Each node keeps a purely local view: a heartbeat counter per known node, and
the wall-clock time it last personally observed that counter increase.
Gossip only ever exchanges *counters* between nodes -- never a "status"
opinion -- because whether a node is alive/suspected/dead is derived locally
from elapsed wall-clock time since a node's own last observation. That's the
real point of a decentralized failure detector: no node's status is decided
anywhere but on the node computing it.
"""
import threading
import time

ALIVE = "alive"
SUSPECTED = "suspected"
DEAD = "dead"


class Membership:
    def __init__(self, self_id, all_node_ids, suspect_timeout=3.0, dead_timeout=8.0):
        self.self_id = self_id
        self.suspect_timeout = suspect_timeout
        self.dead_timeout = dead_timeout
        now = time.time()
        self._heartbeats = {nid: 0 for nid in all_node_ids}
        self._last_seen = {nid: now for nid in all_node_ids}
        self._lock = threading.RLock()

    def tick_self(self):
        with self._lock:
            self._heartbeats[self.self_id] += 1
            self._last_seen[self.self_id] = time.time()

    def snapshot_heartbeats(self):
        with self._lock:
            return dict(self._heartbeats)

    def merge(self, other_heartbeats):
        """Merge a peer's heartbeat counters into ours. Returns the list of
        node_ids that transitioned from non-alive to alive as a result
        (i.e. a real revival this node just learned about), so the caller
        can trigger a hinted-handoff flush."""
        now = time.time()
        revived = []
        with self._lock:
            for nid, hb in other_heartbeats.items():
                if nid == self.self_id:
                    continue
                prev_hb = self._heartbeats.get(nid)
                if prev_hb is None or hb > prev_hb:
                    was_alive = self._status_of_locked(nid, now) == ALIVE
                    self._heartbeats[nid] = hb
                    self._last_seen[nid] = now
                    if not was_alive:
                        revived.append(nid)
        return revived

    def _status_of_locked(self, nid, now):
        if nid == self.self_id:
            return ALIVE
        if nid not in self._last_seen:
            return DEAD
        elapsed = now - self._last_seen[nid]
        if elapsed > self.dead_timeout:
            return DEAD
        if elapsed > self.suspect_timeout:
            return SUSPECTED
        return ALIVE

    def status_of(self, nid):
        with self._lock:
            return self._status_of_locked(nid, time.time())

    def is_alive(self, nid):
        return self.status_of(nid) == ALIVE

    def all_statuses(self):
        now = time.time()
        with self._lock:
            return {nid: self._status_of_locked(nid, now) for nid in self._heartbeats}

    def known_nodes(self):
        with self._lock:
            return list(self._heartbeats.keys())
