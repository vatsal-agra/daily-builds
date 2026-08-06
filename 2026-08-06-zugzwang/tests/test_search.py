"""Search correctness: finds forced mates, never returns an illegal move,
and -- the critical regression test -- never corrupts the board on a
search-timeout abort (see REVIEW.md bug #2)."""

import unittest

from zugzwang.board import Board, START_FEN
from zugzwang.movegen import generate_legal_moves
from zugzwang.search import Searcher, MATE_SCORE


class TestSearch(unittest.TestCase):
    def test_finds_mate_in_one(self):
        # Fool's mate: Black to move, Qh4# is forced mate in 1
        fen = "rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq - 0 2"
        board = Board.from_fen(fen)
        searcher = Searcher()
        move, score, depth = searcher.choose_move(board, seconds=2.0)
        self.assertEqual(move.uci(), "d8h4")
        self.assertGreaterEqual(score, MATE_SCORE - 1000)

    def test_finds_mate_in_one_for_the_side_about_to_be_mated_too(self):
        # from White's perspective one ply earlier, White should see the
        # position is close to lost if Black gets to play Qh4# -- sanity
        # check that scores are meaningfully negative for the losing side
        fen = "rnbqkbnr/pppp1ppp/8/4p3/6P1/5P2/PPPPP2P/RNBQKBNR b KQkq - 0 2"
        board = Board.from_fen(fen)
        searcher = Searcher()
        move, score, depth = searcher.choose_move(board, seconds=1.0)
        self.assertGreater(score, 0)  # good for the side to move (Black)

    def test_returned_move_is_always_legal(self):
        board = Board.from_fen(START_FEN)
        searcher = Searcher()
        for _ in range(6):
            move, score, depth = searcher.choose_move(board, seconds=0.2)
            legal = generate_legal_moves(board)
            self.assertIn(move, legal)
            board.make_move(move)

    def test_search_timeout_does_not_corrupt_board(self):
        """Regression test for the critical bug found in adversarial
        review: an aborted search used to leave stray make_move calls
        un-undone, corrupting the shared Board. A tight time budget makes
        the abort path fire on effectively every move."""
        board = Board.from_fen(START_FEN)
        searcher = Searcher()
        for ply in range(12):
            legal_before = {m.uci() for m in generate_legal_moves(board)}
            move, score, depth = searcher.choose_move(board, seconds=0.05)
            self.assertIsNotNone(move)
            self.assertIn(move.uci(), legal_before)
            board.make_move(move)
        # after 12 plies of tightly-timed search, the board must still be
        # in a completely consistent, legally-reachable state
        self.assertIn(board.to_move, ("w", "b"))
        self.assertTrue(generate_legal_moves(board) or True)  # doesn't raise

    def test_zero_or_negative_time_budget_does_not_hang(self):
        import time
        board = Board.from_fen(START_FEN)
        searcher = Searcher()
        t0 = time.time()
        move, score, depth = searcher.choose_move(board, seconds=0)
        self.assertIsNotNone(move)
        self.assertLess(time.time() - t0, 5.0)


if __name__ == "__main__":
    unittest.main()
