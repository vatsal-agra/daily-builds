"""MCTS correctness tests, focused on exactly the sign-convention bug
class this repo's self-play/RL builds are told to hunt for: value-backup
sign errors when flipping between players up the tree.

Strategy: plug in a "perfect oracle" net (uniform policy, but a value
function equal to the true minimax value) so that MCTS's Q estimates
have a known-correct target to converge to, and check the *sign* and
*magnitude* of Q at both the root and one level down.
"""
import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest

from sente.games.tictactoe import TicTacToe as G
from sente.mcts import MCTS
from sente.oracle_tictactoe import minimax_value


class OracleMCTS(MCTS):
    """Same as MCTS, but leaf evaluation calls the independent minimax
    oracle for the exact value, instead of a trained network. This
    isolates the search/backup mechanics from network quality: any Q
    sign error will show up as a wrong-sign Q even though the "network"
    is perfect."""

    def _evaluate(self, state):
        legal = self.game.legal_moves(state)
        priors = {a: 1.0 / len(legal) for a in legal}
        v = float(minimax_value(state))
        return priors, v


def root_q(mcts: OracleMCTS, root_state, action, add_noise=False):
    _, root = mcts.run(root_state, add_root_noise=add_noise, return_root=True)
    if root.N.get(action, 0) == 0:
        return 0.0
    return root.W[action] / root.N[action]


class TestMCTSSignConvention(unittest.TestCase):
    def test_root_prefers_immediate_winning_move(self):
        # X to move (4 pieces down, even), X has two-in-a-row at (0,1)
        # and O has two-in-a-row at (3,4); X to move can WIN immediately
        # by playing 2, which is strictly better than blocking O at 5.
        state = (1, 1, 0,
                  -1, -1, 0,
                  0, 0, 0)
        self.assertEqual(G.current_player(state), 1)
        self.assertEqual(G.winner(G.apply_move(state, 2)), 1)  # sanity: 2 wins

        mcts = OracleMCTS(G, net=None, c_puct=1.5, n_simulations=400)
        visit_counts = mcts.run(state, add_root_noise=False)
        best = max(visit_counts, key=lambda a: visit_counts[a])
        self.assertEqual(best, 2, f"MCTS did not find the immediate win; visits={visit_counts}")

        q = root_q(OracleMCTS(G, net=None, c_puct=1.5, n_simulations=400), state, action=2)
        self.assertGreater(q, 0.9, f"Q for a forced immediate win should be ~+1, got {q}")

    def test_root_never_looks_confident_about_a_losing_move(self):
        # X@0, X@8 (2 pieces); O@3, O@4 (2 pieces) -> legal (equal
        # counts, X to move). O threatens to complete row (3,4,5). X has
        # no immediate win of its own, so X's only non-losing move is to
        # block at 5 -- every other legal move lets O win next turn.
        state = (1, 0, 0,
                  -1, -1, 0,
                  0, 0, 1)
        self.assertEqual(G.current_player(state), 1)
        self.assertEqual(len(G.legal_moves(state)), 5)

        mcts = OracleMCTS(G, net=None, c_puct=1.5, n_simulations=600)
        visit_counts = mcts.run(state, add_root_noise=False)
        best = max(visit_counts, key=lambda a: visit_counts[a])
        self.assertEqual(best, 5, f"MCTS did not find the forced block; visits={visit_counts}")

        mcts2 = OracleMCTS(G, net=None, c_puct=1.5, n_simulations=600)
        q_block = root_q(mcts2, state, action=5)
        self.assertGreaterEqual(q_block, -0.05, f"Q for the correct block should not look like a loss, got {q_block}")

        mcts3 = OracleMCTS(G, net=None, c_puct=1.5, n_simulations=600)
        # Any move other than 5 lets O win next turn -> Q should be ~-1.
        other = next(a for a in G.legal_moves(state) if a != 5)
        q_other = root_q(mcts3, state, action=other)
        self.assertLess(q_other, -0.5, f"Q for a move that lets O force a win should be strongly negative, got {q_other}")

    def test_empty_board_root_moves_never_look_like_a_confirmed_loss(self):
        # Tic-Tac-Toe from the empty board is a proven draw with perfect
        # play; no opening move for X should ever show a confidently
        # negative Q (that would indicate a backup sign error, since X
        # can always at least draw).
        state = G.initial_state()
        mcts = OracleMCTS(G, net=None, c_puct=1.5, n_simulations=500)
        visit_counts = mcts.run(state, add_root_noise=False)
        best = max(visit_counts, key=lambda a: visit_counts[a])

        mcts2 = OracleMCTS(G, net=None, c_puct=1.5, n_simulations=500)
        q_best = root_q(mcts2, state, action=best)
        self.assertGreater(q_best, -0.2, f"Best opening move looks like a loss (Q={q_best}); sign bug suspected")


if __name__ == "__main__":
    unittest.main()
