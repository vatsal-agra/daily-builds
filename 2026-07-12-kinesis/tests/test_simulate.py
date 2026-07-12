import random
import unittest

from kinesis.genome import Genome, GenomeNode
from kinesis.simulate import run_simulation
from kinesis.physics import World


class TestBasicSimulation(unittest.TestCase):
    def test_single_node_genome_stays_put_and_upright(self):
        g = Genome(GenomeNode(0.5, 0.2), 1.0)
        r = run_simulation(g, duration=2.0, record_trace=True)
        self.assertFalse(r.toppled)
        self.assertLess(abs(r.distance), 1e-3)
        self.assertGreater(len(r.trace), 0)

    def test_zero_duration_is_a_clean_noop(self):
        g = Genome.random(random.Random(3))
        r = run_simulation(g, duration=0.0, record_trace=True)
        self.assertEqual(r.fitness, 0.0)
        self.assertEqual(r.trace, [])

    def test_fitness_never_exceeds_distance_minus_energy_unless_toppled(self):
        rng = random.Random(5)
        for _ in range(6):
            g = Genome.random(rng)
            r = run_simulation(g, duration=1.5)
            expected = r.distance - 0.0025 * r.energy - (1.0 if r.toppled else 0.0)
            self.assertAlmostEqual(r.fitness, expected, places=6)


class TestNaNSentinel(unittest.TestCase):
    """Regression test: a numerically unstable genome must report a
    clean finite fitness sentinel, never NaN. NaN would silently corrupt
    GA selection because max(..., key=...) treats every NaN comparison
    as False, so a NaN that lands first in iteration order can never be
    beaten by a later, genuinely-finite individual."""

    def test_nan_positions_produce_finite_sentinel_not_nan(self):
        orig_step = World.step
        calls = [0]

        def poisoned_step(self, dt):
            calls[0] += 1
            orig_step(self, dt)
            if calls[0] == 20:
                b = self.bodies[0]
                b.pos = (float("nan"), b.pos[1])

        World.step = poisoned_step
        try:
            g = Genome.random(random.Random(9))
            r = run_simulation(g, duration=2.0, record_trace=True)
        finally:
            World.step = orig_step

        self.assertEqual(r.fitness, -1e6)
        self.assertEqual(r.distance, 0.0)
        self.assertTrue(r.toppled)
        self.assertEqual(r.trace, [])
        self.assertFalse(r.fitness != r.fitness)  # not NaN


class TestToppleDetection(unittest.TestCase):
    def test_toppled_flag_is_boolean_and_consistent_with_fitness_penalty(self):
        rng = random.Random(11)
        saw_toppled = False
        saw_upright = False
        for _ in range(12):
            g = Genome.random(rng)
            r = run_simulation(g, duration=3.0)
            self.assertIsInstance(r.toppled, bool)
            if r.toppled:
                saw_toppled = True
            else:
                saw_upright = True
        # sanity: a batch of random genomes should show both outcomes,
        # otherwise the topple detector (or the physics driving it) is
        # certainly broken in some direction
        self.assertTrue(saw_toppled)
        self.assertTrue(saw_upright)


if __name__ == "__main__":
    unittest.main()
