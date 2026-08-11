"""End-to-end REINFORCE training tests. REINFORCE converges much faster
than DQN on cart-pole in this codebase (full-episode Monte-Carlo returns
give a much stronger learning signal per gradient step than one-step TD
bootstrapping does, at the cost of needing complete episodes) -- these
tests hold it to a correspondingly higher bar.
"""
import os
import statistics
import sys
import unittest

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from bellman.envs.cartpole import CartPoleEnv
from bellman.agents.reinforce import ReinforceAgent, softmax, train, evaluate


class TestSoftmax(unittest.TestCase):
    def test_sums_to_one_and_is_positive(self):
        probs = softmax([1.0, 2.0, -1.0])
        self.assertAlmostEqual(sum(probs), 1.0, places=9)
        self.assertTrue(all(p > 0 for p in probs))

    def test_is_shift_invariant(self):
        a = softmax([1.0, 2.0, 3.0])
        b = softmax([1001.0, 1002.0, 1003.0])  # would overflow naive exp
        for pa, pb in zip(a, b):
            self.assertAlmostEqual(pa, pb, places=9)

    def test_larger_logit_gets_more_mass(self):
        probs = softmax([0.0, 5.0])
        self.assertGreater(probs[1], probs[0])


class TestReinforceAgentMechanics(unittest.TestCase):
    def test_act_returns_valid_action_and_probs(self):
        agent = ReinforceAgent(4, 2, seed=0)
        a, probs = agent.act([0.0, 0.0, 0.0, 0.0])
        self.assertIn(a, (0, 1))
        self.assertAlmostEqual(sum(probs), 1.0, places=6)

    def test_update_changes_policy_weights(self):
        # varied states/actions/rewards -- an all-identical-state,
        # constant-reward, alternating-action trajectory is a degenerate
        # case where the batched gradient can cancel to exactly zero
        agent = ReinforceAgent(4, 2, seed=0)
        states = [[0.1, -0.2, 0.05, 0.0], [0.2, 0.1, -0.1, 0.05],
                  [-0.1, 0.3, 0.02, -0.05], [0.0, -0.1, 0.15, 0.1]]
        actions = [0, 1, 1, 0]
        rewards = [1.0, 1.0, 0.5, 2.0]
        before = [row[:] for row in agent.policy_net.layers[0].W]
        agent.update(states, actions, rewards)
        after = agent.policy_net.layers[0].W
        self.assertNotEqual(before, after)

    def test_update_on_empty_trajectory_is_a_noop_not_a_crash(self):
        agent = ReinforceAgent(4, 2, seed=0)
        result = agent.update([], [], [])
        self.assertIsNone(result)

    def test_returns_are_discounted_correctly(self):
        agent = ReinforceAgent(4, 2, gamma=0.5, seed=0)
        returns = agent._returns([1.0, 1.0, 1.0])
        # G_2=1, G_1=1+0.5*1=1.5, G_0=1+0.5*1.5=1.75
        self.assertAlmostEqual(returns[2], 1.0)
        self.assertAlmostEqual(returns[1], 1.5)
        self.assertAlmostEqual(returns[0], 1.75)


class TestReinforceEndToEndTraining(unittest.TestCase):
    def test_reinforce_solves_cartpole_to_a_high_bar(self):
        env = CartPoleEnv(seed=0)
        agent, rewards = train(env, episodes=350, max_steps=500, seed=0)
        eval_env = CartPoleEnv(seed=777)
        evals = evaluate(eval_env, agent, episodes=30, max_steps=500)
        mean_eval = statistics.mean(evals)
        # measured baseline: ~470/500 mean over 30 eval episodes with
        # these hyperparameters/seed; a wide-margin, seed-robust bar
        self.assertGreater(mean_eval, 250)
        self.assertGreater(max(evals), 400)


if __name__ == "__main__":
    unittest.main()
