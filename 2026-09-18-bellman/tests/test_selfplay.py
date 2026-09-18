import random
import unittest

from bellman import minimax
from bellman.envs.tictactoe import EMPTY_BOARD, apply_move, is_terminal, other_player, winner
from bellman.selfplay import SelfPlayAgent


def play_vs_oracle(agent, agent_player, n_games, seed):
    rng = random.Random(seed)
    outcomes = {"agent_win": 0, "oracle_win": 0, "draw": 0}
    for _ in range(n_games):
        board = EMPTY_BOARD
        player = "X"
        while not is_terminal(board):
            if player == agent_player:
                action, _ = agent.choose_move_greedy(board, player)
            else:
                action = minimax.best_move_random_tiebreak(board, player, rng)
            board = apply_move(board, action, player)
            player = other_player(player)
        w = winner(board)
        if w is None:
            outcomes["draw"] += 1
        elif w == agent_player:
            outcomes["agent_win"] += 1
        else:
            outcomes["oracle_win"] += 1
    return outcomes


class TestSelfPlay(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        # Same hyperparameters viz_export.py ships (see its comment on
        # why epsilon=0.3/60000 episodes, not the smaller values that
        # looked fine against a deterministic oracle but weren't).
        cls.agent = SelfPlayAgent(alpha=0.1, epsilon=0.3, seed=7)
        cls.agent.train(60000)

    def test_never_loses_as_x(self):
        outcomes = play_vs_oracle(self.agent, "X", 100, seed=1)
        self.assertEqual(outcomes["oracle_win"], 0)

    def test_never_loses_as_o(self):
        outcomes = play_vs_oracle(self.agent, "O", 100, seed=2)
        self.assertEqual(outcomes["oracle_win"], 0)

    def test_learned_a_substantial_fraction_of_the_state_space(self):
        # 5478 is the exact known count of reachable Tic-Tac-Toe states.
        self.assertGreater(len(self.agent.V), 5478 * 0.9)

    def test_terminal_value_is_exact(self):
        x_win = ("X", "X", "X", "O", "O", " ", " ", " ", " ")
        o_win = ("O", "O", "O", "X", "X", " ", " ", " ", " ")
        draw = ("X", "O", "X", "X", "O", "O", "O", "X", "X")
        self.assertEqual(self.agent.value(x_win), 1.0)
        self.assertEqual(self.agent.value(o_win), 0.0)
        self.assertEqual(self.agent.value(draw), 0.5)


if __name__ == "__main__":
    unittest.main()
