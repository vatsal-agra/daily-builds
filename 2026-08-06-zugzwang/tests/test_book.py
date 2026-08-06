"""Every hand-written opening-book line must actually be a legal,
correctly-notated sequence -- a wrong SAN token fails silently (falls back
to search) rather than crashing, so this needs an explicit check."""

import unittest

from zugzwang.board import Board, START_FEN
from zugzwang.pgn import san_to_move
from zugzwang.book import OPENING_LINES, OpeningBook


class TestOpeningBook(unittest.TestCase):
    def test_every_line_is_legal(self):
        for i, line in enumerate(OPENING_LINES):
            with self.subTest(line=i):
                board = Board.from_fen(START_FEN)
                for san in line:
                    move = san_to_move(board, san)
                    board.make_move(move)

    def test_lookup_returns_a_legal_move_from_empty_history(self):
        board = Board.from_fen(START_FEN)
        book = OpeningBook()
        move = book.lookup(board, [])
        self.assertIsNotNone(move)

    def test_lookup_returns_none_once_out_of_book(self):
        board = Board.from_fen(START_FEN)
        book = OpeningBook()
        move = book.lookup(board, ["Zzzz", "made", "up", "history", "not", "in", "any", "line"])
        self.assertIsNone(move)


if __name__ == "__main__":
    unittest.main()
