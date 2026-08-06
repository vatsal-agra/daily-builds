"""Move-generation correctness against published perft reference values.
This is the ground-truth check for the whole engine: a mismatch here means
some rule (castling, en passant, promotion, check/pin detection...) is
generating an illegal move or missing a legal one."""

import unittest

from zugzwang.board import Board, START_FEN
from zugzwang.perft import perft


class TestPerft(unittest.TestCase):
    def test_start_position(self):
        board = Board.from_fen(START_FEN)
        expected = {1: 20, 2: 400, 3: 8902, 4: 197281}
        for depth, want in expected.items():
            with self.subTest(depth=depth):
                self.assertEqual(perft(board, depth), want)

    def test_kiwipete(self):
        # Famous stress-test position: castling both sides, en passant,
        # promotions, and several pins/discovered-check opportunities.
        fen = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
        board = Board.from_fen(fen)
        self.assertEqual(perft(board, 1), 48)
        self.assertEqual(perft(board, 2), 2039)
        self.assertEqual(perft(board, 3), 97862)

    def test_position_3_en_passant_and_pins(self):
        fen = "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1"
        board = Board.from_fen(fen)
        self.assertEqual(perft(board, 4), 43238)

    def test_position_4_promotions(self):
        fen = "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1"
        board = Board.from_fen(fen)
        self.assertEqual(perft(board, 3), 9467)

    def test_position_5(self):
        fen = "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8"
        board = Board.from_fen(fen)
        self.assertEqual(perft(board, 3), 62379)


if __name__ == "__main__":
    unittest.main()
