import unittest

from bellman.envs import GridWorldEnv
from bellman.dp import (
    value_iteration, policy_iteration, greedy_rollout_return,
    blackjack_optimal_policy,
)


class TestGridWorldDP(unittest.TestCase):
    """Ground-truth checks: the classic Sutton & Barto Cliff Walking result
    is a known constant (optimal path cost -13) -- this is the fixed point
    every learning algorithm in the project is graded against."""

    def test_value_iteration_matches_known_optimal_cliff_walking_return(self):
        env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0)
        V, policy = value_iteration(env, gamma=1.0)
        self.assertAlmostEqual(V[env.encode(*env.start)], -13.0, places=4)
        self.assertAlmostEqual(greedy_rollout_return(env, policy), -13.0, places=4)

    def test_policy_iteration_agrees_with_value_iteration(self):
        env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0)
        V_vi, _ = value_iteration(env, gamma=1.0)
        V_pi, policy_pi = policy_iteration(env, gamma=1.0)
        for s in env.states:
            self.assertAlmostEqual(V_vi[s], V_pi[s], places=3, msg=f"state {s}")
        self.assertAlmostEqual(greedy_rollout_return(env, policy_pi), -13.0, places=4)

    def test_optimal_policy_never_steps_into_the_cliff(self):
        env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0)
        _, policy = value_iteration(env, gamma=1.0)
        s = env.reset()
        for _ in range(100):
            a = policy[s]
            ns, r, done, _ = env.step(a)
            self.assertNotEqual(r, -100.0, "optimal policy should never fall off the cliff")
            s = ns
            if done:
                break
        else:
            self.fail("optimal policy never reached the goal within 100 steps")

    def test_stochastic_slip_increases_optimal_cost(self):
        # A slippery grid can't do strictly better than the deterministic one
        # (more randomness in the same reward structure can only hurt or match).
        det_env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0)
        V_det, _ = value_iteration(det_env, gamma=1.0)
        slip_env = GridWorldEnv(rows=4, cols=12, slip_prob=0.2)
        V_slip, _ = value_iteration(slip_env, gamma=1.0)
        self.assertLessEqual(V_slip[slip_env.encode(*slip_env.start)],
                              V_det[det_env.encode(*det_env.start)] + 1e-6)

    def test_smaller_grid_sanity(self):
        # 3x4 grid: start (2,0), goal (2,3), cliff (2,1),(2,2). The cliff
        # blocks row 2, so the shortest safe path detours one row up: up,
        # right x3, down = 5 steps => -5 (verified independently by walking
        # the rendered ASCII policy by hand, not just trusting the solver).
        env = GridWorldEnv(rows=3, cols=4, slip_prob=0.0)
        V, policy = value_iteration(env, gamma=1.0)
        self.assertAlmostEqual(V[env.encode(*env.start)], -5.0, places=4)
        self.assertAlmostEqual(greedy_rollout_return(env, policy), -5.0, places=4)


class TestBlackjackOracle(unittest.TestCase):
    """Spot-checks against extremely well-established Blackjack basic
    strategy facts (independent of this project, textbook-level knowledge),
    computed here via exact backward induction rather than simulation."""

    @classmethod
    def setUpClass(cls):
        cls.policy, cls.values = blackjack_optimal_policy()

    def test_always_stand_on_hard_20(self):
        for dealer in range(1, 11):
            self.assertEqual(self.policy[(20, dealer, False)], 0, f"dealer={dealer}")

    def test_always_hit_hard_16_vs_ten(self):
        self.assertEqual(self.policy[(16, 10, False)], 1)

    def test_stand_on_hard_12_vs_weak_dealer_card(self):
        # dealer 4/5/6 are the classic "bust cards" -- standing on a stiff 12
        # and letting the dealer bust is correct.
        for dealer in (4, 5, 6):
            self.assertEqual(self.policy[(12, dealer, False)], 0, f"dealer={dealer}")

    def test_hit_on_hard_12_vs_strong_dealer_card(self):
        for dealer in (2, 3, 7, 8, 9, 10):
            self.assertEqual(self.policy[(12, dealer, False)], 1, f"dealer={dealer}")

    def test_values_are_valid_probabilities_range(self):
        for state, v in self.values.items():
            self.assertGreaterEqual(v, -1.0 - 1e-9)
            self.assertLessEqual(v, 1.0 + 1e-9)


if __name__ == "__main__":
    unittest.main()
