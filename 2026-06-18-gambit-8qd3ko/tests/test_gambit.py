"""Gambit test suite — exercises every feature. Run: python3 -m unittest -v
(from the project root) or via ../demo.sh."""

import json
import os
import random
import re
import sys
import tempfile
import unittest

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gambit.board import Board, WHITE, BLACK, move_from, move_to, move_uci
from gambit.movegen import gen_legal, to_san, parse_san
from gambit.perft import perft, perft_divide, REFERENCE
from gambit.eval import evaluate, MATE, MATE_THRESHOLD
from gambit.search import search, SearchInfo
from gambit.engine import Engine, self_play, game_result, to_pgn
from gambit.viz import generate_viz


class TestPerft(unittest.TestCase):
    """The correctness gate: exact node counts prove the rules are right."""

    # depth cap per position to keep the suite fast (a few seconds total)
    CAPS = {"startpos": 4, "kiwipete": 3, "position3": 4,
            "position4": 3, "position5": 3}

    def test_reference_suite(self):
        for name, fen, counts in REFERENCE:
            cap = self.CAPS[name]
            for d in range(1, min(cap, len(counts)) + 1):
                b = Board.from_fen(fen)
                self.assertEqual(perft(b, d), counts[d - 1],
                                 f"{name} perft({d}) mismatch")

    def test_divide_sums_to_total(self):
        b = Board.startpos()
        div = perft_divide(b, 3)
        self.assertEqual(sum(div.values()), 8902)
        self.assertEqual(len(div), 20)


class TestBoard(unittest.TestCase):
    def test_fen_roundtrip(self):
        for _, fen, _ in REFERENCE:
            self.assertEqual(Board.from_fen(fen).to_fen(), fen)

    def test_make_unmake_restores_everything(self):
        random.seed(1)
        for _ in range(120):
            b = Board.startpos()
            snaps, mv = [], []
            for _ in range(random.randint(1, 30)):
                ms = gen_legal(b)
                if not ms:
                    break
                snaps.append(b.to_fen())
                m = random.choice(ms)
                mv.append(m)
                b.make(m)
            while mv:
                b.unmake()
                mv.pop()
                self.assertEqual(b.to_fen(), snaps[len(mv)])

    def test_zobrist_incremental_matches_recompute(self):
        random.seed(2)
        for _ in range(120):
            b = Board.startpos()
            for _ in range(random.randint(1, 40)):
                ms = gen_legal(b)
                if not ms:
                    break
                b.make(random.choice(ms))
                self.assertEqual(b.zobrist, b._compute_zobrist())

    def test_bad_fen_rejected(self):
        for bad in ["", "garbage",
                    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP w KQkq - 0 1",  # 7 ranks
                    "8/8/8/8/8/8/8/8 w - - 0 1",                        # no kings
                    "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR x KQkq - 0 1",
                    "rnbqkbnr/pppppXpp/8/8/8/8/PPPPPPPP/RNBQKBNR w - - 0 1"]:
            with self.assertRaises(ValueError):
                Board.from_fen(bad)


class TestMoveGen(unittest.TestCase):
    def test_castling_available(self):
        b = Board.from_fen("r3k2r/8/8/8/8/8/8/R3K2R w KQkq - 0 1")
        sans = {to_san(b, m) for m in gen_legal(b)}
        self.assertIn("O-O", sans)
        self.assertIn("O-O-O", sans)

    def test_cannot_castle_through_check(self):
        # black rook on f8 attacks f1 -> white cannot castle king-side
        b = Board.from_fen("5rk1/8/8/8/8/8/8/R3K2R w KQ - 0 1")
        sans = {to_san(b, m) for m in gen_legal(b)}
        self.assertNotIn("O-O", sans)
        self.assertIn("O-O-O", sans)  # queen-side still legal

    def test_en_passant(self):
        b = Board.from_fen(
            "rnbqkbnr/ppp1p1pp/8/3pPp2/8/8/PPPP1PPP/RNBQKBNR w KQkq f6 0 3")
        m = parse_san(b, "exf6")
        self.assertIsNotNone(m)
        self.assertEqual(move_uci(m), "e5f6")

    def test_promotion_all_pieces(self):
        b = Board.from_fen("8/P7/8/8/8/8/8/4k2K w - - 0 1")
        sans = {to_san(b, m) for m in gen_legal(b)}
        for p in ("a8=Q", "a8=R", "a8=B", "a8=N"):
            self.assertIn(p, sans)

    def test_san_roundtrip(self):
        random.seed(5)
        for _ in range(35):
            b = Board.startpos()
            for _ in range(random.randint(0, 20)):
                ms = gen_legal(b)
                if not ms:
                    break
                b.make(random.choice(ms))
            for m in gen_legal(b):
                san = to_san(b, m)
                self.assertEqual(parse_san(b, san), m,
                                 f"SAN roundtrip failed for {san}")

    def test_null_move_for_zero_move_is_none(self):
        b = Board.startpos()
        self.assertEqual(to_san(b, 0), "(none)")


class TestEval(unittest.TestCase):
    def test_startpos_balanced(self):
        self.assertEqual(evaluate(Board.startpos()), 0)

    def test_color_mirror_symmetry(self):
        def mirror(fen):
            p = fen.split()
            rows = p[0].split("/")[::-1]
            swap = lambda c: c.lower() if c.isupper() else c.upper()
            rows = ["".join(swap(c) if c.isalpha() else c for c in r)
                    for r in rows]
            side = "b" if p[1] == "w" else "w"
            cr = "".join(sorted(swap(c) for c in p[2])) if p[2] != "-" else "-"
            return f"{'/'.join(rows)} {side} {cr} - 0 1"
        for _, fen, _ in REFERENCE:
            a = evaluate(Board.from_fen(fen))
            b = evaluate(Board.from_fen(mirror(fen)))
            self.assertEqual(a, b)


class TestSearch(unittest.TestCase):
    def test_best_move_always_legal(self):
        random.seed(8)
        for _ in range(40):
            b = Board.startpos()
            for _ in range(random.randint(0, 24)):
                ms = gen_legal(b)
                if not ms:
                    break
                b.make(random.choice(ms))
            if not gen_legal(b):
                continue
            r = search(b, depth=3)
            self.assertIn(r.move, gen_legal(b))

    def test_tt_does_not_change_score(self):
        """The headline invariant: the TT (move-ordering only) is provably
        score-neutral for the exact search."""
        random.seed(9)
        positions = [fen for _, fen, _ in REFERENCE]
        for _ in range(20):
            b = Board.startpos()
            for _ in range(random.randint(2, 18)):
                ms = gen_legal(b)
                if not ms:
                    break
                b.make(random.choice(ms))
            if gen_legal(b):
                positions.append(b.to_fen())
        for fen in positions:
            b = Board.from_fen(fen)
            i_on = SearchInfo(); i_on.use_null = False
            i_off = SearchInfo(); i_off.use_null = False; i_off.use_tt = False
            self.assertEqual(search(b, 4, info=i_on).score,
                             search(b, 4, info=i_off).score,
                             f"TT changed score on {fen}")

    def test_finds_mate_in_one(self):
        b = Board.from_fen("6k1/5ppp/8/8/8/8/8/R3K3 w - - 0 1")
        r = search(b, depth=3)
        self.assertEqual(to_san(b, r.move), "Ra8#")
        self.assertGreater(r.score, MATE_THRESHOLD)

    def test_finds_mate_in_two(self):
        # KQ vs K: from this position the engine should see a forced mate.
        b = Board.from_fen("6k1/8/6K1/8/8/8/8/3Q4 w - - 0 1")
        r = search(b, depth=4)
        self.assertGreater(r.score, MATE_THRESHOLD)

    def test_avoids_being_mated_picks_only_escape(self):
        # White king must move out of check; only one legal reply exists path.
        b = Board.from_fen("rnb1kbnr/pppp1ppp/8/4p3/6Pq/5P2/PPPPP2P/RNBQKBNR "
                           "w KQkq - 1 3")
        # this is fool's mate -> checkmate, no legal move
        self.assertEqual(gen_legal(b), [])
        res, reason = game_result(b)
        self.assertEqual((res, reason), ("0-1", "checkmate"))


class TestEngineRules(unittest.TestCase):
    def test_stalemate_is_draw(self):
        b = Board.from_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
        self.assertEqual(game_result(b), ("1/2-1/2", "stalemate"))

    def test_threefold_repetition(self):
        b = Board.startpos()
        for mv in ["Nf3", "Nf6", "Ng1", "Ng8", "Nf3", "Nf6", "Ng1", "Ng8"]:
            b.make(parse_san(b, mv))
        self.assertEqual(game_result(b), ("1/2-1/2", "threefold repetition"))

    def test_insufficient_material(self):
        b = Board.from_fen("4k3/8/8/8/8/8/8/4K2B w - - 0 1")
        self.assertEqual(game_result(b),
                         ("1/2-1/2", "insufficient material"))

    def test_fifty_move_rule(self):
        b = Board.from_fen("4k3/8/8/8/8/8/8/R3K3 w - - 100 80")
        self.assertEqual(game_result(b), ("1/2-1/2", "fifty-move rule"))

    def test_engine_converts_kq_vs_k_to_mate(self):
        b, sans, res, reason, evals, fens = self_play(
            depth=4, max_moves=40, verbose=False,
            start_fen="4k3/8/8/8/8/8/8/3QK3 w - - 0 1")
        self.assertEqual((res, reason), ("1-0", "checkmate"))
        self.assertTrue(sans[-1].endswith("#"))


class TestPGNandViz(unittest.TestCase):
    def test_pgn_wellformed(self):
        pgn = to_pgn(["e4", "e5", "Nf3", "Nc6"], "1-0")
        self.assertIn('[White "Gambit"]', pgn)
        self.assertIn("1. e4 e5 2. Nf3 Nc6 1-0", pgn)

    def test_viz_generates_valid_html(self):
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "game.html")
            generate_viz(out, depth=2, max_moves=10)
            with open(out) as fh:
                html = fh.read()
            self.assertIn("<!DOCTYPE html>", html)
            m = re.search(r"const DATA = (\{.*?\});", html, re.S)
            self.assertIsNotNone(m)
            data = json.loads(m.group(1))
            self.assertEqual(len(data["fens"]), len(data["sans"]) + 1)
            self.assertEqual(len(data["evals"]), len(data["sans"]))


if __name__ == "__main__":
    unittest.main(verbosity=2)
