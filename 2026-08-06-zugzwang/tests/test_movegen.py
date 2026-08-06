"""Rule-by-rule correctness tests for move generation and game-state
detection, beyond what raw perft node counts alone can pin down."""

import unittest

from zugzwang.board import Board, parse_square
from zugzwang.movegen import (
    generate_legal_moves, is_in_check, game_state, has_insufficient_material,
)
from zugzwang.zobrist import hash_board


class TestCastling(unittest.TestCase):
    def test_kingside_and_queenside_available(self):
        board = Board.from_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        legal_ucis = {m.uci() for m in generate_legal_moves(board)}
        self.assertIn("e1g1", legal_ucis)
        self.assertIn("e1c1", legal_ucis)

    def test_cannot_castle_through_check(self):
        # black rook on f8 attacks f1, so white cannot castle kingside
        board = Board.from_fen("4k3/8/8/8/8/8/8/4K2R w K - 0 1")
        legal_ucis = {m.uci() for m in generate_legal_moves(board)}
        self.assertIn("e1g1", legal_ucis)
        board2 = Board.from_fen("5r1k/8/8/8/8/8/8/4K2R w K - 0 1")
        legal_ucis2 = {m.uci() for m in generate_legal_moves(board2)}
        self.assertNotIn("e1g1", legal_ucis2)

    def test_rights_revoked_when_rook_captured_on_home_square(self):
        board = Board.from_fen("4k3/8/2b5/8/8/8/8/4K2R b K - 0 1")
        legal = generate_legal_moves(board)
        capture = next(m for m in legal if m.captured == "R")
        board.make_move(capture)
        self.assertEqual(board.castling, set())

    def test_rights_revoked_when_king_or_rook_moves(self):
        board = Board.from_fen("4k3/8/8/8/8/8/8/R3K2R w KQ - 0 1")
        legal = generate_legal_moves(board)
        rook_move = next(m for m in legal if m.frm == parse_square("a1"))
        board.make_move(rook_move)
        self.assertEqual(board.castling, {"K"})


class TestEnPassant(unittest.TestCase):
    def test_en_passant_capture_available_and_correct(self):
        # white pawn e5, black just played d7-d5 -> en passant on d6
        board = Board.from_fen("4k3/8/8/3pP3/8/8/8/4K3 w - d6 0 1")
        legal = generate_legal_moves(board)
        ep_moves = [m for m in legal if m.is_ep]
        self.assertEqual(len(ep_moves), 1)
        board.make_move(ep_moves[0])
        # the captured black pawn (on d5, not d6) must be gone
        self.assertEqual(board.squares[parse_square("d5")], ".")
        self.assertEqual(board.squares[parse_square("d6")], "P")

    def test_en_passant_discovered_check_is_illegal(self):
        # classic pin: White King a5, Black pawn d5 (just double-pushed),
        # White pawn e5, Black rook h5. Capturing en passant removes BOTH
        # the d5 and e5 pawns from the rank, opening a clear rook check
        # against White's own king along rank 5 -- so the capture must be
        # filtered out as illegal, not merely offered and left to the
        # legality check to (maybe) catch some other way.
        board = Board.from_fen("4k3/8/8/K2pP2r/8/8/8/8 w - d6 0 1")
        legal = generate_legal_moves(board)
        ep_moves = [m for m in legal if m.is_ep]
        self.assertEqual(ep_moves, [])


class TestPromotion(unittest.TestCase):
    def test_all_four_promotion_pieces_offered(self):
        board = Board.from_fen("4k3/P7/8/8/8/8/8/4K3 w - - 0 1")
        legal = generate_legal_moves(board)
        promos = {m.promotion for m in legal if m.promotion}
        self.assertEqual(promos, {"Q", "R", "B", "N"})

    def test_capturing_underpromotion(self):
        board = Board.from_fen("1r2k3/P7/8/8/8/8/8/4K3 w - - 0 1")
        legal = generate_legal_moves(board)
        capture_promos = [m for m in legal if m.promotion and m.captured]
        self.assertEqual(len(capture_promos), 4)


class TestGameState(unittest.TestCase):
    def test_checkmate(self):
        # fool's mate final position
        board = Board.from_fen("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR w KQkq - 1 3")
        self.assertEqual(game_state(board), "checkmate")

    def test_stalemate(self):
        board = Board.from_fen("7k/5K2/6Q1/8/8/8/8/8 b - - 0 1")
        self.assertEqual(game_state(board), "stalemate")

    def test_insufficient_material_king_vs_king(self):
        board = Board.from_fen("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
        self.assertTrue(has_insufficient_material(board))
        self.assertEqual(game_state(board), "draw_insufficient")

    def test_bishop_pair_opposite_colors_is_sufficient(self):
        board = Board.from_fen("8/8/8/4k3/8/3b4/8/2BK4 w - - 0 1")
        self.assertFalse(has_insufficient_material(board))

    def test_fifty_move_rule(self):
        board = Board.from_fen("4k3/8/8/8/8/8/8/4K3 w - - 100 50")
        self.assertEqual(game_state(board), "draw_fifty")

    def test_threefold_repetition(self):
        board = Board.from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        position_history = [hash_board(board)]
        shuffle = ["g1f3", "g8f6", "f3g1", "f6g8"] * 2
        for uci in shuffle:
            legal = generate_legal_moves(board)
            frm, to = parse_square(uci[:2]), parse_square(uci[2:4])
            move = next(m for m in legal if m.frm == frm and m.to == to)
            board.make_move(move)
            position_history.append(hash_board(board))
        self.assertEqual(game_state(board, position_history), "draw_repetition")

    def test_no_false_repetition_without_history(self):
        # same position, but the caller didn't pass history -> can't claim it
        board = Board.from_fen("rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        self.assertEqual(game_state(board), "ongoing")


if __name__ == "__main__":
    unittest.main()
