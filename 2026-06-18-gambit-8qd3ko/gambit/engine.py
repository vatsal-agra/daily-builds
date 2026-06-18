"""High-level engine: pick best move, play self-games, detect game end."""

from .board import Board, WHITE, move_to, move_from
from .movegen import gen_legal, to_san
from .search import search, SearchInfo
from .eval import MATE_THRESHOLD


class Engine:
    def __init__(self, depth=4, movetime=None):
        self.depth = depth
        self.movetime = movetime
        self.info = SearchInfo()

    def best_move(self, board, verbose=False):
        # fresh TT per move keeps memory bounded; killers persist in info
        self.info.tt = {}
        self.info.nodes = 0
        return search(board, depth=self.depth, movetime=self.movetime,
                      info=self.info, verbose=verbose)


def game_result(board):
    """Return one of: None (ongoing), '1-0', '0-1', '1/2-1/2', and a reason."""
    legal = gen_legal(board)
    if not legal:
        if board.in_check():
            winner = "0-1" if board.side == WHITE else "1-0"
            return winner, "checkmate"
        return "1/2-1/2", "stalemate"
    if board.halfmove >= 100:
        return "1/2-1/2", "fifty-move rule"
    if board.is_repetition(3):
        return "1/2-1/2", "threefold repetition"
    if _insufficient_material(board):
        return "1/2-1/2", "insufficient material"
    return None, ""


def _insufficient_material(board):
    from .board import piece_type, piece_color, EMPTY, PAWN, KNIGHT, BISHOP, \
        ROOK, QUEEN
    minors = 0
    for sq in range(128):
        if sq & 0x88:
            continue
        pc = board.squares[sq]
        if pc == EMPTY:
            continue
        pt = piece_type(pc)
        if pt in (PAWN, ROOK, QUEEN):
            return False
        if pt in (KNIGHT, BISHOP):
            minors += 1
    return minors <= 1   # K vs K, K+minor vs K


def self_play(depth=4, movetime=None, max_moves=200, verbose=True,
              start_fen=None):
    """Play an engine-vs-engine game. Returns (board, san_moves, result,
    reason, evals) where evals[i] is the search score after move i (white POV
    in centipawns / mate scores)."""
    board = Board.from_fen(start_fen) if start_fen else Board.startpos()
    engine = Engine(depth=depth, movetime=movetime)
    san_moves = []
    evals = []
    fens = [board.to_fen()]
    result, reason = game_result(board)
    while result is None and len(san_moves) < max_moves:
        res = engine.best_move(board)
        if res.move == 0:
            break
        san = to_san(board, res.move)
        # convert score to white POV
        wp = res.score if board.side == WHITE else -res.score
        board.make(res.move)
        san_moves.append(san)
        evals.append(wp)
        fens.append(board.to_fen())
        if verbose:
            num = (len(san_moves) + 1) // 2
            prefix = f"{num}." if len(san_moves) % 2 == 1 else f"{num}..."
            print(f"  {prefix:5} {san:8} (eval {wp:+d}, d{res.depth}, "
                  f"{res.nodes} nodes)")
        result, reason = game_result(board)

    if result is None:
        result, reason = "1/2-1/2", "move limit"
    return board, san_moves, result, reason, evals, fens


def to_pgn(san_moves, result="*", headers=None):
    """Build a valid PGN string from a list of SAN moves."""
    hdr = {
        "Event": "Gambit self-play",
        "Site": "local",
        "Date": "????.??.??",
        "Round": "1",
        "White": "Gambit",
        "Black": "Gambit",
        "Result": result,
    }
    if headers:
        hdr.update(headers)
    lines = [f'[{k} "{v}"]' for k, v in hdr.items()]
    lines.append("")
    body = []
    for i, san in enumerate(san_moves):
        if i % 2 == 0:
            body.append(f"{i // 2 + 1}. {san}")
        else:
            body.append(san)
    body.append(result)
    # wrap at ~80 cols
    text = " ".join(body)
    wrapped = []
    line = ""
    for tok in text.split(" "):
        if len(line) + len(tok) + 1 > 80:
            wrapped.append(line)
            line = tok
        else:
            line = f"{line} {tok}".strip()
    if line:
        wrapped.append(line)
    return "\n".join(lines + wrapped) + "\n"
