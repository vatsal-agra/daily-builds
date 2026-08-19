import unittest

from skein import convergence


class TestShuffleConvergence(unittest.TestCase):
    def test_random_op_set_converges_under_many_shuffles(self):
        from skein.simulate import Simulation

        sim = Simulation(["a", "b", "c"], seed=11)
        for _ in range(40):
            sim.random_edit()
        result = convergence.random_shuffles_converge(sim.all_ops, trials=60, seed=11)
        self.assertTrue(result["ok"], result["mismatches"])

    def test_replay_any_order_raises_on_incomplete_op_set(self):
        from skein.simulate import Simulation

        sim = Simulation(["a"], seed=1)
        sim.type_str("a", 0, "abc")
        # Deliberately drop the first op — its dependents can never resolve.
        incomplete = sim.all_ops[1:]
        with self.assertRaises(AssertionError):
            convergence.replay_any_order(incomplete)


class TestChaosConvergence(unittest.TestCase):
    def test_many_chaos_trials_converge_and_match_oracle(self):
        result = convergence.run_many_chaos_trials(trials=60, seed_base=100)
        self.assertTrue(result["ok"], result["failures"][:2])

    def test_single_chaos_trial_reports_network_stats(self):
        result = convergence.run_chaos_trial(seed=1)
        self.assertTrue(result["ok"])
        self.assertIn("sent", result["network_stats"])
        self.assertGreater(result["num_ops"], 0)

    def test_chaos_trial_without_partitions_still_converges(self):
        result = convergence.run_chaos_trial(seed=2, use_partitions=False)
        self.assertTrue(result["ok"])


if __name__ == "__main__":
    unittest.main()
