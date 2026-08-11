"""End-to-end DQN training tests, with a hard numeric pass bar.

These are the slowest tests in the suite (real training runs, no
shortcuts) -- run alone with `python -m unittest tests.test_dqn -v` if
iterating just on this file.
"""
import os
import statistics
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bellman.envs.cartpole import CartPoleEnv, STATE_DIM, ACTIONS
from bellman.agents.dqn import DQNAgent, ReplayBuffer, train, evaluate, DEFAULT_STATE_SCALE


class TestReplayBuffer(unittest.TestCase):
    def test_capacity_evicts_oldest(self):
        buf = ReplayBuffer(capacity=3, seed=0)
        for i in range(5):
            buf.push([i], 0, 0.0, [i], False)
        self.assertEqual(len(buf), 3)

    def test_sample_returns_requested_size(self):
        buf = ReplayBuffer(capacity=100, seed=0)
        for i in range(10):
            buf.push([i], 0, 0.0, [i], False)
        batch = buf.sample(4)
        self.assertEqual(len(batch), 4)


class TestDQNAgentMechanics(unittest.TestCase):
    def test_learn_returns_none_before_train_start(self):
        agent = DQNAgent(4, 2, train_start=50, batch_size=8, seed=0)
        for _ in range(10):
            agent.observe([0, 0, 0, 0], 0, 1.0, [0, 0, 0, 0], False)
        self.assertIsNone(agent.learn())

    def test_learn_updates_weights_once_buffer_is_warm(self):
        agent = DQNAgent(4, 2, train_start=20, batch_size=8, seed=0)
        for i in range(30):
            agent.observe([0.1, 0, 0, 0], i % 2, 1.0, [0.1, 0, 0, 0], False)
        before = [row[:] for row in agent.q_net.layers[0].W]
        loss = agent.learn()
        self.assertIsNotNone(loss)
        after = agent.q_net.layers[0].W
        self.assertNotEqual(before, after)

    def test_target_network_syncs_on_schedule(self):
        agent = DQNAgent(4, 2, train_start=5, batch_size=5, target_update_every=3, seed=0)
        for i in range(20):
            agent.observe([0.1, 0, 0, 0], i % 2, 1.0, [0.1, 0, 0, 0], False)
        for _ in range(3):
            agent.learn()
        # after exactly target_update_every learn() calls, target == online
        self.assertEqual(agent.q_net.layers[0].W, agent.target_net.layers[0].W)

    def test_state_normalization_matches_configured_scale(self):
        agent = DQNAgent(4, 2, state_scale=(2.0, 4.0, 1.0, 5.0), seed=0)
        normed = agent._norm([2.0, 4.0, 1.0, 5.0])
        self.assertEqual(normed, [1.0, 1.0, 1.0, 1.0])

    def test_act_is_greedy_when_epsilon_zero(self):
        agent = DQNAgent(4, 2, seed=0)
        # force a known Q-value ordering by hand-setting the last layer
        last = agent.q_net.layers[-1]
        last.W = [[0.0] * last.n_in, [0.0] * last.n_in]
        last.b = [5.0, -5.0]
        a = agent.act([0.0, 0.0, 0.0, 0.0], epsilon=0.0)
        self.assertEqual(a, 0)


class TestDQNEndToEndTraining(unittest.TestCase):
    """The real pass bar: a trained agent must clear cart-pole's return by
    a wide, unambiguous margin over both a random policy and an untrained
    network -- not just "the loss went down"."""

    def test_random_policy_baseline_is_short(self):
        import random

        env = CartPoleEnv(seed=0)
        rng = random.Random(0)
        totals = []
        for _ in range(20):
            env.reset()
            total = 0.0
            for _ in range(500):
                _, r, done, truncated = env.step(rng.choice(ACTIONS))
                total += r
                if done or truncated:
                    break
            totals.append(total)
        # documents the baseline the trained agent is compared against
        self.assertLess(statistics.mean(totals), 40)

    def test_dqn_learns_to_meaningfully_outperform_random(self):
        env = CartPoleEnv(seed=0)
        agent, rewards, losses = train(
            env, episodes=260, seed=0, max_steps=500, epsilon_decay_episodes=180,
        )
        eval_env = CartPoleEnv(seed=777)
        evals = evaluate(eval_env, agent, episodes=30, max_steps=500)
        mean_eval = statistics.mean(evals)
        # random-policy cart-pole averages roughly 18-25 steps; a properly
        # trained DQN here reliably clears 3x-5x that with real margin
        self.assertGreater(mean_eval, 70)
        # and it must have actually trained, not just avoided crashing
        trained_losses = [l for l in losses if l is not None]
        self.assertGreater(len(trained_losses), 0)


if __name__ == "__main__":
    unittest.main()
