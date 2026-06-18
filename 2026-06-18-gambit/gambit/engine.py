"""High-level engine API: pick a best move, analyse a position, and play a full
annotated game (engine vs engine) recording per-move SAN, score, depth and PV.
"""

from __future__ import annotations

from .board import Board, move_uci
from .movegen import legal_moves, in_check
from .search import Search, SearchResult, MATE_THRESHOLD
from .san import to_san
from .eval import MATE


class Engine:
    def __init__(self, depth: int = 4, movetime: float | None = None, use_tt: bool = True):
        self.depth = depth
        self.movetime = movetime
        self.search = Search(use_tt=use_tt)

    def best_move(self, board: Board, history: list | None = None) -> SearchResult:
        return self.search.search(board, max_depth=self.depth,
                                   movetime=self.movetime, history=history)

    def analyse(self, board: Board) -> dict:
        res = self.best_move(board)
        pv_san = _pv_to_san(board, res.pv)
        return {
            "fen": board.to_fen(),
            "best_move": move_uci(res.best_move) if res.best_move else None,
            "best_san": pv_san[0] if pv_san else None,
            "score": res.score,
            "score_str": format_score(res.score),
            "depth": res.depth,
            "nodes": res.nodes,
            "time": round(res.time, 3),
            "pv": pv_san,
        }


def format_score(score: int) -> str:
    if score >= MATE_THRESHOLD:
        return f"#{(MATE - score + 1) // 2}"
    if score <= -MATE_THRESHOLD:
        return f"#-{(MATE + score + 1) // 2}"
    return f"{score / 100:+.2f}"


def _pv_to_san(board: Board, pv: list) -> list:
    out = []
    n = 0
    for mv in pv:
        if mv not in legal_moves(board):
            break
        out.append(to_san(board, mv))
        board.make_move(mv)
        n += 1
    for _ in range(n):
        board.unmake_move()
    return out


def result_text(board: Board, history_counts: dict | None = None) -> str | None:
    """Return '1-0' / '0-1' / '1/2-1/2' if the game is over, else None."""
    moves = legal_moves(board)
    if not moves:
        if in_check(board, board.side):
            return "0-1" if board.side == 0 else "1-0"
        return "1/2-1/2"  # stalemate
    if board.halfmove >= 100:
        return "1/2-1/2"  # fifty-move
    if history_counts is not None and history_counts.get(board.zobrist, 0) >= 3:
        return "1/2-1/2"  # threefold
    if _insufficient_material(board):
        return "1/2-1/2"
    return None


def _insufficient_material(board: Board) -> bool:
    """Only the universally dead positions: at most a single minor piece on the
    whole board (K-vs-K, KN-vs-K, KB-vs-K). KB-vs-KB and KN-vs-KN are *not*
    automatic draws under the rules, so they are not flagged here."""
    from .board import piece_type, KING, BISHOP, KNIGHT
    minors = 0
    for sq in range(128):
        if sq & 0x88:
            continue
        p = board.squares[sq]
        if not p:
            continue
        pt = piece_type(p)
        if pt == KING:
            continue
        if pt in (BISHOP, KNIGHT):
            minors += 1
        else:
            return False  # a pawn, rook or queen exists -> not a dead draw
    return minors <= 1


def play_game(white: Engine, black: Engine, start_fen: str | None = None,
              max_moves: int = 200, verbose: bool = False) -> dict:
    """Play a full engine-vs-engine game; return an annotated record."""
    board = Board.from_fen(start_fen) if start_fen else Board.startpos()
    start = board.to_fen()
    history = [board.zobrist]
    counts = {board.zobrist: 1}
    moves = []  # list of dicts

    while len(moves) < max_moves:
        over = result_text(board, counts)
        if over is not None:
            break
        engine = white if board.side == 0 else black
        res = engine.best_move(board, history=history[:-1])
        mv = res.best_move
        if not mv:
            break
        san = to_san(board, mv)
        rec = {
            "ply": len(moves) + 1,
            "san": san,
            "uci": move_uci(mv),
            "fen_before": board.to_fen(),
            "score": res.score,
            "score_str": format_score(res.score),
            "depth": res.depth,
            "nodes": res.nodes,
            "time": round(res.time, 3),
            "side": "w" if board.side == 0 else "b",
        }
        moves.append(rec)
        if verbose:
            print(f"{rec['ply']:3}. {san:8} {rec['score_str']:>7}  "
                  f"d{res.depth} {res.nodes} nodes")
        board.make_move(mv)
        rec["fen_after"] = board.to_fen()
        history.append(board.zobrist)
        counts[board.zobrist] = counts.get(board.zobrist, 0) + 1

    result = result_text(board, counts) or "*"
    return {
        "start_fen": start,
        "result": result,
        "moves": moves,
        "final_fen": board.to_fen(),
    }
