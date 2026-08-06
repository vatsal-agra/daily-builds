"""Evaluation correctness: symmetry (flipping colors flips the score) and
the pieces of the tapered midgame/endgame scheme behave sanely."""

import unittest

from zugzwang.board import Board
from zugzwang.evaluate import evaluate, game_phase, MAX_PHASE


def flip_fen(fen):
    """Mirror a FEN vertically and swap piece colors -- an equal-and-
    opposite position should evaluate to the exact negated score."""
    placement, stm, castling, ep, hm, fm = fen.split()
    rows = placement.split("/")
    flipped_rows = []
    for row in reversed(rows):
        flipped_row = "".join(
            ch if ch.isdigit() else (ch.lower() if ch.isupper() else ch.upper())
            for ch in row
        )
        flipped_rows.append(flipped_row)
    new_placement = "/".join(flipped_rows)
    new_stm = "b" if stm == "w" else "w"
    new_castling = "".join(c.lower() if c.isupper() else c.upper() for c in castling) \
        if castling != "-" else "-"
    if ep != "-":
        new_ep = ep[0] + str(9 - int(ep[1]))
    else:
        new_ep = "-"
    return f"{new_placement} {new_stm} {new_castling} {new_ep} {hm} {fm}"


class TestEvalSymmetry(unittest.TestCase):
    def test_symmetry_across_several_positions(self):
        fens = [
            "rnbqkbnr/pppppppp/8/8/4P3/8/PPPP1PPP/RNBQKBNR b KQkq e3 0 1",
            "r1bqkbnr/pppp1ppp/2n5/4p3/2B1P3/5N2/PPPP1PPP/RNBQK2R b KQkq - 3 3",
            "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        ]
        for fen in fens:
            with self.subTest(fen=fen):
                score = evaluate(Board.from_fen(fen))
                flipped_score = evaluate(Board.from_fen(flip_fen(fen)))
                self.assertEqual(score, -flipped_score)


class TestGamePhase(unittest.TestCase):
    def test_full_material_is_max_phase(self):
        from zugzwang.board import START_FEN
        self.assertEqual(game_phase(Board.from_fen(START_FEN)), MAX_PHASE)

    def test_bare_kings_is_zero_phase(self):
        board = Board.from_fen("4k3/8/8/8/8/8/8/4K3 w - - 0 1")
        self.assertEqual(game_phase(board), 0)


if __name__ == "__main__":
    unittest.main()
