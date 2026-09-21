"""Phase 3 adversarial-review regression tests: Dirichlet noise must
apply during self-play and MUST NEVER leak into evaluation/tournament
play (an explicit item in the brief's bug-hunt checklist). These tests
prove the mechanism actually works (noise measurably changes root
priors) AND that every evaluation-facing player wires add_root_noise to
False -- not just by reading the code, but by spying on the real call.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
import numpy as np

from sente.games.tictactoe import TicTacToe as T
from sente.nn.network import PolicyValueNet
from sente.mcts import MCTS, Node
from sente.evaluate import NetMCTSPlayer, PureMCTSPlayer, RolloutMCTS


class TestDirichletNoiseDoesNotLeak(unittest.TestCase):
    def setUp(self):
        self.net = PolicyValueNet(T.input_dim, T.action_size, hidden_sizes=(16, 16), seed=5)
        self.state = T.initial_state()

    def test_noise_mechanism_actually_perturbs_root_priors(self):
        # Sanity: the noise-mixing code path must actually do something
        # measurable, otherwise "noise never leaks into eval" would be a
        # vacuous claim (nothing to leak).
        mcts_clean = MCTS(T, self.net, n_simulations=1, dirichlet_alpha=0.3, dirichlet_eps=0.25,
                           rng=np.random.default_rng(1))
        node_clean = Node(self.state)
        mcts_clean._expand(node_clean, add_noise=False)
        p_clean = dict(node_clean.P)

        mcts_noisy = MCTS(T, self.net, n_simulations=1, dirichlet_alpha=0.3, dirichlet_eps=0.25,
                           rng=np.random.default_rng(1))
        node_noisy = Node(self.state)
        mcts_noisy._expand(node_noisy, add_noise=True)
        p_noisy = dict(node_noisy.P)

        self.assertNotEqual(p_clean, p_noisy, "Dirichlet noise had no measurable effect on root priors")
        # both must still be valid probability distributions over the same actions
        self.assertAlmostEqual(sum(p_clean.values()), 1.0, places=6)
        self.assertAlmostEqual(sum(p_noisy.values()), 1.0, places=6)

    def test_run_defaults_to_no_noise(self):
        # The API default matters: a caller who forgets the flag must get
        # the SAFE (no noise) behavior, not the exploratory one.
        import inspect
        sig = inspect.signature(MCTS.run)
        self.assertEqual(sig.parameters["add_root_noise"].default, False)

    def test_net_mcts_player_calls_run_without_noise(self):
        calls = []
        orig_run = MCTS.run

        def spy_run(self_mcts, root_state, add_root_noise=False, return_root=False):
            calls.append(add_root_noise)
            return orig_run(self_mcts, root_state, add_root_noise=add_root_noise, return_root=return_root)

        MCTS.run = spy_run
        try:
            player = NetMCTSPlayer(self.net, n_simulations=5)
            player.select_move(T, self.state, np.random.default_rng(0))
        finally:
            MCTS.run = orig_run
        self.assertTrue(len(calls) >= 1)
        self.assertTrue(all(c is False for c in calls), f"NetMCTSPlayer leaked Dirichlet noise into evaluation: {calls}")

    def test_pure_mcts_player_calls_run_without_noise(self):
        calls = []
        orig_run = MCTS.run

        def spy_run(self_mcts, root_state, add_root_noise=False, return_root=False):
            calls.append(add_root_noise)
            return orig_run(self_mcts, root_state, add_root_noise=add_root_noise, return_root=return_root)

        MCTS.run = spy_run
        try:
            player = PureMCTSPlayer(n_simulations=5, n_rollouts_per_leaf=1)
            player.select_move(T, self.state, np.random.default_rng(0))
        finally:
            MCTS.run = orig_run
        self.assertTrue(len(calls) >= 1)
        self.assertTrue(all(c is False for c in calls), f"PureMCTSPlayer leaked Dirichlet noise into evaluation: {calls}")


if __name__ == "__main__":
    unittest.main()
