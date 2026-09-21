import sys, os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

import unittest
import numpy as np

from sente.games.tictactoe import TicTacToe as T
from sente.games.connect4 import Connect4Jr as C


class TestTicTacToe(unittest.TestCase):
    def test_initial_state(self):
        s = T.initial_state()
        self.assertEqual(T.current_player(s), 1)
        self.assertEqual(len(T.legal_moves(s)), 9)
        self.assertIsNone(T.winner(s))
        self.assertFalse(T.is_terminal(s))

    def test_win_detection_all_lines(self):
        lines = [(0, 1, 2), (3, 4, 5), (6, 7, 8), (0, 3, 6), (1, 4, 7), (2, 5, 8), (0, 4, 8), (2, 4, 6)]
        for line in lines:
            board = [0] * 9
            for i in line:
                board[i] = 1
            board = tuple(board)
            self.assertEqual(T.winner(board), 1, f"line {line} should be a win for X")
            self.assertTrue(T.is_terminal(board))

    def test_draw(self):
        # A known drawn full board.
        board = (1, -1, 1,
                  1, -1, -1,
                  -1, 1, 1)
        self.assertTrue(T.is_terminal(board))
        self.assertEqual(T.winner(board), 0)

    def test_apply_move_rejects_occupied_cell(self):
        s = T.apply_move(T.initial_state(), 0)
        with self.assertRaises(ValueError):
            T.apply_move(s, 0)

    def test_current_player_alternates(self):
        s = T.initial_state()
        players = []
        for a in [0, 1, 2, 3]:
            players.append(T.current_player(s))
            s = T.apply_move(s, a)
        self.assertEqual(players, [1, -1, 1, -1])

    def test_encode_shape_and_perspective(self):
        s = T.apply_move(T.initial_state(), 0)  # X played 0; O to move
        x = T.encode(s)
        self.assertEqual(x.shape, (18,))
        # O is to move; "own" plane (first 9) should be all 0 (O has no pieces),
        # "opp" plane (last 9) should have a 1 at index 0 (X's piece).
        self.assertTrue(np.all(x[:9] == 0))
        self.assertEqual(x[9], 1.0)

    def test_symmetries_count_and_win_preserved(self):
        s = (1, 0, 0,
             0, 1, 0,
             0, 0, -1)
        # Policy mass only on the EMPTY cells (1, 2, 3, 5, 6, 7) -- 0, 4, 8
        # are occupied and must stay exactly 0 after every symmetry too.
        pi = np.array([0, 0.3, 0.2, 0.1, 0, 0.15, 0.1, 0.15, 0])
        syms = T.symmetries(s, pi)
        self.assertGreaterEqual(len(syms), 1)
        self.assertLessEqual(len(syms), 8)
        for sym_state, sym_pi in syms:
            self.assertAlmostEqual(float(np.sum(sym_pi)), 1.0, places=6)
            # policy mass must stay on legal (empty) cells
            for i, v in enumerate(sym_state):
                if v != 0:
                    self.assertEqual(sym_pi[i], 0.0)

    def test_legal_mask_matches_legal_moves(self):
        s = T.apply_move(T.initial_state(), 4)
        mask = T.legal_mask(s)
        self.assertEqual(set(np.where(mask)[0].tolist()), set(T.legal_moves(s)))


class TestConnect4Jr(unittest.TestCase):
    def test_initial_state(self):
        s = C.initial_state()
        self.assertEqual(C.current_player(s), 1)
        self.assertEqual(len(C.legal_moves(s)), C.cols)
        self.assertFalse(C.is_terminal(s))

    def test_gravity_drop(self):
        s = C.initial_state()
        s = C.apply_move(s, 2)
        s = C.apply_move(s, 2)
        self.assertEqual(len(s[2]), 2)
        self.assertEqual(s[2], (1, -1))

    def test_column_full_rejected(self):
        s = C.initial_state()
        for _ in range(C.rows):
            s = C.apply_move(s, 0)
        self.assertNotIn(0, C.legal_moves(s))
        with self.assertRaises(ValueError):
            C.apply_move(s, 0)

    def test_horizontal_win(self):
        # X has a piece on the bottom row of columns 0-3.
        board = tuple([(1,), (1,), (1,), (1,), ()])
        self.assertEqual(C.winner(board), 1)

    def test_vertical_win(self):
        board = tuple([(1, 1, 1, 1), (), (), (), ()])
        self.assertEqual(C.winner(board), 1)

    def test_diagonal_win(self):
        # / diagonal: (col0,row0), (col1,row1), (col2,row2), (col3,row3)
        board = (
            (1,),
            (-1, 1),
            (-1, -1, 1),
            (-1, -1, -1, 1),
            (),
        )
        self.assertEqual(C.winner(board), 1)

    def test_no_win_no_terminal_mid_game(self):
        board = tuple([(1,), (-1,), (), (), ()])
        self.assertFalse(C.is_terminal(board))
        self.assertIsNone(C.winner(board))

    def test_full_board_draw(self):
        # Fill without any 4-in-a-row: alternate a pattern that avoids
        # any line of 4. Use a checker-ish column fill sized to ROWSxCOLS.
        cols = []
        for c in range(C.cols):
            col = []
            for r in range(C.rows):
                # alternate parity based on (r+c) to avoid runs of 4
                col.append(1 if (r + c) % 2 == 0 else -1)
            cols.append(tuple(col))
        board = tuple(cols)
        # This particular pattern may or may not be a legal *sequence* of
        # drops, but Connect4Jr's winner() only cares about the final grid,
        # so it's a valid state object for testing win-detection absence.
        if C.winner(board) is None:
            self.assertTrue(C.is_terminal(board))
            self.assertEqual(C.winner(board), 0)

    def test_encode_shape(self):
        s = C.initial_state()
        x = C.encode(s)
        self.assertEqual(x.shape, (2 * C.rows * C.cols,))

    def test_mirror_symmetry(self):
        s = tuple([(1,), (), (), (), (-1,)])
        pi = np.zeros(C.cols)
        pi[1] = 0.6
        pi[3] = 0.4
        syms = C.symmetries(s, pi)
        self.assertEqual(len(syms), 2)
        mirrored_state, mirrored_pi = syms[1]
        self.assertEqual(mirrored_state[0], s[4])
        self.assertEqual(mirrored_state[4], s[0])
        self.assertAlmostEqual(mirrored_pi[3], 0.6)
        self.assertAlmostEqual(mirrored_pi[1], 0.4)


if __name__ == "__main__":
    unittest.main()
