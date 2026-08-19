import unittest

from skein.simulate import Simulation


class TestSimulationBasics(unittest.TestCase):
    def test_type_and_delete_broadcast_and_converge(self):
        sim = Simulation(["a", "b", "c"], seed=1)
        sim.type_str("a", 0, "hello")
        sim.drain()
        self.assertTrue(sim.converged())
        self.assertEqual(sim.texts()["b"], "hello")

    def test_random_edit_never_deletes_from_empty_doc(self):
        sim = Simulation(["a", "b"], seed=2)
        for _ in range(50):
            sim.random_edit()  # must never IndexError, even starting from an empty doc
        sim.drain()
        self.assertTrue(sim.converged())

    def test_delete_range_valid(self):
        sim = Simulation(["a", "b"], seed=3)
        sim.type_str("a", 0, "hello")
        sim.drain()
        sim.delete_range("a", 1, 3)  # remove 'ell'
        sim.drain()
        self.assertEqual(sim.sites["a"].text, "ho")
        self.assertTrue(sim.converged())


class TestDeleteRangeAtomicityRegression(unittest.TestCase):
    """Regression test for REVIEW.md addendum bug #4: an oversized
    delete_range used to partially apply (and broadcast!) before
    raising, silently wiping every replica's document."""

    def test_oversized_range_raises_and_touches_nothing(self):
        sim = Simulation(["a", "b"], seed=4)
        sim.type_str("a", 0, "hello")
        sim.drain()

        with self.assertRaises(IndexError):
            sim.delete_range("a", 0, 9999)

        sim.drain()
        self.assertEqual(sim.sites["a"].text, "hello", "the origin site must be untouched")
        self.assertEqual(sim.sites["b"].text, "hello", "nothing must have been broadcast to other replicas either")

    def test_negative_and_out_of_range_pos_rejected(self):
        sim = Simulation(["a", "b"], seed=5)
        sim.type_str("a", 0, "hi")
        with self.assertRaises(IndexError):
            sim.delete_range("a", -1, 1)
        with self.assertRaises(IndexError):
            sim.delete_range("a", 5, 1)
        self.assertEqual(sim.sites["a"].text, "hi")

    def test_zero_count_is_a_harmless_noop(self):
        sim = Simulation(["a", "b"], seed=6)
        sim.type_str("a", 0, "hi")
        ops = sim.delete_range("a", 0, 0)
        self.assertEqual(ops, [])
        self.assertEqual(sim.sites["a"].text, "hi")


if __name__ == "__main__":
    unittest.main()
