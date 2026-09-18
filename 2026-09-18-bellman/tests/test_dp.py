import unittest

from bellman import dp
from bellman.envs.cliffwalking import CliffWalking


class TestDynamicProgramming(unittest.TestCase):
    def setUp(self):
        self.env = CliffWalking()

    def test_value_and_policy_iteration_agree(self):
        vi = dp.value_iteration(self.env)
        pi = dp.policy_iteration(self.env)
        for s in self.env.states:
            self.assertAlmostEqual(vi["V"][s], pi["V"][s], places=6)
            self.assertEqual(vi["policy"][s], pi["policy"][s])

    def test_optimal_value_at_start_is_known(self):
        # The textbook optimal path along the cliff edge is 13 steps at
        # -1/step: V*(start) = -13. This is a known closed-form answer,
        # not just "whatever the code outputs."
        vi = dp.value_iteration(self.env)
        self.assertEqual(vi["V"][self.env.start_state], -13.0)

    def test_converges_in_finite_sweeps(self):
        vi = dp.value_iteration(self.env)
        pi = dp.policy_iteration(self.env)
        self.assertLess(vi["iterations"], 1000)
        self.assertLess(pi["iterations"], 1000)

    def test_policy_evaluation_matches_value_iteration_for_optimal_policy(self):
        vi = dp.value_iteration(self.env)
        evaluated = dp.policy_evaluation(self.env, vi["policy"])
        for s in self.env.states:
            self.assertAlmostEqual(evaluated[s], vi["V"][s], places=6)


if __name__ == "__main__":
    unittest.main()
