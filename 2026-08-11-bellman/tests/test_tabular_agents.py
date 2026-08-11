import os
import statistics
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bellman.envs import gridworld
from bellman.agents import dp, tabular


def _optimal_state_match(env, agent, opt_policy):
    learned = agent.greedy_policy()
    total = matches = 0
    for s in opt_policy:
        if env.is_terminal(s):
            continue
        total += 1
        if opt_policy[s] == learned.get(s):
            matches += 1
    return matches, total


class TestConvergenceToOptimal(unittest.TestCase):
    """Every tabular agent must find the DP oracle's exact optimal policy
    on the deterministic gridworld -- this is the whole point of having
    an exact oracle to check against."""

    def test_qlearning_converges_on_gridworld(self):
        env = gridworld.make("gridworld")
        _, _, opt_policy = dp.value_iteration(gridworld.make("gridworld"), gamma=0.99)
        agent = tabular.QLearning(env, alpha=0.5, gamma=0.99, seed=0)
        agent.train(episodes=1000)
        matches, total = _optimal_state_match(env, agent, opt_policy)
        self.assertEqual(matches, total)

    def test_sarsa_converges_on_gridworld(self):
        env = gridworld.make("gridworld")
        _, _, opt_policy = dp.value_iteration(gridworld.make("gridworld"), gamma=0.99)
        agent = tabular.Sarsa(env, alpha=0.5, gamma=0.99, seed=0,
                               schedule=tabular.EpsilonGreedy(1.0, 0.02, 700))
        agent.train(episodes=1200)
        matches, total = _optimal_state_match(env, agent, opt_policy)
        self.assertGreaterEqual(matches / total, 0.9)

    def test_monte_carlo_converges_on_gridworld(self):
        env = gridworld.make("gridworld")
        _, _, opt_policy = dp.value_iteration(gridworld.make("gridworld"), gamma=0.99)
        agent = tabular.MonteCarlo(env, gamma=0.99, seed=0,
                                    schedule=tabular.EpsilonGreedy(1.0, 0.02, 1800))
        agent.train(episodes=3000, max_steps=100)
        matches, total = _optimal_state_match(env, agent, opt_policy)
        self.assertGreaterEqual(matches / total, 0.85)

    def test_qlearning_solves_frozen_lake_better_than_random(self):
        env = gridworld.make("frozenlake")
        agent = tabular.QLearning(env, alpha=0.3, gamma=0.99, seed=0,
                                   schedule=tabular.EpsilonGreedy(1.0, 0.05, 3000))
        agent.train(episodes=6000)
        # evaluate the learned greedy policy's success rate
        policy = agent.greedy_policy()
        wins = 0
        trials = 500
        for _ in range(trials):
            s = env.reset()
            for _ in range(100):
                a = policy[s]
                s, r, done, truncated = env.step(a)
                if done or truncated:
                    break
            if s in env.goals:
                wins += 1
        win_rate = wins / trials
        self.assertGreater(win_rate, 0.5)  # random policy wins far less often


class TestOnVsOffPolicyDivergence(unittest.TestCase):
    """The textbook Q-learning vs SARSA divergence on CliffWalking:
    Q-learning (off-policy) learns the optimal risky path along the cliff
    edge; SARSA (on-policy, epsilon-greedy behavior) learns a safer,
    longer path because it accounts for its own exploration risk."""

    def test_qlearning_takes_the_cliff_edge_sarsa_does_not(self):
        env_template = lambda: gridworld.make("cliffwalking")
        schedule = tabular.EpsilonGreedy(1.0, 0.1, 300)

        ql = tabular.QLearning(env_template(), alpha=0.5, gamma=1.0, seed=2, schedule=schedule)
        ql.train(episodes=800)
        sarsa = tabular.Sarsa(env_template(), alpha=0.5, gamma=1.0, seed=2, schedule=schedule)
        sarsa.train(episodes=800)

        def rows_visited(agent):
            env = env_template()
            policy = agent.greedy_policy()
            s = env.reset()
            rows = {env.rc(s)[0]}
            for _ in range(50):
                a = policy[s]
                s, r, done, truncated = env.step(a)
                rows.add(env.rc(s)[0])
                if done or truncated:
                    break
            return rows

        ql_rows = rows_visited(ql)
        sarsa_rows = rows_visited(sarsa)
        # Q-learning's greedy path stays right along the cliff (row 2, one
        # above the cliff row 3); SARSA's stays further away (lower row
        # index = further from the cliff, since row 0 is the top edge)
        self.assertEqual(min(ql_rows), 2)
        self.assertLess(min(sarsa_rows), 2)


class TestEpsilonGreedySchedule(unittest.TestCase):
    def test_epsilon_decays_from_start_to_end(self):
        sched = tabular.EpsilonGreedy(epsilon_start=1.0, epsilon_end=0.1, decay_episodes=100)
        self.assertAlmostEqual(sched.epsilon(0), 1.0)
        self.assertAlmostEqual(sched.epsilon(100), 0.1)
        self.assertAlmostEqual(sched.epsilon(200), 0.1)  # clamped past decay window
        self.assertTrue(0.1 < sched.epsilon(50) < 1.0)


class TestFactory(unittest.TestCase):
    def test_make_rejects_unknown_agent(self):
        with self.assertRaises(KeyError):
            tabular.make("not-a-real-agent", gridworld.make("gridworld"))

    def test_make_is_case_and_punctuation_insensitive(self):
        env = gridworld.make("gridworld")
        a1 = tabular.make("Q-Learning", env, seed=0)
        a2 = tabular.make("qlearning", env, seed=0)
        self.assertIsInstance(a1, tabular.QLearning)
        self.assertIsInstance(a2, tabular.QLearning)


if __name__ == "__main__":
    unittest.main()
