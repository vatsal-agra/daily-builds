"""Zero-dependency local web server: a small JSON API over the real engine,
backing the interactive board in web/index.html. No chess logic is
duplicated in JavaScript -- every legality check, move, and engine reply
goes through this server, which is just this package's board/search/pgn
modules wired to HTTP.
"""

import json
import os
import argparse
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import urlparse, parse_qs

from .board import Board, START_FEN, WHITE, BLACK, parse_square, square_name
from .movegen import generate_legal_moves, game_state, is_in_check
from .search import Searcher
from .pgn import move_to_san, game_to_pgn, replay_pgn
from .zobrist import hash_board
from . import book as opening_book

WEB_DIR = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "web")

STATE_MESSAGES = {
    "checkmate": "Checkmate",
    "stalemate": "Stalemate -- draw",
    "draw_fifty": "Draw -- fifty-move rule",
    "draw_insufficient": "Draw -- insufficient material",
    "draw_repetition": "Draw -- threefold repetition",
}


class GameSession:
    def __init__(self):
        self.searcher = Searcher()
        self.book = opening_book.OpeningBook()
        self.use_book = True
        self.reset()

    def reset(self, fen=None, human_color=WHITE, think_time=2.0):
        self.board = Board.from_fen(fen) if fen else Board.from_fen(START_FEN)
        self.human_color = human_color
        self.think_time = think_time
        self.san_history = []
        self.uci_history = []
        self.position_history = [hash_board(self.board)]
        self.searcher.tt.clear()
        self.last_engine_info = None

    def to_state(self):
        legal = generate_legal_moves(self.board)
        state = game_state(self.board, self.position_history)
        over = state != "ongoing"
        return {
            "fen": self.board.to_fen(),
            "to_move": "white" if self.board.to_move == WHITE else "black",
            "human_color": "white" if self.human_color == WHITE else "black",
            "in_check": is_in_check(self.board, self.board.to_move),
            "game_over": over,
            "state": state,
            "message": STATE_MESSAGES.get(state),
            "legal_moves": [m.uci() for m in legal],
            "san_history": self.san_history,
            "uci_history": self.uci_history,
            "last_move": self.uci_history[-1] if self.uci_history else None,
            "engine_info": self.last_engine_info,
        }

    def apply_move(self, move):
        legal = generate_legal_moves(self.board)
        san = move_to_san(self.board, move, legal)
        self.board.make_move(move)
        self.san_history.append(san)
        self.uci_history.append(move.uci())
        self.position_history.append(hash_board(self.board))
        return san

    def find_legal_move(self, frm, to, promotion=None):
        for m in generate_legal_moves(self.board):
            if m.frm == frm and m.to == to:
                if promotion:
                    if m.promotion and m.promotion.lower() == promotion.lower():
                        return m
                elif not m.promotion:
                    return m
        return None

    def engine_move(self):
        move = self.book.lookup(self.board, self.san_history) if self.use_book else None
        if move is not None:
            self.last_engine_info = {"source": "book"}
        else:
            move, score, depth = self.searcher.choose_move(self.board, seconds=self.think_time)
            if move is None:
                return None
            self.last_engine_info = {
                "source": "search", "depth": depth, "score": score,
                "nodes": self.searcher.nodes,
            }
        san = self.apply_move(move)
        return san


SESSION = GameSession()


class Handler(BaseHTTPRequestHandler):
    server_version = "Zugzwang/1.0"

    def log_message(self, fmt, *args):
        pass  # keep stdout clean; errors still surface via 4xx/5xx JSON bodies

    def _send_json(self, payload, status=200):
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except OSError:
            self._send_json({"error": "not found"}, 404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw.decode("utf-8"))
        except json.JSONDecodeError:
            return {}

    def do_GET(self):
        parsed = urlparse(self.path)
        path = parsed.path

        if path == "/" or path == "/index.html":
            self._send_file(os.path.join(WEB_DIR, "index.html"), "text/html; charset=utf-8")
        elif path == "/api/state":
            self._send_json(SESSION.to_state())
        elif path == "/api/moves":
            qs = parse_qs(parsed.query)
            square_str = qs.get("square", [None])[0]
            if not square_str:
                self._send_json({"error": "missing square"}, 400)
                return
            try:
                frm = parse_square(square_str)
            except (ValueError, IndexError):
                self._send_json({"error": "bad square"}, 400)
                return
            moves = [m for m in generate_legal_moves(SESSION.board) if m.frm == frm]
            dests = []
            seen = set()
            for m in moves:
                key = (m.to, bool(m.promotion))
                if key in seen:
                    continue
                seen.add(key)
                dests.append({"to": square_name(m.to), "capture": bool(m.captured) or m.is_ep,
                              "promotion": bool(m.promotion)})
            self._send_json({"from": square_str, "moves": dests})
        elif path == "/api/pgn":
            self._send_json({"pgn": game_to_pgn(SESSION.san_history)})
        else:
            self._send_json({"error": "not found"}, 404)

    def do_POST(self):
        parsed = urlparse(self.path)
        path = parsed.path
        data = self._read_json()

        if path == "/api/new":
            fen = data.get("fen") or None
            human_color = BLACK if data.get("human_color") == "black" else WHITE
            think_time = float(data.get("think_time", 2.0))
            try:
                SESSION.reset(fen=fen, human_color=human_color, think_time=think_time)
            except Exception as e:
                self._send_json({"error": f"bad FEN: {e}"}, 400)
                return
            self._send_json(SESSION.to_state())

        elif path == "/api/move":
            uci = data.get("uci", "")
            if len(uci) < 4:
                self._send_json({"error": "malformed move"}, 400)
                return
            try:
                frm = parse_square(uci[0:2])
                to = parse_square(uci[2:4])
            except (ValueError, IndexError):
                self._send_json({"error": "malformed move"}, 400)
                return
            promo = uci[4:5] if len(uci) > 4 else None
            move = SESSION.find_legal_move(frm, to, promo)
            if move is None:
                self._send_json({"error": "illegal move"}, 400)
                return
            SESSION.apply_move(move)
            self._send_json(SESSION.to_state())

        elif path == "/api/engine_move":
            state = game_state(SESSION.board, SESSION.position_history)
            if state != "ongoing":
                self._send_json(SESSION.to_state())
                return
            san = SESSION.engine_move()
            if san is None:
                self._send_json({"error": "no legal moves"}, 400)
                return
            self._send_json(SESSION.to_state())

        elif path == "/api/load_pgn":
            pgn_text = data.get("pgn", "")
            try:
                board, history, position_hashes = replay_pgn(pgn_text)
            except (ValueError, IndexError) as e:
                self._send_json({"error": f"could not parse PGN: {e}"}, 400)
                return
            SESSION.reset()
            SESSION.board = board
            SESSION.san_history = [h[0] for h in history]
            SESSION.uci_history = [h[1] for h in history]
            SESSION.position_history = position_hashes
            self._send_json(SESSION.to_state())

        else:
            self._send_json({"error": "not found"}, 404)


def run(host="127.0.0.1", port=8765, think_time=2.0):
    SESSION.think_time = think_time
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Zugzwang web UI: http://{host}:{port}/")
    print("Ctrl-C to stop.")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


def main():
    parser = argparse.ArgumentParser(description="Serve the Zugzwang web UI.")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--think-time", type=float, default=2.0)
    args = parser.parse_args()
    run(args.host, args.port, args.think_time)


if __name__ == "__main__":
    main()
