import os
import sys
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import numpy as np

from bellman.envs.cartpole import CartPole
from bellman.agents.reinforce import ReinforceAgent, run_episode, train, evaluate


class TestActionProbs(unittest.TestCase):
    def test_probs_sum_to_one_and_are_nonnegative(self):
        agent = ReinforceAgent(state_dim=4, n_actions=3, seed=0)
        p = agent.action_probs((0.1, -0.2, 0.05, 0.0))
        self.assertAlmostEqual(float(np.sum(p)), 1.0, places=10)
        self.assertTrue(np.all(p >= 0.0))

    def test_greedy_action_is_argmax_of_probs(self):
        agent = ReinforceAgent(state_dim=4, n_actions=2, seed=0)
        state = (0.1, -0.2, 0.05, 0.0)
        p = agent.action_probs(state)
        expected = int(np.argmax(p))
        for _ in range(10):
            self.assertEqual(agent.select_action(state, greedy=True), expected)

    def test_stochastic_action_is_always_valid(self):
        agent = ReinforceAgent(state_dim=4, n_actions=4, seed=0)
        for _ in range(50):
            a = agent.select_action((0.0, 0.0, 0.0, 0.0), greedy=False)
            self.assertIn(a, range(4))


class TestDiscountedReturns(unittest.TestCase):
    def test_matches_hand_computed_returns(self):
        agent = ReinforceAgent(state_dim=2, n_actions=2, gamma=0.5, seed=0)
        rewards = [1.0, 1.0, 1.0]
        returns = agent._discounted_returns(rewards)
        # G2 = 1; G1 = 1 + 0.5*1 = 1.5; G0 = 1 + 0.5*1.5 = 1.75
        np.testing.assert_allclose(returns, [1.75, 1.5, 1.0], atol=1e-10)

    def test_single_step_episode(self):
        agent = ReinforceAgent(state_dim=2, n_actions=2, gamma=0.9, seed=0)
        returns = agent._discounted_returns([5.0])
        np.testing.assert_allclose(returns, [5.0])


class TestUpdateMovesTowardHigherReturnActions(unittest.TestCase):
    def test_advantage_positive_increases_action_probability(self):
        """A single fabricated timestep with a large positive advantage
        should increase pi(a|s) for the action taken — the entire point
        of the policy-gradient update rule."""
        agent = ReinforceAgent(state_dim=3, n_actions=2, policy_lr=0.5, gamma=0.99, seed=0,
                                normalize_advantages=False)
        state = [0.1, 0.2, -0.1]
        before = agent.action_probs(state)[0]
        # A single episode where action 0 was taken and got a big reward.
        agent.update(states=[state], actions=[0], rewards=[10.0])
        after = agent.action_probs(state)[0]
        self.assertGreater(after, before)

    def test_value_net_regresses_toward_the_return(self):
        agent = ReinforceAgent(state_dim=3, n_actions=2, value_lr=0.5, gamma=0.9, seed=0)
        state = [0.1, -0.2, 0.0]
        v_before, _ = agent.value_net.forward(np.array(state))
        for _ in range(50):
            agent.update(states=[state], actions=[0], rewards=[10.0])
        v_after, _ = agent.value_net.forward(np.array(state))
        # value estimate for this state should move toward the observed
        # return (10.0 for a length-1 episode), i.e. get much closer to it
        self.assertLess(abs(v_after.item() - 10.0), abs(v_before.item() - 10.0))


class TestEmptyEpisodeGuard(unittest.TestCase):
    def test_update_on_empty_episode_raises_clear_error(self):
        """Regression: agent.update([], [], []) used to fall through to a
        raw numpy matmul dimension-mismatch error deep inside forward();
        run_episode() already guards against calling update() this way,
        but the public method itself should fail clearly too."""
        agent = ReinforceAgent(state_dim=2, n_actions=2, seed=0)
        with self.assertRaises(ValueError):
            agent.update([], [], [])

    def test_run_episode_never_calls_update_on_empty_episode(self):
        # An env whose very first step is always terminal
        class ImmediatelyDoneEnv:
            def reset(self):
                return (0.0, 0.0, 0.0, 0.0)

            def step(self, action):
                return (0.0, 0.0, 0.0, 0.0), 1.0, True, {}

        agent = ReinforceAgent(state_dim=4, n_actions=2, seed=0)
        r, steps = run_episode(ImmediatelyDoneEnv(), agent, learn=True, max_steps=10)
        self.assertEqual(steps, 1)  # one real (non-empty) step, not zero


class TestEpisodeAndTrainingLoop(unittest.TestCase):
    def test_run_episode_returns_positive_reward_and_steps(self):
        env = CartPole(max_steps=50, seed=0)
        agent = ReinforceAgent(state_dim=4, n_actions=2, seed=0)
        r, steps = run_episode(env, agent, learn=True, max_steps=50)
        self.assertGreaterEqual(r, 1.0)
        self.assertGreater(steps, 0)

    def test_train_returns_one_value_per_episode(self):
        env = CartPole(max_steps=30, seed=0)
        agent = ReinforceAgent(state_dim=4, n_actions=2, seed=0)
        returns = train(env, agent, n_episodes=5, max_steps=30)
        self.assertEqual(len(returns), 5)

    def test_evaluate_is_seed_controlled_and_reproducible(self):
        env = CartPole(max_steps=50, seed=0)
        agent = ReinforceAgent(state_dim=4, n_actions=2, seed=0)
        r1 = evaluate(env, agent, n_episodes=3, max_steps=50, seeds=[10, 11, 12])
        r2 = evaluate(env, agent, n_episodes=3, max_steps=50, seeds=[10, 11, 12])
        self.assertEqual(r1, r2)


class TestReinforceLearnsSomethingOnCartPole(unittest.TestCase):
    def test_short_training_beats_random_policy(self):
        import random as _random

        random_returns = []
        for seed in range(20):
            env = CartPole(max_steps=200, seed=1000 + seed)
            env.reset()
            rng = _random.Random(seed)
            total = 0.0
            for _ in range(200):
                s, r, done, _ = env.step(rng.randrange(2))
                total += r
                if done:
                    break
            random_returns.append(total)
        random_avg = sum(random_returns) / len(random_returns)

        env = CartPole(max_steps=200, seed=0)
        agent = ReinforceAgent(state_dim=4, n_actions=2, hidden=(32,), seed=0)
        train(env, agent, n_episodes=150, max_steps=200)
        eval_env = CartPole(max_steps=200, seed=0)
        trained_returns = evaluate(eval_env, agent, 20, max_steps=200, seeds=list(range(1000, 1020)))
        trained_avg = sum(trained_returns) / len(trained_returns)

        self.assertGreater(trained_avg, random_avg)


if __name__ == "__main__":
    unittest.main()
