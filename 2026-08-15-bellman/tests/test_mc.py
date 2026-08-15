import unittest

from bellman.envs import BlackjackEnv
from bellman.mc import mc_control, mc_es_control
from bellman.dp import blackjack_optimal_policy


class TestMonteCarloExploringStarts(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.optimal_policy, _ = blackjack_optimal_policy()
        cls.Q, cls.learned_policy = mc_es_control(episodes=200_000, gamma=1.0, seed=0)

    def test_high_agreement_with_independent_optimal_policy(self):
        agree = sum(1 for s, a in self.learned_policy.items() if a == self.optimal_policy[s])
        total = len(self.learned_policy)
        agreement = agree / total
        # Exploring Starts should get very close to the true optimum; allow a
        # small margin for the handful of genuinely near-indifferent states
        # (where hit/stand expected values differ by only a few percent).
        self.assertGreaterEqual(agreement, 0.90, f"only {agreement:.1%} agreement")

    def test_covers_the_full_graded_state_space(self):
        expected_states = {(t, d, ace) for t in range(12, 22) for d in range(1, 11) for ace in (False, True)}
        self.assertEqual(set(self.learned_policy.keys()), expected_states)

    def test_unambiguous_cases_are_learned_correctly(self):
        # These aren't close calls -- large EV gaps (>=0.2, verified against
        # dp.py's exact backward induction) -- so MC-ES must get them right.
        # (16 vs 10 is deliberately NOT tested here: it's the single closest
        # decision in the entire basic-strategy table, EV gap ~0.006 -- real
        # coin-flip territory that no reasonable sample budget resolves reliably.)
        self.assertEqual(self.learned_policy[(20, 10, False)], 0)  # always stand on 20
        self.assertEqual(self.learned_policy[(12, 5, False)], 0)   # stand, dealer bust card
        self.assertEqual(self.learned_policy[(17, 2, False)], 0)   # stand, hard 17
        self.assertEqual(self.learned_policy[(13, 7, False)], 1)   # hit, stiff hand vs strong card

    def test_deterministic_given_seed(self):
        Q_a, policy_a = mc_es_control(episodes=5000, seed=3)
        Q_b, policy_b = mc_es_control(episodes=5000, seed=3)
        self.assertEqual(policy_a, policy_b)


class TestMonteCarloEpsilonGreedy(unittest.TestCase):
    """The general on-policy epsilon-greedy variant (mc_control) exists as a
    deliberate contrast to Exploring Starts -- see mc.py's module docstring
    for why ES was chosen for the shipped Blackjack feature. Exercised here
    so it stays a working, tested piece of the project rather than orphaned
    code nothing ever calls."""

    def test_produces_a_valid_policy_over_visited_states(self):
        Q, policy = mc_control(lambda: BlackjackEnv(), episodes=40_000,
                                gamma=1.0, epsilon_start=1.0, epsilon_end=0.05, seed=0)
        self.assertGreater(len(policy), 50)
        for state, action in policy.items():
            self.assertIn(action, (0, 1))
            player_total, dealer_showing, usable_ace = state
            self.assertTrue(1 <= dealer_showing <= 10)

    def test_still_gets_the_easy_calls_right_despite_soft_policy_bias(self):
        # mc.py's module docs explain epsilon-soft MC control converges to
        # Q_pi (value under continued exploration), not Q*, which biases the
        # closer decisions -- but the *large*-margin decisions should still
        # come out right even so.
        Q, policy = mc_control(lambda: BlackjackEnv(), episodes=100_000,
                                gamma=1.0, epsilon_start=1.0, epsilon_end=0.02, seed=0)
        self.assertEqual(policy.get((20, 10, False)), 0)  # always stand on 20


if __name__ == "__main__":
    unittest.main()
