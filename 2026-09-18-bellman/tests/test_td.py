import unittest

from bellman import convergence, dp, td
from bellman.envs.cliffwalking import CliffWalking
from bellman.utils import rollout_policy


class TestTDControl(unittest.TestCase):
    def setUp(self):
        self.env = CliffWalking()
        self.optimal_value = dp.value_iteration(self.env)["V"][self.env.start_state]

    def test_qlearning_matches_dp_optimum(self):
        result = td.q_learning(self.env, episodes=500, alpha=0.5, epsilon=0.1, seed=42)
        exact = dp.policy_evaluation(self.env, result["policy"])[self.env.start_state]
        self.assertEqual(exact, self.optimal_value)

    def test_sarsa_takes_the_safe_longer_path(self):
        result = td.sarsa(self.env, episodes=500, alpha=0.5, epsilon=0.1, seed=42)
        exact = dp.policy_evaluation(self.env, result["policy"])[self.env.start_state]
        # SARSA's on-policy safety detour must be a real detour (strictly
        # worse than optimal) but still a reasonable, working path.
        self.assertLess(exact, self.optimal_value)
        self.assertGreater(exact, self.optimal_value - 20)

    def test_qlearning_greedy_rollout_reaches_goal(self):
        result = td.q_learning(self.env, episodes=500, alpha=0.5, epsilon=0.1, seed=42)
        _, _, reached = rollout_policy(self.env, result["policy"])
        self.assertTrue(reached)

    def test_sarsa_lambda_reaches_a_working_policy(self):
        result = td.sarsa_lambda(self.env, episodes=500, alpha=0.1, epsilon=0.1, lam=0.9, seed=42)
        _, _, reached = rollout_policy(self.env, result["policy"])
        self.assertTrue(reached)

    def test_sarsa_lambda_converges_faster_than_sarsa(self):
        checkpoints = [10, 25, 50, 75, 100, 150, 200, 300, 400, 500]
        shared = dict(alpha=0.1, epsilon=0.1, seed=42)
        sarsa_crossing, _ = convergence.episodes_to_threshold(
            self.env, td.sarsa, checkpoints, -20.0, **shared
        )
        lambda_crossing, _ = convergence.episodes_to_threshold(
            self.env, td.sarsa_lambda, checkpoints, -20.0, lam=0.9, **shared
        )
        self.assertIsNotNone(lambda_crossing)
        self.assertTrue(sarsa_crossing is None or lambda_crossing < sarsa_crossing)

    def test_invalid_action_raises(self):
        with self.assertRaises(ValueError):
            self.env.step(self.env.start_state, 99)


if __name__ == "__main__":
    unittest.main()
