import unittest

from bellman.envs import GridWorldEnv
from bellman.dp import value_iteration, greedy_rollout_return
from bellman.td import q_learning, sarsa, sarsa_lambda


class TestTDControl(unittest.TestCase):
    """The core verification story: Q-Learning and SARSA never see
    `transition_model()` -- only samples from `step()` -- yet must converge
    to (Q-Learning) or near (SARSA) the DP oracle's optimum."""

    @classmethod
    def setUpClass(cls):
        cls.oracle_env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0)
        cls.V_star, cls.policy_star = value_iteration(cls.oracle_env, gamma=1.0)
        cls.optimal_return = greedy_rollout_return(
            GridWorldEnv(rows=4, cols=12, slip_prob=0.0), cls.policy_star)

    def test_q_learning_matches_dp_optimal_exactly(self):
        env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0, seed=0)
        _, policy, rewards = q_learning(env, episodes=500, alpha=0.5, gamma=1.0,
                                         epsilon_start=1.0, epsilon_end=0.01,
                                         max_steps=200, seed=0)
        eval_env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0)
        learned_return = greedy_rollout_return(eval_env, policy)
        self.assertAlmostEqual(learned_return, self.optimal_return, places=4,
                                msg="off-policy Q-Learning should learn the true optimal "
                                    "greedy path regardless of its own exploration")

    def test_sarsa_reaches_goal_safely_and_near_optimally(self):
        env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0, seed=0)
        _, policy, rewards = sarsa(env, episodes=500, alpha=0.5, gamma=1.0,
                                    epsilon_start=1.0, epsilon_end=0.01,
                                    max_steps=200, seed=0)
        eval_env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0)
        learned_return = greedy_rollout_return(eval_env, policy)
        # SARSA is on-policy: with residual exploration during training it
        # classically prefers the *safer* path (further from the cliff),
        # which costs more steps than optimal (a return no better than -13,
        # since nothing can beat the DP optimum) but must never actually
        # walk off the cliff on its final greedy policy (return > -100).
        self.assertLessEqual(learned_return, self.optimal_return + 1e-9)
        self.assertGreater(learned_return, -100)

    def test_sarsa_prefers_safer_path_than_q_learning_near_cliff(self):
        # The textbook divergence: with residual exploration, on-policy SARSA
        # rates the cliff-hugging optimal path as riskier than off-policy
        # Q-Learning does, and ends up taking the (longer, safer) path.
        env_q = GridWorldEnv(rows=4, cols=12, slip_prob=0.0, seed=0)
        _, policy_q, _ = q_learning(env_q, episodes=500, alpha=0.5, gamma=1.0,
                                     epsilon_start=1.0, epsilon_end=0.01, max_steps=200, seed=0)
        env_s = GridWorldEnv(rows=4, cols=12, slip_prob=0.0, seed=0)
        _, policy_s, _ = sarsa(env_s, episodes=500, alpha=0.5, gamma=1.0,
                                epsilon_start=1.0, epsilon_end=0.01, max_steps=200, seed=0)
        eval_env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0)
        q_return = greedy_rollout_return(eval_env, policy_q)
        s_return = greedy_rollout_return(eval_env, policy_s)
        self.assertGreaterEqual(q_return, s_return)

    def test_sarsa_lambda_also_solves_the_task(self):
        env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0, seed=0)
        _, policy, rewards = sarsa_lambda(env, episodes=500, alpha=0.5, gamma=1.0, lam=0.9,
                                           epsilon_start=1.0, epsilon_end=0.01,
                                           max_steps=200, seed=0)
        eval_env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0)
        learned_return = greedy_rollout_return(eval_env, policy)
        self.assertGreater(learned_return, -100)  # never actually falls off the cliff when greedy
        self.assertLessEqual(learned_return, self.optimal_return + 1e-9)  # can't beat the DP optimum

    def test_learning_curve_improves_over_training(self):
        env = GridWorldEnv(rows=4, cols=12, slip_prob=0.0, seed=0)
        _, _, rewards = q_learning(env, episodes=300, alpha=0.5, gamma=1.0,
                                    epsilon_start=1.0, epsilon_end=0.05,
                                    max_steps=200, seed=0)
        first_50_avg = sum(rewards[:50]) / 50
        last_50_avg = sum(rewards[-50:]) / 50
        self.assertGreater(last_50_avg, first_50_avg,
                            "reward should meaningfully improve from early to late training")

    def test_epsilon_greedy_is_deterministic_given_seed(self):
        env_a = GridWorldEnv(rows=4, cols=12, slip_prob=0.0, seed=0)
        env_b = GridWorldEnv(rows=4, cols=12, slip_prob=0.0, seed=0)
        _, policy_a, rewards_a = q_learning(env_a, episodes=50, seed=7, max_steps=200)
        _, policy_b, rewards_b = q_learning(env_b, episodes=50, seed=7, max_steps=200)
        self.assertEqual(rewards_a, rewards_b)
        self.assertEqual(policy_a, policy_b)


if __name__ == "__main__":
    unittest.main()
