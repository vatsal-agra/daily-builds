import unittest

from meridian.nodeid import distance
from meridian.routing import KBucket, RoutingTable


class TestKBucket(unittest.TestCase):
    def test_insert_until_full(self):
        b = KBucket(k=3)
        self.assertEqual(b.touch(1), "inserted")
        self.assertEqual(b.touch(2), "inserted")
        self.assertEqual(b.touch(3), "inserted")
        self.assertEqual(len(b), 3)

    def test_touch_existing_moves_to_tail(self):
        b = KBucket(k=3)
        for i in (1, 2, 3):
            b.touch(i)
        self.assertEqual(b.head(), 1)
        b.touch(1)  # re-seen -> most-recently-seen, no longer head
        self.assertEqual(b.head(), 2)

    def test_full_bucket_queues_replacement_not_insert(self):
        b = KBucket(k=2)
        b.touch(1)
        b.touch(2)
        status = b.touch(3)
        self.assertEqual(status, "full")
        self.assertEqual(sorted(b.all_ids()), [1, 2])
        self.assertIn(3, b.replacement)

    def test_replace_head_evicts_lru_contact(self):
        b = KBucket(k=2)
        b.touch(1)
        b.touch(2)
        b.touch(3)  # full -> goes to replacement
        self.assertEqual(b.head(), 1)  # 1 was least-recently-seen
        swapped = b.replace_head_with(1, 3)
        self.assertTrue(swapped)
        self.assertEqual(sorted(b.all_ids()), [2, 3])
        self.assertNotIn(3, b.replacement)

    def test_replace_head_with_is_a_no_op_if_old_id_already_gone(self):
        b = KBucket(k=2)
        b.touch(1)
        b.touch(2)
        b.touch(3)  # queued in replacement
        swapped = b.replace_head_with(999, 3)  # 999 was never a contact
        self.assertFalse(swapped)
        self.assertEqual(sorted(b.all_ids()), [1, 2])  # untouched

    def test_replacement_cache_is_capped_at_k(self):
        b = KBucket(k=2)
        b.touch(1)
        b.touch(2)
        for extra in (3, 4, 5, 6):
            b.touch(extra)
        self.assertLessEqual(len(b.replacement), 2)
        # the most recently queued replacements survive, oldest overflow is dropped
        self.assertIn(6, b.replacement)
        self.assertIn(5, b.replacement)

    def test_remove_promotes_best_replacement(self):
        b = KBucket(k=2)
        b.touch(1)
        b.touch(2)
        b.touch(3)  # queued as replacement while full
        self.assertTrue(b.remove(1))
        self.assertEqual(sorted(b.all_ids()), [2, 3])

    def test_remove_missing_contact_is_false(self):
        b = KBucket(k=2)
        b.touch(1)
        self.assertFalse(b.remove(999))


class TestRoutingTable(unittest.TestCase):
    def test_self_id_ignored(self):
        rt = RoutingTable(self_id=42, k=5)
        status, info = rt.record(42)
        self.assertEqual(status, "self")

    def test_insert_and_closest(self):
        rt = RoutingTable(self_id=0, k=20)
        ids = [1, 2, 5, 100, 1 << 40, 1 << 100]
        for i in ids:
            rt.record(i)
        closest3 = rt.closest(target_id=0, count=3)
        expected = sorted(ids, key=lambda x: distance(0, x))[:3]
        self.assertEqual(closest3, expected)

    def test_closest_matches_brute_force_over_random_ids(self):
        import random

        r = random.Random(11)
        rt = RoutingTable(self_id=0, k=20)
        ids = set()
        while len(ids) < 200:
            ids.add(r.getrandbits(160))
        for i in ids:
            rt.record(i)
        target = r.getrandbits(160)
        got = rt.closest(target, 10)
        # k=20 per bucket may not retain every one of 200 ids if some
        # collide into over-full buckets, so compare against what the
        # table actually retained, not the full random set.
        retained = [nid for bucket in rt.buckets for nid in bucket.all_ids()]
        expected = sorted(retained, key=lambda nid: distance(target, nid))[:10]
        self.assertEqual(got, expected)

    def test_full_bucket_triggers_ping_head(self):
        rt = RoutingTable(self_id=0, k=2)
        # ids 1..4 are all adjacent to 0 -> all land in bucket 0/1 mix;
        # pick values that all share the same bucket index deterministically:
        # distance in [4, 8) -> bucket index 2
        for i in (4, 5):
            status, info = rt.record(i)
            self.assertIn(status, ("inserted",))
        status, info = rt.record(6)
        self.assertEqual(status, "ping_head")
        self.assertEqual(info["idx"], 2)
        self.assertEqual(info["head"], 4)  # 4 was inserted first -> least recently seen

    def test_resolve_ping_head_keeps_alive_head(self):
        rt = RoutingTable(self_id=0, k=2)
        rt.record(4)
        rt.record(5)
        rt.record(6)  # queued as candidate, head=4
        rt.resolve_ping_head(idx=2, candidate_id=6, pinged_head_id=4, head_alive=True)
        self.assertEqual(sorted(rt.buckets[2].all_ids()), [4, 5])

    def test_resolve_ping_head_evicts_dead_head(self):
        rt = RoutingTable(self_id=0, k=2)
        rt.record(4)
        rt.record(5)
        rt.record(6)
        rt.resolve_ping_head(idx=2, candidate_id=6, pinged_head_id=4, head_alive=False)
        self.assertEqual(sorted(rt.buckets[2].all_ids()), [5, 6])

    def test_overlapping_ping_episodes_never_evict_the_wrong_contact(self):
        """Regression test for a real bug found in adversarial review: two
        candidates (6, 7) both show up while the bucket [4, 5] is full,
        before either ping resolves -- both trigger their own independent
        ping-the-head episode against contact 4. If contact 4 really is
        dead, the first episode to resolve should evict *it* specifically;
        the second, now-redundant episode must not then evict contact 5
        (which was never pinged and may be perfectly healthy) just because
        it happens to be head() by the time it resolves."""
        rt = RoutingTable(self_id=0, k=2)
        rt.record(4)
        rt.record(5)
        status6, info6 = rt.record(6)  # bucket full -> ping_head against 4
        status7, info7 = rt.record(7)  # also full -> a second, independent ping_head against 4
        self.assertEqual((status6, status7), ("ping_head", "ping_head"))
        self.assertEqual(info6["head"], 4)
        self.assertEqual(info7["head"], 4)

        # first episode resolves: 4 really is dead -> evicted, 6 takes its place
        rt.resolve_ping_head(idx=2, candidate_id=6, pinged_head_id=4, head_alive=False)
        self.assertEqual(sorted(rt.buckets[2].all_ids()), [5, 6])

        # second, now-stale episode resolves for the same (already-handled)
        # dead contact 4 -- must be a no-op, not evict healthy contact 5
        rt.resolve_ping_head(idx=2, candidate_id=7, pinged_head_id=4, head_alive=False)
        self.assertEqual(sorted(rt.buckets[2].all_ids()), [5, 6])

    def test_remove_and_non_empty_buckets(self):
        rt = RoutingTable(self_id=0, k=5)
        rt.record(1)
        rt.record(1 << 50)
        self.assertEqual(len(rt.non_empty_buckets()), 2)
        self.assertTrue(rt.remove(1))
        self.assertEqual(len(rt.non_empty_buckets()), 1)

    def test_contact_count(self):
        rt = RoutingTable(self_id=0, k=5)
        for i in (1, 2, 3):
            rt.record(i)
        self.assertEqual(rt.contact_count(), 3)


if __name__ == "__main__":
    unittest.main()
