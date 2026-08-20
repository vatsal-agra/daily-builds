import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from bellman.envs.gridworld import make_simple_grid, make_cliff_walking
from bellman.agents.qlearning import QLearningAgent, SarsaAgent, run_episode, train
from bellman.verify import verify_against_value_iteration, greedy_path, cliff_edge_fraction


class TestConvergenceAgainstValueIteration(unittest.TestCase):
    """The real correctness test: does the learned policy actually
    achieve the value-iteration-verified optimal return, not just
    "did reward go up"."""

    def test_qlearning_converges_to_optimal_on_simple_grid(self):
        env = make_simple_grid()
        agent = QLearningAgent(
            env.n_states, env.n_actions, alpha=0.3, gamma=0.99,
            epsilon=1.0, epsilon_decay=0.99, epsilon_min=0.001, seed=0,
        )
        train(env, agent, 800, max_steps=env.max_steps)
        result = verify_against_value_iteration(env, agent, 0.99)
        self.assertTrue(result["optimal_rollout"])

    def test_sarsa_converges_to_optimal_on_simple_grid(self):
        env = make_simple_grid()
        agent = SarsaAgent(
            env.n_states, env.n_actions, alpha=0.3, gamma=0.99,
            epsilon=1.0, epsilon_decay=0.99, epsilon_min=0.001, seed=0,
        )
        train(env, agent, 800, max_steps=env.max_steps)
        result = verify_against_value_iteration(env, agent, 0.99)
        self.assertTrue(result["optimal_rollout"])

    def test_convergence_is_seed_robust(self):
        """Not a one-seed fluke: check a spread of seeds all converge."""
        for seed in (1, 2, 3):
            env = make_simple_grid()
            agent = QLearningAgent(
                env.n_states, env.n_actions, alpha=0.3, gamma=0.99,
                epsilon=1.0, epsilon_decay=0.99, epsilon_min=0.001, seed=seed,
            )
            train(env, agent, 800, max_steps=env.max_steps)
            result = verify_against_value_iteration(env, agent, 0.99)
            self.assertTrue(result["optimal_rollout"], f"seed={seed} failed to converge")


class TestOffPolicyVsOnPolicyUpdateRule(unittest.TestCase):
    """Directly checks the ONE line that's supposed to differ between the
    two agents: Q-learning bootstraps off max_a' Q(s',a'); SARSA
    bootstraps off Q(s', a') for the action actually taken next."""

    def test_qlearning_uses_max_next_q_regardless_of_next_action(self):
        agent = QLearningAgent(n_states=3, n_actions=2, alpha=1.0, gamma=1.0, epsilon=0.0, seed=0)
        agent.Q[1] = [5.0, 9.0]
        # update from state 0 -> next_state 1, taking next_action=0 (the WORSE one)
        agent.update(state=0, action=0, reward=0.0, next_state=1, next_action=0, done=False)
        # target should use max(Q[1]) = 9.0, not Q[1][0] = 5.0
        self.assertAlmostEqual(agent.Q[0][0], 9.0)

    def test_sarsa_uses_the_actual_next_action_value(self):
        agent = SarsaAgent(n_states=3, n_actions=2, alpha=1.0, gamma=1.0, epsilon=0.0, seed=0)
        agent.Q[1] = [5.0, 9.0]
        agent.update(state=0, action=0, reward=0.0, next_state=1, next_action=0, done=False)
        # target should use Q[1][0] = 5.0, the action actually selected next — NOT the max
        self.assertAlmostEqual(agent.Q[0][0], 5.0)

    def test_terminal_update_ignores_bootstrap(self):
        agent = QLearningAgent(n_states=3, n_actions=2, alpha=1.0, gamma=1.0, epsilon=0.0, seed=0)
        agent.Q[1] = [999.0, 999.0]  # should be irrelevant — episode ended
        agent.update(state=0, action=0, reward=3.0, next_state=1, next_action=0, done=True)
        self.assertAlmostEqual(agent.Q[0][0], 3.0)


class TestEpsilonGreedy(unittest.TestCase):
    def test_greedy_always_picks_argmax(self):
        agent = QLearningAgent(n_states=2, n_actions=3, epsilon=1.0, seed=0)
        agent.Q[0] = [1.0, 9.0, 2.0]
        for _ in range(20):
            self.assertEqual(agent.select_action(0, greedy=True), 1)

    def test_epsilon_zero_is_always_greedy(self):
        agent = QLearningAgent(n_states=2, n_actions=3, epsilon=0.0, seed=0)
        agent.Q[0] = [1.0, 9.0, 2.0]
        for _ in range(20):
            self.assertEqual(agent.select_action(0, greedy=False), 1)

    def test_epsilon_decay_respects_floor(self):
        agent = QLearningAgent(n_states=2, n_actions=2, epsilon=1.0, epsilon_decay=0.5, epsilon_min=0.1, seed=0)
        for _ in range(50):
            agent.decay_epsilon()
        self.assertGreaterEqual(agent.epsilon, 0.1)
        self.assertAlmostEqual(agent.epsilon, 0.1, places=6)


class TestCliffWalkingDivergence(unittest.TestCase):
    """Reproduces the textbook Sutton & Barto Example 6.6 result: with
    identical hyperparameters, off-policy Q-learning's greedy path hugs
    the cliff edge (optimal but risky); on-policy SARSA's does not."""

    def test_qlearning_and_sarsa_diverge_on_cliff_walking(self):
        results = {}
        for name, cls in (("qlearning", QLearningAgent), ("sarsa", SarsaAgent)):
            env = make_cliff_walking()
            agent = cls(
                env.n_states, env.n_actions, alpha=0.5, gamma=1.0,
                epsilon=0.1, epsilon_decay=1.0, epsilon_min=0.1, seed=0,
            )
            train(env, agent, 500, max_steps=env.max_steps)
            path = greedy_path(env, agent.greedy_policy())
            results[name] = cliff_edge_fraction(env, path)

        self.assertGreater(results["qlearning"], 0.9, "Q-learning should walk almost entirely along the cliff edge")
        self.assertLess(results["sarsa"], 0.3, "SARSA should mostly avoid the cliff edge")
        self.assertGreater(
            results["qlearning"], results["sarsa"],
            "Q-learning must hug the cliff edge more than SARSA does",
        )


class TestRunEpisode(unittest.TestCase):
    def test_run_episode_returns_reward_and_step_count(self):
        env = make_simple_grid()
        agent = QLearningAgent(env.n_states, env.n_actions, seed=0)
        r, steps = run_episode(env, agent, learn=True, max_steps=env.max_steps)
        self.assertIsInstance(r, float)
        self.assertGreater(steps, 0)

    def test_learn_false_does_not_change_q_table(self):
        env = make_simple_grid()
        agent = QLearningAgent(env.n_states, env.n_actions, seed=0)
        q_before = [row[:] for row in agent.Q]
        run_episode(env, agent, learn=False, max_steps=env.max_steps)
        self.assertEqual(agent.Q, q_before)


if __name__ == "__main__":
    unittest.main()
