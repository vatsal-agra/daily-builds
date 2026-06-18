"""Gambit test suite — exercises every feature with objective checks."""

import json
import os
import random
import sys
import threading
import unittest
import urllib.request
from http.server import ThreadingHTTPServer

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from gambit.board import Board, move_uci, WHITE, BLACK
from gambit.movegen import legal_moves, in_check
from gambit.perft import perft, PERFT_POSITIONS
from gambit.san import to_san, from_san, game_to_pgn
from gambit.eval import evaluate
from gambit.engine import (
    Engine, play_game, format_score, result_text, _insufficient_material,
)
from gambit.search import Search


class TestPerft(unittest.TestCase):
    """Move generation vs published node counts — the primary correctness gate."""

    def test_perft_oracle(self):
        budgets = {"startpos": 4, "kiwipete": 3, "position3": 4,
                   "position4": 3, "position5": 3}
        for name, fen, exp in PERFT_POSITIONS:
            maxd = budgets[name]
            for d in sorted(exp):
                if d > maxd:
                    continue
                with self.subTest(pos=name, depth=d):
                    self.assertEqual(perft(Board.from_fen(fen), d), exp[d])


class TestMakeUnmake(unittest.TestCase):
    def test_invariants_fuzz(self):
        random.seed(7)
        fens = [p[1] for p in PERFT_POSITIONS]

        def walk(b, d):
            for mv in legal_moves(b):
                fen0, z0 = b.to_fen(), b.zobrist
                b.make_move(mv)
                self.assertEqual(b.zobrist, b._compute_zobrist())
                if d > 1 and random.random() < 0.12:
                    walk(b, d - 1)
                b.unmake_move()
                self.assertEqual(b.to_fen(), fen0)
                self.assertEqual(b.zobrist, z0)

        for fen in fens:
            walk(Board.from_fen(fen), 4)

    def test_null_move(self):
        b = Board.from_fen(PERFT_POSITIONS[1][1])
        fen0, z0 = b.to_fen(), b.zobrist
        b.make_null_move()
        self.assertNotEqual(b.side, Board.from_fen(fen0).side)
        b.unmake_null_move()
        self.assertEqual(b.to_fen(), fen0)
        self.assertEqual(b.zobrist, z0)


class TestFEN(unittest.TestCase):
    def test_roundtrip(self):
        for _, fen, _ in PERFT_POSITIONS:
            self.assertEqual(Board.from_fen(fen).to_fen(), fen)

    def test_rejects_bad(self):
        bad = [
            "garbage",
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq z9 0 1",  # bad ep
            "8/8/8/8/8/8/8/8 w - - 0 1",  # no kings
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBKR w KQkq - 0 1",  # 2 white kings
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNRR w - - 0 1",  # rank != 8
        ]
        for f in bad:
            with self.subTest(fen=f):
                self.assertRaises(ValueError, Board.from_fen, f)


class TestSAN(unittest.TestCase):
    def test_roundtrip(self):
        random.seed(3)
        b = Board.startpos()
        for _ in range(60):
            moves = legal_moves(b)
            if not moves:
                break
            for mv in moves:
                self.assertEqual(from_san(b, to_san(b, mv)), mv)
            b.make_move(random.choice(moves))

    def test_known_san(self):
        b = Board.startpos()
        self.assertEqual(to_san(b, from_san(b, "e4")), "e4")
        b.make_move(from_san(b, "e4"))
        b.make_move(from_san(b, "e5"))
        self.assertEqual(to_san(b, from_san(b, "Nf3")), "Nf3")

    def test_castling_and_mate_san(self):
        # back-rank mate: Ra8#
        b = Board.from_fen("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
        mv = from_san(b, "Ra8")
        self.assertEqual(to_san(b, mv), "Ra8#")

    def test_pgn_roundtrip(self):
        g = play_game(Engine(depth=2, movetime=0.5), Engine(depth=2, movetime=0.5),
                      max_moves=12)
        sans = [m["san"] for m in g["moves"]]
        pgn = game_to_pgn(g["start_fen"], sans, g["result"])
        # replay the SAN list to confirm every move parses legally
        b = Board.from_fen(g["start_fen"])
        for s in sans:
            b.make_move(from_san(b, s))
        self.assertIn("1.", pgn)


class TestEval(unittest.TestCase):
    @staticmethod
    def _mirror(fen):
        parts = fen.split()
        rows = parts[0].split("/")[::-1]
        swap = lambda r: "".join(c.lower() if c.isupper() else c.upper() for c in r)
        rows = [swap(r) for r in rows]
        side = "b" if parts[1] == "w" else "w"
        cast = parts[2]
        if cast != "-":
            nc = "".join({"K": "k", "Q": "q", "k": "K", "q": "Q"}.get(c, c) for c in cast)
            cast = "".join(sorted(nc, key="KQkq".index))
        return f"{'/'.join(rows)} {side} {cast} - 0 1"

    def test_symmetry(self):
        for _, fen, _ in PERFT_POSITIONS:
            base = " ".join(fen.split()[:3]) + " - 0 1"
            b = Board.from_fen(base)
            m = Board.from_fen(self._mirror(base))
            self.assertEqual(evaluate(b), evaluate(m))

    def test_startpos_balanced(self):
        self.assertEqual(evaluate(Board.startpos()), 0)

    def test_material_advantage(self):
        # white up a queen should evaluate strongly for white
        b = Board.from_fen("rnb1kbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")
        self.assertGreater(evaluate(b), 600)


class TestSearch(unittest.TestCase):
    def test_mate_in_one(self):
        b = Board.from_fen("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
        res = Engine(depth=3).best_move(b)
        self.assertEqual(move_uci(res.best_move), "a1a8")
        self.assertGreaterEqual(res.score, 29000)

    def test_mate_played_out(self):
        # engine should be able to deliver mate within a few moves vs itself
        b = Board.from_fen("6k1/5ppp/8/8/8/8/8/R5K1 w - - 0 1")
        mv = Engine(depth=3).best_move(b).best_move
        b.make_move(mv)
        self.assertTrue(in_check(b, b.side))
        self.assertEqual(legal_moves(b), [])  # checkmate: no legal replies

    def test_stalemate_detected(self):
        b = Board.from_fen("7k/5Q2/6K1/8/8/8/8/8 b - - 0 1")
        self.assertEqual(legal_moves(b), [])
        self.assertFalse(in_check(b, b.side))
        self.assertEqual(result_text(b), "1/2-1/2")

    def test_finds_only_move(self):
        # king in check with a single legal reply
        b = Board.from_fen("4k3/8/8/8/8/8/8/r3K3 w - - 0 1")
        legal = legal_moves(b)
        res = Engine(depth=3).best_move(b)
        self.assertIn(res.best_move, legal)

    def test_tt_consistency(self):
        fen = "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1"
        on = Engine(depth=4, use_tt=True).best_move(Board.from_fen(fen))
        off = Engine(depth=4, use_tt=False).best_move(Board.from_fen(fen))
        self.assertEqual(on.score, off.score)
        self.assertLessEqual(on.nodes, off.nodes)

    def test_movetime_budget(self):
        b = Board.startpos()
        res = Engine(depth=64, movetime=0.5).best_move(b)
        self.assertLess(res.time, 2.0)
        self.assertTrue(res.best_move)


class TestGameRules(unittest.TestCase):
    def test_insufficient_material(self):
        draws = ["8/8/8/4k3/8/8/8/4K3 w - - 0 1",      # KvK
                 "8/8/8/4k3/8/8/8/4K2B w - - 0 1",      # KBvK
                 "8/8/8/4k3/8/8/8/4K1N1 w - - 0 1"]     # KNvK
        not_draws = ["8/8/8/4k3/8/2b5/8/4K2B w - - 0 1",   # KBvKB
                     "8/8/8/4k3/8/2n5/8/4K1N1 w - - 0 1",   # KNvKN
                     "8/8/8/4k3/8/8/8/3RK3 w - - 0 1"]      # KRvK
        for f in draws:
            self.assertTrue(_insufficient_material(Board.from_fen(f)), f)
        for f in not_draws:
            self.assertFalse(_insufficient_material(Board.from_fen(f)), f)

    def test_full_game_terminates_legally(self):
        g = play_game(Engine(depth=3, movetime=0.6), Engine(depth=3, movetime=0.6),
                      max_moves=80)
        # every recorded move must have been legal in its position
        b = Board.from_fen(g["start_fen"])
        for m in g["moves"]:
            legal = {move_uci(x).replace(" ", "") for x in legal_moves(b)}
            self.assertIn(m["uci"].replace(" ", ""), legal)
            b.make_move(from_san(b, m["san"]))
        self.assertIn(g["result"], ("1-0", "0-1", "1/2-1/2", "*"))

    def test_threefold_draw(self):
        # shuffle knights back and forth to force a repetition draw
        b = Board.from_fen("4k3/8/8/8/8/8/8/4K1N1 w - - 0 1")
        seq = ["Nf3", "Ke7", "Ng1", "Ke8", "Nf3", "Ke7", "Ng1", "Ke8"]
        counts = {b.zobrist: 1}
        for s in seq:
            b.make_move(from_san(b, s))
            counts[b.zobrist] = counts.get(b.zobrist, 0) + 1
        self.assertEqual(result_text(b, counts), "1/2-1/2")


class TestServer(unittest.TestCase):
    def test_play_endpoint(self):
        from gambit.server import Handler
        Handler.engine = Engine(depth=2, movetime=0.5)
        srv = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
        port = srv.server_address[1]
        threading.Thread(target=srv.serve_forever, daemon=True).start()
        try:
            base = f"http://127.0.0.1:{port}"
            new = json.loads(urllib.request.urlopen(base + "/api/new").read())
            self.assertEqual(new["turn"], "w")
            req = urllib.request.Request(
                base + "/api/move",
                data=json.dumps({"fen": new["fen"], "uci": "e2e4"}).encode(),
                headers={"Content-Type": "application/json"})
            r = json.loads(urllib.request.urlopen(req).read())
            self.assertEqual(r["human_san"], "e4")
            self.assertIsNotNone(r["engine"])
            # illegal move -> HTTP 400
            bad = urllib.request.Request(
                base + "/api/move",
                data=json.dumps({"fen": new["fen"], "uci": "e2e5"}).encode(),
                headers={"Content-Type": "application/json"})
            with self.assertRaises(urllib.error.HTTPError) as cm:
                urllib.request.urlopen(bad)
            self.assertEqual(cm.exception.code, 400)
        finally:
            srv.shutdown()
            srv.server_close()


if __name__ == "__main__":
    unittest.main(verbosity=2)
