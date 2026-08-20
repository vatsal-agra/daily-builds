import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from bellman.envs.cartpole import CartPole
from bellman.agents.dqn import ReplayBuffer, DQNAgent, train, evaluate


class TestReplayBuffer(unittest.TestCase):
    def test_len_grows_up_to_capacity_then_stays(self):
        buf = ReplayBuffer(capacity=5, seed=0)
        for i in range(10):
            buf.push(i, 0, 0.0, i, False)
        self.assertEqual(len(buf), 5)

    def test_wraparound_overwrites_oldest_first(self):
        buf = ReplayBuffer(capacity=3, seed=0)
        for i in range(3):
            buf.push(i, 0, 0.0, i, False)
        # buf now holds [0,1,2]; pushing a 4th should overwrite the oldest (0)
        buf.push(99, 0, 0.0, 99, False)
        states = sorted(item[0] for item in buf.buf)
        self.assertEqual(states, [1, 2, 99])

    def test_last_is_correct_even_after_wraparound(self):
        """Regression test: `buf[-1]` on a wrapped ring buffer is NOT
        necessarily the most recently pushed item — `.last` must be."""
        buf = ReplayBuffer(capacity=3, seed=0)
        for i in range(3):
            buf.push(i, 0, 0.0, i, False)
        buf.push(42, 0, 0.0, 42, False)  # wraps, overwrites slot 0
        buf.push(43, 0, 0.0, 43, False)  # wraps, overwrites slot 1
        self.assertEqual(buf.last, (43, 0, 0.0, 43, False))

    def test_sample_returns_requested_batch_size(self):
        buf = ReplayBuffer(capacity=100, seed=0)
        for i in range(50):
            buf.push([float(i)] * 4, i % 2, 1.0, [float(i + 1)] * 4, False)
        s, a, r, s2, d = buf.sample(16)
        self.assertEqual(s.shape, (16, 4))
        self.assertEqual(a.shape, (16,))

    def test_sample_larger_than_buffer_raises(self):
        buf = ReplayBuffer(capacity=10, seed=0)
        buf.push([0.0] * 4, 0, 0.0, [0.0] * 4, False)
        with self.assertRaises(ValueError):
            buf.sample(5)


class TestDQNAgent(unittest.TestCase):
    def test_select_action_in_range(self):
        agent = DQNAgent(state_dim=4, n_actions=2, seed=0)
        for _ in range(20):
            a = agent.select_action((0.0, 0.0, 0.0, 0.0))
            self.assertIn(a, (0, 1))

    def test_greedy_action_is_deterministic_argmax(self):
        agent = DQNAgent(state_dim=4, n_actions=2, seed=0)
        state = (0.1, -0.2, 0.05, 0.0)
        q, _ = agent.q_net.forward(np.asarray(state))
        expected = int(np.argmax(q))
        for _ in range(10):
            self.assertEqual(agent.select_action(state, greedy=True), expected)

    def test_train_step_returns_none_before_enough_data(self):
        agent = DQNAgent(state_dim=4, n_actions=2, batch_size=32, seed=0)
        self.assertIsNone(agent.train_step())

    def test_train_step_runs_once_enough_data(self):
        agent = DQNAgent(state_dim=4, n_actions=2, batch_size=8, seed=0)
        for i in range(8):
            agent.observe([0.0] * 4, 0, 1.0, [0.0] * 4, False)
        loss = agent.train_step()
        self.assertIsNotNone(loss)
        self.assertGreaterEqual(loss, 0.0)

    def test_no_replay_trains_on_single_transition_only(self):
        agent = DQNAgent(state_dim=4, n_actions=2, use_replay=False, seed=0)
        self.assertIsNone(agent.train_step())  # nothing observed yet
        agent.observe([1.0, 0, 0, 0], 1, 1.0, [0, 0, 0, 0], False)
        loss = agent.train_step()
        self.assertIsNotNone(loss)

    def test_no_target_network_aliases_q_net(self):
        agent = DQNAgent(state_dim=4, n_actions=2, use_target_network=False, seed=0)
        self.assertIs(agent.target_net, agent.q_net)

    def test_target_network_is_a_separate_copy_initially_equal(self):
        agent = DQNAgent(state_dim=4, n_actions=2, use_target_network=True, seed=0)
        self.assertIsNot(agent.target_net, agent.q_net)
        for wq, wt in zip(agent.q_net.Ws, agent.target_net.Ws):
            self.assertTrue(np.array_equal(wq, wt))

    def test_target_network_syncs_on_schedule(self):
        agent = DQNAgent(
            state_dim=4, n_actions=2, batch_size=4, target_update_freq=3,
            use_replay=True, use_target_network=True, seed=0,
        )
        # Nonzero states: an all-zero input state gives an exactly-zero
        # gradient for the first layer's *weight* matrix (a_prev.T @ delta
        # is zero when a_prev is zero) — only its bias would move, so a
        # naive Ws-only check on that input is checking the wrong thing.
        for i in range(4):
            agent.observe([0.2, -0.1, 0.05, 0.3], 0, 1.0, [0.1, 0.1, 0.1, 0.1], False)
        agent.train_step()  # update 1
        agent.train_step()  # update 2
        before = [w.copy() for w in agent.target_net.Ws] + [b.copy() for b in agent.target_net.bs]
        agent.train_step()  # update 3 -> should sync
        after = agent.target_net.Ws + agent.target_net.bs
        # q_net should have moved from its initial weights by now (Adam step),
        # so a sync at update 3 must make target diverge from its update-2 self.
        changed = any(not np.array_equal(b, a) for b, a in zip(before, after))
        self.assertTrue(changed)


class TestDQNTrainingLoop(unittest.TestCase):
    def test_train_returns_one_return_per_episode(self):
        env = CartPole(max_steps=30, seed=0)
        agent = DQNAgent(state_dim=4, n_actions=2, batch_size=8, seed=0)
        returns, losses = train(env, agent, n_episodes=5, max_steps=30)
        self.assertEqual(len(returns), 5)
        self.assertEqual(len(losses), 5)
        for r in returns:
            self.assertGreaterEqual(r, 1.0)  # every episode survives at least 1 step

    def test_evaluate_is_greedy_and_seed_controlled(self):
        env = CartPole(max_steps=50, seed=0)
        agent = DQNAgent(state_dim=4, n_actions=2, seed=0)
        r1 = evaluate(env, agent, n_episodes=3, max_steps=50, seeds=[10, 11, 12])
        r2 = evaluate(env, agent, n_episodes=3, max_steps=50, seeds=[10, 11, 12])
        self.assertEqual(r1, r2)  # untrained but fixed weights + fixed seeds -> identical


class TestDQNLearnsSomethingOnCartPole(unittest.TestCase):
    """Not a full "solved CartPole" claim (that's train.py's `dqn` command,
    run at real episode counts) — a much cheaper smoke test that training
    measurably improves over a short run relative to a random baseline,
    catching a totally broken learning loop without eating minutes of CI
    time."""

    def test_short_training_run_beats_random_policy(self):
        random_agent_env = CartPole(max_steps=200, seed=123)
        random_returns = []
        for seed in range(20):
            random_agent_env.seed(1000 + seed)
            random_agent_env.reset()
            total = 0.0
            for _ in range(200):
                import random as _random
                s, r, done, _ = random_agent_env.step(_random.Random(seed).randrange(2))
                total += r
                if done:
                    break
            random_returns.append(total)
        random_avg = sum(random_returns) / len(random_returns)

        env = CartPole(max_steps=200, seed=0)
        agent = DQNAgent(state_dim=4, n_actions=2, hidden=(32, 32), batch_size=32, seed=0)
        train(env, agent, n_episodes=80, max_steps=200)
        eval_env = CartPole(max_steps=200, seed=0)
        trained_returns = evaluate(eval_env, agent, 20, max_steps=200, seeds=list(range(1000, 1020)))
        trained_avg = sum(trained_returns) / len(trained_returns)

        self.assertGreater(trained_avg, random_avg)


if __name__ == "__main__":
    unittest.main()
