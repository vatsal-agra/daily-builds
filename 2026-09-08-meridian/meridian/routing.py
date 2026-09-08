"""The k-bucket routing table.

Real Kademlia fidelity matters here, specifically the "prefer old contacts
over new ones" eviction rule from the original paper (Maymounkov & Mazieres,
2002, S4.1): when a bucket is full and a new contact shows up, the *least*
recently seen contact is pinged. If it answers, it's moved to the most-
recently-seen end and the new contact is dropped (kept in a small
replacement cache instead). Only if the ping times out does the new contact
replace it. This is deliberate -- nodes that have been up a long time are
statistically likely to stay up, so long-lived contacts are trusted over
unverified new ones. It's also what makes flooding a target's routing table
with throwaway Sybil nodes hard: you can't evict a bucket just by showing up.
"""
from __future__ import annotations

from collections import OrderedDict

from .nodeid import bucket_index, distance

DEFAULT_K = 20


class KBucket:
    """One bucket: up to `k` live contacts (LRU-ordered, least-recently-seen
    at the head) plus a small replacement cache of overflow candidates."""

    def __init__(self, k: int = DEFAULT_K):
        self.k = k
        self.contacts: "OrderedDict[int, None]" = OrderedDict()
        self.replacement: "OrderedDict[int, None]" = OrderedDict()
        self.last_refreshed = 0

    def __len__(self) -> int:
        return len(self.contacts)

    def __contains__(self, node_id: int) -> bool:
        return node_id in self.contacts

    def all_ids(self) -> list[int]:
        return list(self.contacts.keys())

    def head(self) -> int | None:
        """The least-recently-seen contact -- the one to ping before
        evicting, per the rule above."""
        return next(iter(self.contacts), None)

    def touch(self, node_id: int) -> str:
        """Record contact with `node_id`. Returns one of:
        - 'updated'   already in the bucket, moved to most-recently-seen
        - 'inserted'  bucket had room, added directly
        - 'full'      bucket is full; `node_id` was placed in the
                       replacement cache and the caller must ping head()
                       to decide whether to evict it
        """
        if node_id in self.contacts:
            self.contacts.move_to_end(node_id)
            return "updated"
        if len(self.contacts) < self.k:
            self.contacts[node_id] = None
            self.replacement.pop(node_id, None)
            return "inserted"
        self.replacement.pop(node_id, None)
        self.replacement[node_id] = None
        while len(self.replacement) > self.k:
            self.replacement.popitem(last=False)
        return "full"

    def replace_head_with(self, old_id: int, new_id: int) -> bool:
        """The contact `old_id` -- which must have been the head at the
        moment it was pinged -- failed to answer: evict it and promote
        `new_id` into its slot. Takes the *specific* contact to evict
        rather than just popping "whichever contact is head() right now",
        because by the time a ping's response/timeout comes back, a
        second, independent full-bucket episode may already have replaced
        the head with someone else -- blindly evicting "the current head"
        at resolution time could then evict the wrong (and possibly
        perfectly healthy) contact. Returns False (a no-op) if `old_id`
        is no longer present, e.g. because that other episode already
        resolved first."""
        if old_id not in self.contacts:
            return False
        del self.contacts[old_id]
        self.contacts[new_id] = None
        self.replacement.pop(new_id, None)
        return True

    def remove(self, node_id: int) -> bool:
        """Drop a contact outright (used when a graceful leave is observed
        directly). Promotes the freshest replacement candidate into the
        freed slot, if one is waiting."""
        if node_id not in self.contacts:
            return False
        del self.contacts[node_id]
        if self.replacement and len(self.contacts) < self.k:
            promoted, _ = self.replacement.popitem(last=True)
            self.contacts[promoted] = None
        return True


class RoutingTable:
    """The full set of 160 k-buckets for one node."""

    def __init__(self, self_id: int, k: int = DEFAULT_K):
        self.id = self_id
        self.k = k
        self.buckets = [KBucket(k) for _ in range(160)]

    def record(self, other_id: int) -> tuple[str, dict]:
        """Record contact with `other_id`. Returns (status, info):
        - ('self', {})                          other_id is us; ignored
        - ('updated'|'inserted', {'idx': i})     handled, no action needed
        - ('ping_head', {'idx': i, 'head': h})   caller must ping contact
                                                  `h` and call
                                                  resolve_ping_head() with
                                                  the outcome
        """
        idx = bucket_index(self.id, other_id)
        if idx is None:
            return "self", {}
        bucket = self.buckets[idx]
        status = bucket.touch(other_id)
        if status == "full":
            return "ping_head", {"idx": idx, "head": bucket.head()}
        return status, {"idx": idx}

    def resolve_ping_head(self, idx: int, candidate_id: int, pinged_head_id: int, head_alive: bool) -> None:
        """Finish a deferred 'ping_head' decision for the specific contact
        `pinged_head_id` that was actually pinged. If it answered, it's
        kept (already moved to MRU by the ping's own record() call); if it
        didn't, the candidate takes its place -- but only if
        `pinged_head_id` is still there to evict (see replace_head_with)."""
        if not head_alive:
            self.buckets[idx].replace_head_with(pinged_head_id, candidate_id)

    def remove(self, other_id: int) -> bool:
        idx = bucket_index(self.id, other_id)
        if idx is None:
            return False
        return self.buckets[idx].remove(other_id)

    def closest(self, target_id: int, count: int) -> list[int]:
        """The `count` known contacts closest to `target_id` by XOR
        distance, across all buckets. A demo-scale network (dozens to a
        few hundred nodes, at most k=20-ish contacts per bucket) makes a
        full flatten-and-sort cheap enough that a fancier indexed
        structure would be premature optimization."""
        all_ids = []
        for bucket in self.buckets:
            all_ids.extend(bucket.all_ids())
        all_ids.sort(key=lambda nid: distance(target_id, nid))
        return all_ids[:count]

    def contact_count(self) -> int:
        return sum(len(b) for b in self.buckets)

    def non_empty_buckets(self) -> list[int]:
        return [i for i, b in enumerate(self.buckets) if len(b) > 0]
