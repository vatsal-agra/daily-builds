import random
import unittest

from gossamer.hashring import HashRing


class TestHashRing(unittest.TestCase):
    def test_empty_ring(self):
        ring = HashRing(vnodes=8)
        self.assertEqual(ring.replicas_for("k", 3), [])

    def test_single_node(self):
        ring = HashRing(vnodes=8)
        ring.add_node("a")
        self.assertEqual(ring.replicas_for("k", 3), ["a"])

    def test_replicas_are_distinct_physical_nodes(self):
        ring = HashRing(vnodes=16)
        for n in ["a", "b", "c", "d", "e"]:
            ring.add_node(n)
        for key in ["foo", "bar", "baz", "qux", "1234", "a-long-key-name"]:
            reps = ring.replicas_for(key, 3)
            self.assertEqual(len(reps), 3)
            self.assertEqual(len(set(reps)), 3)

    def test_replicas_capped_at_physical_node_count(self):
        ring = HashRing(vnodes=8)
        ring.add_node("a")
        ring.add_node("b")
        self.assertEqual(len(ring.replicas_for("k", 5)), 2)

    def test_preference_list_contains_all_nodes_in_ring_order(self):
        ring = HashRing(vnodes=8)
        nodes = ["a", "b", "c", "d"]
        for n in nodes:
            ring.add_node(n)
        pref = ring.preference_list("some-key")
        self.assertEqual(set(pref), set(nodes))
        self.assertEqual(len(pref), len(nodes))

    def test_deterministic(self):
        ring1 = HashRing(vnodes=16)
        ring2 = HashRing(vnodes=16)
        for n in ["a", "b", "c"]:
            ring1.add_node(n)
            ring2.add_node(n)
        for key in ["x", "y", "z", "abc123"]:
            self.assertEqual(ring1.replicas_for(key, 2), ring2.replicas_for(key, 2))

    def test_removing_a_node_only_moves_its_own_share_of_keys(self):
        # Property test: with N virtual nodes, adding/removing one physical
        # node out of many should reshuffle roughly 1/num_nodes of keys, not
        # everything -- the entire point of consistent hashing over
        # hash(key) % num_nodes.
        ring = HashRing(vnodes=64)
        node_ids = [f"node-{i}" for i in range(10)]
        for n in node_ids:
            ring.add_node(n)

        random.seed(42)
        keys = [f"key-{i}" for i in range(5000)]
        before = {k: ring.replicas_for(k, 3) for k in keys}

        ring.remove_node("node-5")

        after = {k: ring.replicas_for(k, 3) for k in keys}

        moved = sum(1 for k in keys if before[k] != after[k])
        fraction_moved = moved / len(keys)
        # With 3 replicas per key out of 10 nodes, node-5 is expected to be
        # a replica owner for ~3/10 of keys (that's the fraction that can
        # possibly move); must not be anywhere near "all keys reshuffled".
        self.assertLess(fraction_moved, 0.45)
        self.assertGreater(fraction_moved, 0.02)

        # Every key that moved must have had "node-5" in its old replica
        # set -- removing an uninvolved node should never perturb a key
        # that didn't route through it.
        for k in keys:
            if before[k] != after[k]:
                self.assertIn("node-5", before[k])

    def test_adding_a_node_only_steals_keys_it_now_owns(self):
        ring = HashRing(vnodes=64)
        node_ids = [f"node-{i}" for i in range(9)]
        for n in node_ids:
            ring.add_node(n)

        keys = [f"key-{i}" for i in range(5000)]
        before = {k: ring.replicas_for(k, 3) for k in keys}

        ring.add_node("node-new")
        after = {k: ring.replicas_for(k, 3) for k in keys}

        for k in keys:
            if before[k] != after[k]:
                self.assertIn("node-new", after[k])

    def test_uniform_load_distribution(self):
        ring = HashRing(vnodes=64)
        node_ids = [f"node-{i}" for i in range(8)]
        for n in node_ids:
            ring.add_node(n)

        counts = {n: 0 for n in node_ids}
        for i in range(20000):
            owner = ring.replicas_for(f"key-{i}", 1)[0]
            counts[owner] += 1

        expected = 20000 / len(node_ids)
        for n, c in counts.items():
            self.assertGreater(c, expected * 0.5, f"{n} got {c}, expected ~{expected}")
            self.assertLess(c, expected * 1.5, f"{n} got {c}, expected ~{expected}")


if __name__ == "__main__":
    unittest.main()
