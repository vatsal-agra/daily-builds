import random
import unittest

from bellman import minimax
from bellman.envs.tictactoe import EMPTY_BOARD, apply_move, is_terminal, other_player, winner


class TestMinimax(unittest.TestCase):
    def test_optimal_vs_optimal_always_draws(self):
        rng = random.Random(0)
        for _ in range(50):
            board = EMPTY_BOARD
            player = "X"
            while not is_terminal(board):
                action = minimax.best_move_random_tiebreak(board, player, rng)
                board = apply_move(board, action, player)
                player = other_player(player)
            self.assertIsNone(winner(board))

    def test_full_state_space_size(self):
        minimax.best_move(EMPTY_BOARD, "X")
        # 5478 is the known exact count of reachable Tic-Tac-Toe board
        # states (including terminal ones) under alternating play.
        self.assertEqual(len(minimax.memo_snapshot()), 5478)

    def test_optimal_response_to_center_opening_is_a_draw(self):
        # X opens center; O's only non-losing replies are the corners.
        board = apply_move(EMPTY_BOARD, 4, "X")
        board = apply_move(board, 0, "O")  # a corner
        _, score = minimax.best_move(board, "X")
        self.assertEqual(score, 0)

    def test_punishes_a_blunder(self):
        # X opens center; O replies with an edge instead of a corner --
        # the well-known Tic-Tac-Toe blunder -- so a perfect X must now
        # have a forced win, not a draw.
        board = apply_move(EMPTY_BOARD, 4, "X")
        board = apply_move(board, 1, "O")  # an edge, not a corner
        action, score = minimax.best_move(board, "X")
        self.assertIsNotNone(action)
        self.assertGreater(score, 0)

    def test_terminal_board_has_no_move(self):
        board = ("X", "X", "X", "O", "O", " ", " ", " ", " ")
        action, _ = minimax.best_move(board, "O")
        self.assertIsNone(action)

    def test_random_tiebreak_on_terminal_board_returns_none(self):
        board = ("X", "X", "X", "O", "O", " ", " ", " ", " ")
        minimax.best_move(board, "O")  # populate memo
        result = minimax.best_move_random_tiebreak(board, "O", random.Random(0))
        self.assertIsNone(result)

    def test_occupied_cell_raises(self):
        board = apply_move(EMPTY_BOARD, 0, "X")
        with self.assertRaises(ValueError):
            apply_move(board, 0, "O")


if __name__ == "__main__":
    unittest.main()
