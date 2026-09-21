"""Server-backed interactive play: a real Python process holds the actual
network + MCTS state; the browser only renders the board and the MCTS
visit-count/value visualization and sends move choices over HTTP as JSON.
No game logic is duplicated in JavaScript (same pattern as this repo's
Gambit/Impulse builds) -- the client cannot even tell whether a move is
legal without asking the server.

Stdlib-only (`http.server`), no Flask/Django, matching this repo's
established precedent for these interactive builds.
"""

from __future__ import annotations
import json
import os
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import numpy as np

from .games.tictactoe import TicTacToe
from .games.connect4 import Connect4Jr
from .checkpoint import load_checkpoint
from .mcts import MCTS, sample_action

GAMES = {"tictactoe": TicTacToe, "connect4jr": Connect4Jr}

STATIC_DIR = os.path.join(os.path.dirname(__file__), "..", "static")


class Session:
    """One human-vs-agent game. All mutable state lives here, guarded by
    a lock -- this is the ONE piece of shared mutable state in the whole
    codebase (everything else, including MCTS itself, is built to be
    stateless/immutable specifically to avoid this kind of hazard; a live
    server inherently needs somewhere to hold "the current game")."""

    def __init__(self):
        self.lock = threading.Lock()
        self.game_name = "tictactoe"
        self.game = TicTacToe
        self.net = None
        self.n_simulations = 200
        self.c_puct = 1.5
        self.state = self.game.initial_state()
        self.human_player = 1
        self.rng = np.random.default_rng()
        self._load_net("tictactoe")

    def _load_net(self, game_name: str):
        game = GAMES[game_name]
        ckpt_dir = os.path.join(os.path.dirname(__file__), "..", "checkpoints", game_name)
        candidates = sorted(
            (f for f in os.listdir(ckpt_dir) if f.endswith(".npz")),
        ) if os.path.isdir(ckpt_dir) else []
        if not candidates:
            raise RuntimeError(f"No checkpoints found for {game_name} in {ckpt_dir}")
        best = candidates[-1]  # lexicographic == highest generation, gen### is zero-padded
        self.net = load_checkpoint(os.path.join(ckpt_dir, best))
        self.game_name = game_name
        self.game = game
        self.n_simulations = 200 if game_name == "tictactoe" else 150
        self.checkpoint_used = best

    def _search(self, state):
        """Runs exactly one MCTS search from `state` (NO Dirichlet noise --
        this is interactive human-facing play, not self-play data
        generation) and returns (visit_counts, root). Both the live
        visualization and the agent's actual move are derived from this
        SAME search (not two independent searches), so what the browser
        shows is provably what actually decided the move, not a
        cosmetically-similar second run."""
        mcts = MCTS(self.game, self.net, c_puct=self.c_puct,
                    n_simulations=self.n_simulations, rng=self.rng)
        return mcts.run(state, add_root_noise=False, return_root=True)

    def _viz_from_search(self, state, visit_counts, root):
        total = sum(visit_counts.values()) or 1
        per_action = {}
        for a in self.game.legal_moves(state):
            n = visit_counts.get(a, 0)
            q = (root.W[a] / n) if n > 0 else 0.0
            per_action[a] = {
                "visits": n,
                "visit_frac": n / total,
                "q": q,
                "prior": root.P.get(a, 0.0),
            }
        x = self.game.encode(state)
        mask = self.game.legal_mask(state)
        raw_probs, raw_value = self.net.predict_one(x, mask)
        return {
            "visit_counts": per_action,
            "raw_policy": {a: float(raw_probs[a]) for a in self.game.legal_moves(state)},
            "raw_value": raw_value,
            "chosen_action": max(visit_counts, key=lambda a: visit_counts[a]) if visit_counts else None,
        }

    def reset(self, game_name: str, human_side: str):
        with self.lock:
            if game_name not in GAMES:
                raise ValueError(f"unknown game {game_name!r}; choices are {sorted(GAMES)}")
            side = str(human_side).upper()
            if side not in ("X", "O"):
                raise ValueError(f"human_side must be 'X' or 'O', got {human_side!r}")
            if game_name != self.game_name:
                self._load_net(game_name)
            self.state = self.game.initial_state()
            self.human_player = 1 if side == "X" else -1
            agent_viz = None
            if self.game.current_player(self.state) != self.human_player:
                agent_viz = self._agent_move()
            return self._public_state(agent_viz)

    def hint(self):
        """Runs a read-only search from the CURRENT state (whoever's turn
        it is) purely for the live visualization panel -- does not apply
        any move. Lets a person see what the search thinks about a
        position before either side actually moves, not only in
        hindsight after the agent has already moved."""
        with self.lock:
            if self.game.is_terminal(self.state):
                raise ValueError("game already over")
            visit_counts, root = self._search(self.state)
            return self._viz_from_search(self.state, visit_counts, root)

    def human_move(self, action: int):
        with self.lock:
            if self.game.is_terminal(self.state):
                raise ValueError("game already over")
            if self.game.current_player(self.state) != self.human_player:
                raise ValueError("not human's turn")
            legal = self.game.legal_moves(self.state)
            if action not in legal:
                raise ValueError(f"illegal move {action}; legal moves are {legal}")
            self.state = self.game.apply_move(self.state, action)
            agent_viz = None
            if not self.game.is_terminal(self.state):
                agent_viz = self._agent_move()
            return self._public_state(agent_viz)

    def _agent_move(self):
        visit_counts, root = self._search(self.state)
        viz = self._viz_from_search(self.state, visit_counts, root)
        action = sample_action(visit_counts, temperature=0.0, rng=self.rng)
        self.state = self.game.apply_move(self.state, action)
        viz["agent_action"] = action
        return viz

    def _public_state(self, agent_viz):
        terminal = self.game.is_terminal(self.state)
        winner = self.game.winner(self.state) if terminal else None
        return {
            "game": self.game_name,
            "board_rows": self.game.rows,
            "board_cols": self.game.cols,
            "state": _state_to_grid(self.game, self.state),
            "legal_moves": self.game.legal_moves(self.state),
            "current_player": self.game.current_player(self.state) if not terminal else None,
            "human_player": self.human_player,
            "terminal": terminal,
            "winner": winner,
            "agent_viz": agent_viz,
            "checkpoint": getattr(self, "checkpoint_used", None),
        }


def _state_to_grid(game, state):
    if game is TicTacToe:
        return {"cells": list(state)}
    if game is Connect4Jr:
        g = game._grid(state)
        return {"cells": g.tolist()}
    raise ValueError("unknown game")


SESSION = Session()


class Handler(BaseHTTPRequestHandler):
    def log_message(self, fmt, *args):
        pass  # keep stdout clean; errors are still surfaced via response bodies

    def _send_json(self, obj, status=200):
        body = json.dumps(obj).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_file(self, path, content_type):
        try:
            with open(path, "rb") as f:
                body = f.read()
        except FileNotFoundError:
            self._send_json({"error": "not found"}, status=404)
            return
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _read_json_body(self):
        length = int(self.headers.get("Content-Length", 0))
        if length == 0:
            return {}
        raw = self.rfile.read(length)
        try:
            return json.loads(raw)
        except json.JSONDecodeError:
            raise ValueError("malformed JSON body")

    def do_GET(self):
        if self.path == "/" or self.path == "/index.html":
            self._send_file(os.path.join(STATIC_DIR, "index.html"), "text/html; charset=utf-8")
        elif self.path == "/api/health":
            self._send_json({"ok": True})
        elif self.path.startswith("/api/state"):
            self._send_json(SESSION._public_state(None))
        else:
            self._send_json({"error": "not found"}, status=404)

    def do_POST(self):
        try:
            body = self._read_json_body()
        except ValueError as e:
            self._send_json({"error": str(e)}, status=400)
            return
        try:
            if self.path == "/api/reset":
                game_name = body.get("game", "tictactoe")
                human_side = body.get("human_side", "X")
                result = SESSION.reset(game_name, human_side)
                self._send_json(result)
            elif self.path == "/api/move":
                if "action" not in body:
                    raise ValueError("missing 'action'")
                try:
                    action = int(body["action"])
                except (TypeError, ValueError):
                    raise ValueError(f"'action' must be an integer, got {body['action']!r}")
                result = SESSION.human_move(action)
                self._send_json(result)
            elif self.path == "/api/hint":
                result = SESSION.hint()
                self._send_json(result)
            else:
                self._send_json({"error": "not found"}, status=404)
        except ValueError as e:
            self._send_json({"error": str(e)}, status=400)
        except Exception as e:  # last-resort: never leak a raw traceback to the client
            self._send_json({"error": f"internal error: {e}"}, status=500)


def run(host="127.0.0.1", port=8765):
    server = ThreadingHTTPServer((host, port), Handler)
    print(f"Sente server running at http://{host}:{port}/")
    server.serve_forever()


if __name__ == "__main__":
    import sys
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    run(port=port)
