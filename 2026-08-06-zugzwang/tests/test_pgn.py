"""SAN generation, PGN export, and PGN parsing/replay -- including the two
parser bugs found in adversarial review (0-0 castling notation, and PGN
numbering for a non-White-first start)."""

import unittest

from zugzwang.board import Board, START_FEN, parse_square
from zugzwang.movegen import generate_legal_moves
from zugzwang.pgn import (
    move_to_san, game_to_pgn, parse_pgn_movetext, san_to_move, replay_pgn,
)


class TestSAN(unittest.TestCase):
    def test_disambiguation_by_file(self):
        board = Board.from_fen("4k3/8/8/8/8/8/8/1N2KN2 w - - 0 1")
        legal = generate_legal_moves(board)
        sans = sorted(move_to_san(board, m, legal) for m in legal
                      if m.piece == "N" and m.to == parse_square("d2"))
        self.assertEqual(sans, ["Nbd2", "Nfd2"])

    def test_disambiguation_by_rank(self):
        board = Board.from_fen("4k3/8/8/3N4/8/8/8/3NK3 w - - 0 1")
        legal = generate_legal_moves(board)
        sans = sorted(move_to_san(board, m, legal) for m in legal
                      if m.piece == "N" and m.to == parse_square("c3"))
        self.assertEqual(sans, ["N1c3", "N5c3"])

    def test_check_and_mate_suffixes(self):
        # position right before Qh4# is played (fool's mate)
        board = Board.from_fen("rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq - 0 2")
        legal = generate_legal_moves(board)
        move = next(m for m in legal if m.uci() == "d8h4")
        self.assertEqual(move_to_san(board, move, legal), "Qh4#")

    def test_castling_san(self):
        board = Board.from_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        legal = generate_legal_moves(board)
        kingside = next(m for m in legal if m.uci() == "e1g1")
        queenside = next(m for m in legal if m.uci() == "e1c1")
        self.assertEqual(move_to_san(board, kingside, legal), "O-O")
        self.assertEqual(move_to_san(board, queenside, legal), "O-O-O")


class TestPgnParsing(unittest.TestCase):
    def test_movetext_strips_numbers_and_result(self):
        text = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 1-0"
        self.assertEqual(
            parse_pgn_movetext(text),
            ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6"],
        )

    def test_zero_castling_notation_survives_parsing(self):
        text = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. 0-0 Nf6"
        self.assertIn("0-0", parse_pgn_movetext(text))

    def test_no_space_move_numbers(self):
        text = "1.e4 e5 2.Nf3 Nc6 3.Bb5 a6 4.O-O Nf6"
        self.assertEqual(
            parse_pgn_movetext(text),
            ["e4", "e5", "Nf3", "Nc6", "Bb5", "a6", "O-O", "Nf6"],
        )

    def test_comments_stripped(self):
        text = "1. e4 {best by test} e5 2. Nf3 Nc6"
        self.assertEqual(parse_pgn_movetext(text), ["e4", "e5", "Nf3", "Nc6"])

    def test_replay_round_trip(self):
        pgn = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. Ba4 Nf6 5. O-O Be7"
        board, history, hashes = replay_pgn(pgn)
        self.assertEqual(len(history), 10)
        self.assertEqual(len(hashes), 11)  # start position + 10 plies
        self.assertEqual(board.to_fen().split()[0],
                          "r1bqk2r/1pppbppp/p1n2n2/4p3/B3P3/5N2/PPPP1PPP/RNBQ1RK1")

    def test_castling_notated_with_zeros_replays_correctly(self):
        pgn = "1. e4 e5 2. Nf3 Nc6 3. Bb5 a6 4. 0-0 Nf6"
        board, history, hashes = replay_pgn(pgn)
        self.assertEqual(history[-2][0], "0-0")  # White's O-O, as originally written

    def test_illegal_move_in_pgn_raises(self):
        with self.assertRaises(ValueError):
            replay_pgn("1. e4 e5 2. Ke2 Ke7 3. Kd3 Kd7 4. Kxd7")  # nonsense/illegal chain


class TestPgnNumbering(unittest.TestCase):
    def test_white_first_numbering(self):
        pgn = game_to_pgn(["e4", "e5", "Nf3", "Nc6"])
        self.assertIn("1. e4 e5 2. Nf3 Nc6", pgn)

    def test_black_to_move_first_numbering(self):
        # regression test: numbering used to always assume White moves
        # first at san_history[0]
        black_first_fen = "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq - 0 1"
        pgn = game_to_pgn(["Nc6", "Nf3", "Nf6"], start_fen=black_first_fen)
        self.assertIn("1... Nc6 2. Nf3 Nf6", pgn)
        self.assertIn('[SetUp "1"]', pgn)
        self.assertIn(f'[FEN "{black_first_fen}"]', pgn)

    def test_standard_start_has_no_setup_headers(self):
        pgn = game_to_pgn(["e4"], start_fen=START_FEN)
        self.assertNotIn("SetUp", pgn)
        self.assertNotIn("[FEN", pgn)


if __name__ == "__main__":
    unittest.main()
