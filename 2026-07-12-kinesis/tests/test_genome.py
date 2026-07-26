import random
import unittest

from kinesis.genome import Genome, GenomeNode, MAX_DEPTH, MAX_SEGMENTS


class TestRandomGeneration(unittest.TestCase):
    def test_random_genome_respects_bounds(self):
        rng = random.Random(0)
        for _ in range(20):
            g = Genome.random(rng)
            self.assertLessEqual(g.depth(), MAX_DEPTH)
            self.assertLessEqual(g.node_count(), MAX_SEGMENTS)
            self.assertGreaterEqual(g.node_count(), 1)


class TestSerialization(unittest.TestCase):
    def test_roundtrip_preserves_structure_and_values(self):
        rng = random.Random(1)
        g = Genome.random(rng)
        d = g.to_dict()
        g2 = Genome.from_dict(d)
        self.assertEqual(g.node_count(), g2.node_count())
        self.assertEqual(g.depth(), g2.depth())
        self.assertEqual(g.base_freq, g2.base_freq)
        self.assertEqual(d, g2.to_dict())


class TestMutationAndCrossoverBounds(unittest.TestCase):
    """Regression tests for the adversarial-review finding that
    _repair_bounds's depth-trimming loop always picked the root (whose
    max_subdepth() is, by construction, always the tree's global max)
    and so never actually trimmed anything -- letting depth grow
    unboundedly past MAX_DEPTH after repeated crossover."""

    def test_bounds_hold_across_many_crossover_and_mutate_rounds(self):
        rng = random.Random(0)
        a = Genome.random(rng)
        b = Genome.random(rng)
        for i in range(300):
            child = Genome.crossover(a, b, rng)
            child = child.mutate(rng, rate=0.3)
            self.assertLessEqual(child.depth(), MAX_DEPTH,
                                  f"depth exceeded bound at iteration {i}")
            self.assertLessEqual(child.node_count(), MAX_SEGMENTS,
                                  f"node count exceeded bound at iteration {i}")
            a, b = child, (a if i % 2 == 0 else b)

    def test_crossover_of_two_single_node_genomes_is_a_noop_graft(self):
        a = Genome(GenomeNode(0.5, 0.2), 1.0)
        b = Genome(GenomeNode(0.6, 0.3), 1.2)
        child = Genome.crossover(a, b, random.Random(1))
        self.assertEqual(child.node_count(), 1)

    def test_mutating_a_single_node_genome_many_times_stays_in_bounds(self):
        rng = random.Random(2)
        g = Genome(GenomeNode(0.5, 0.2), 1.0)
        for _ in range(50):
            g = g.mutate(rng, rate=0.3)
            self.assertLessEqual(g.depth(), MAX_DEPTH)
            self.assertLessEqual(g.node_count(), MAX_SEGMENTS)

    def test_add_limb_respects_true_root_relative_depth(self):
        # Regression: _add_limb used to check a node's *local* subtree
        # height (always 1 for any leaf) instead of its real depth from
        # root, so it could extend nodes that were already at MAX_DEPTH.
        rng = random.Random(3)
        for _ in range(50):
            g = Genome.random(rng, max_depth=MAX_DEPTH)
            mutated = g.mutate(rng, rate=1.0)  # force heavy mutation pressure
            self.assertLessEqual(mutated.depth(), MAX_DEPTH)


if __name__ == "__main__":
    unittest.main()
