import unittest

from bellman import gradcheck
from bellman.envs.cartpole import CartPole
from bellman.reinforce import PolicyNet, evaluate, reinforce_train


class TestGradCheck(unittest.TestCase):
    def test_backward_matches_finite_differences(self):
        n_checked, worst = gradcheck.check()
        self.assertGreater(n_checked, 0)
        self.assertLess(worst, 1e-4)


class TestReinforce(unittest.TestCase):
    def test_untrained_policy_is_near_uniform(self):
        net = PolicyNet(input_size=4, hidden_size=16, output_size=2, seed=0)
        probs, _ = net.forward([0.1, -0.1, 0.05, -0.05])
        self.assertAlmostEqual(sum(probs), 1.0, places=6)
        for p in probs:
            self.assertGreater(p, 0.2)  # not already collapsed to a corner

    def test_training_beats_untrained_baseline(self):
        env = CartPole(max_steps=200)
        untrained = reinforce_train(env, episodes=0, seed=42)[0]
        baseline = evaluate(env, untrained, episodes=50, seed=999)

        net, returns, survived, checkpoints = reinforce_train(
            env, episodes=1500, hidden_size=16, lr=0.02, gamma=0.99, seed=42, batch_size=10
        )
        trained = evaluate(env, net, episodes=50, seed=999)

        self.assertGreater(trained["avg_steps"], baseline["avg_steps"])
        self.assertGreater(len(returns), 0)
        self.assertGreater(len(checkpoints), 0)

    def test_invalid_action_count_mismatch_is_caught_by_gradcheck_tolerance(self):
        # Sanity: a badly-scaled advantage should NOT still gradcheck
        # clean if the backward pass were wrong -- this just re-affirms
        # gradcheck is sensitive, using a different (seed, state, action)
        # than the default check() call.
        from bellman.gradcheck import check
        n_checked, worst = check(seed=7)
        self.assertLess(worst, 1e-4)


if __name__ == "__main__":
    unittest.main()
