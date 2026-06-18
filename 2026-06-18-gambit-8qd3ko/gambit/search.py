"""Principal Variation Search (PVS) with iterative deepening, a check-aware
quiescence search, a Zobrist transposition table, null-move pruning, and move
ordering (TT move, MVV-LVA, killers).

The search is PVS so that TT *bound* cutoffs are only ever taken at non-PV
(zero-window) nodes; the principal variation is always searched with a full
window, which keeps the root score exact and independent of the TT.
"""

import time

from .board import (
    EMPTY, PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING,
    piece_type, move_from, move_to, move_promo, move_flag, F_EP,
)
from .movegen import gen_legal, gen_captures
from .eval import evaluate, MATE, MATE_THRESHOLD

# MVV-LVA victim/attacker weights for capture ordering.
_VICTIM = {PAWN: 1, KNIGHT: 3, BISHOP: 3, ROOK: 5, QUEEN: 9, KING: 20, EMPTY: 0}


class SearchInfo:
    def __init__(self):
        self.nodes = 0
        self.tt = {}            # zobrist -> (depth, score, flag, move)
        self.killers = [[0, 0] for _ in range(256)]
        self.stop = False
        self.deadline = None
        self.use_tt = True
        self.use_null = True


class SearchResult:
    def __init__(self, move, score, depth, pv, nodes, elapsed):
        self.move = move
        self.score = score
        self.depth = depth
        self.pv = pv
        self.nodes = nodes
        self.elapsed = elapsed


def _mvv_lva(board, m):
    if move_flag(m) == F_EP:
        vt = PAWN
    else:
        victim = board.squares[move_to(m)]
        vt = piece_type(victim) if victim else EMPTY
    attacker = piece_type(board.squares[move_from(m)])
    return _VICTIM[vt] * 10 - attacker


def _order_moves(board, moves, tt_move, info, ply):
    k1, k2 = info.killers[ply]
    scored = []
    sqs = board.squares
    for m in moves:
        if m == tt_move:
            s = 1_000_000
        elif sqs[move_to(m)] != EMPTY or move_flag(m) == F_EP:
            s = 100_000 + _mvv_lva(board, m)
        elif move_promo(m):
            s = 90_000 + move_promo(m)
        elif m == k1:
            s = 80_000
        elif m == k2:
            s = 79_000
        else:
            s = 0
        scored.append((s, m))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [m for _, m in scored]


def _quiesce(board, alpha, beta, info, ply):
    info.nodes += 1
    color = board.side

    # If in check, this is not a "quiet" position: search all evasions so we
    # never stand pat into a checkmate.
    if board.in_check():
        moves = gen_legal(board)
        if not moves:
            return -MATE + ply
        moves = sorted(moves, key=lambda m: _mvv_lva(board, m), reverse=True)
        best = -MATE - 1
        for m in moves:
            board.make(m)
            score = -_quiesce(board, -beta, -alpha, info, ply + 1)
            board.unmake()
            if score > best:
                best = score
            if best > alpha:
                alpha = best
            if alpha >= beta:
                break
        return best

    stand = evaluate(board)
    if stand >= beta:
        return beta
    if stand > alpha:
        alpha = stand

    moves = gen_captures(board)
    moves.sort(key=lambda m: _mvv_lva(board, m), reverse=True)
    for m in moves:
        board.make(m)
        if board.is_attacked(board.king_sq[color], color ^ 1):
            board.unmake()
            continue
        score = -_quiesce(board, -beta, -alpha, info, ply + 1)
        board.unmake()
        if score >= beta:
            return beta
        if score > alpha:
            alpha = score
    return alpha


def _has_non_pawn_material(board):
    color = board.side
    for sq in range(128):
        if sq & 0x88:
            continue
        pc = board.squares[sq]
        if pc and (pc >> 3) & 1 == color:
            pt = piece_type(pc)
            if pt not in (PAWN, KING):
                return True
    return False


def _negamax(board, depth, alpha, beta, info, ply, is_pv):
    if info.stop:
        return 0
    if info.deadline and (info.nodes & 2047) == 0 and \
            time.time() > info.deadline:
        info.stop = True
        return 0

    if ply > 0 and (board.is_repetition(2) or board.halfmove >= 100):
        return 0

    tt_move = 0
    z = board.zobrist
    if info.use_tt:
        entry = info.tt.get(z)
        if entry is not None:
            # The TT is used for MOVE ORDERING ONLY: we seed the search with the
            # best move found last time we visited this position. Reordering
            # moves cannot change the value alpha-beta returns (only how fast it
            # gets there), so this keeps the search result provably identical to
            # a TT-less search while still cutting node counts substantially.
            tt_move = entry[1]

    if depth <= 0:
        return _quiesce(board, alpha, beta, info, ply)

    info.nodes += 1
    in_check = board.in_check()

    # Null-move pruning: if not in check, not a PV node, and we have non-pawn
    # material (zugzwang guard), try giving the opponent a free move.
    if (info.use_null and not is_pv and not in_check and depth >= 3
            and beta < MATE_THRESHOLD and _has_non_pawn_material(board)):
        R = 2 + (depth > 6)
        board.make_null()
        score = -_negamax(board, depth - 1 - R, -beta, -beta + 1, info,
                          ply + 1, False)
        board.unmake_null()
        if info.stop:
            return 0
        if score >= beta:
            return beta

    moves = gen_legal(board)
    if not moves:
        if in_check:
            return -MATE + ply        # checkmated
        return 0                       # stalemate

    moves = _order_moves(board, moves, tt_move, info, ply)
    best_move = moves[0]
    best = -MATE - 1
    first = True
    for m in moves:
        board.make(m)
        if first:
            score = -_negamax(board, depth - 1, -beta, -alpha, info,
                              ply + 1, is_pv)
        else:
            # zero-window scout search
            score = -_negamax(board, depth - 1, -alpha - 1, -alpha, info,
                              ply + 1, False)
            if alpha < score < beta:
                # fail-high: re-search with full window as a PV node
                score = -_negamax(board, depth - 1, -beta, -alpha, info,
                                  ply + 1, is_pv)
        board.unmake()
        if info.stop:
            return 0
        if score > best:
            best = score
            best_move = m
        if score > alpha:
            alpha = score
        if alpha >= beta:
            if board.squares[move_to(m)] == EMPTY and move_flag(m) != F_EP:
                kl = info.killers[ply]
                if kl[0] != m:
                    kl[1] = kl[0]
                    kl[0] = m
            break
        first = False

    if info.use_tt and best_move:
        # depth-preferred replacement; store only the best move (for ordering)
        prev = info.tt.get(z)
        if prev is None or prev[0] <= depth:
            info.tt[z] = (depth, best_move)

    return best


def _extract_pv(board, info, max_len):
    pv = []
    made = 0
    seen = set()
    while len(pv) < max_len:
        entry = info.tt.get(board.zobrist)
        if not entry or entry[1] == 0:
            break
        m = entry[1]
        if m not in gen_legal(board) or board.zobrist in seen:
            break
        seen.add(board.zobrist)
        pv.append(m)
        board.make(m)
        made += 1
    for _ in range(made):
        board.unmake()
    return pv


def search(board, depth=4, movetime=None, info=None, verbose=False):
    """Iterative-deepening PVS search. Returns a SearchResult."""
    if info is None:
        info = SearchInfo()
    start = time.time()
    if movetime is not None:
        info.deadline = start + movetime
    best_move = 0
    best_score = 0
    pv = []
    completed = 0

    for d in range(1, depth + 1):
        info.stop = False
        score = _negamax(board, d, -MATE - 1, MATE + 1, info, 0, True)
        if info.stop:
            break
        completed = d
        best_score = score
        pv = _extract_pv(board, info, d)
        if pv:
            best_move = pv[0]
        else:
            entry = info.tt.get(board.zobrist)
            if entry:
                best_move = entry[1]
        if verbose:
            elapsed = time.time() - start
            print(f"  depth {d:2}  score {_score_str(score):>8}  "
                  f"nodes {info.nodes:>9}  time {elapsed:5.2f}s  "
                  f"pv {_pv_san(board, pv)}")
        if abs(score) > MATE_THRESHOLD:
            break

    if best_move == 0:
        legal = gen_legal(board)
        if legal:
            best_move = legal[0]
    return SearchResult(best_move, best_score, completed, pv, info.nodes,
                        time.time() - start)


def _score_str(score):
    if score > MATE_THRESHOLD:
        return f"#{(MATE - score + 1) // 2}"
    if score < -MATE_THRESHOLD:
        return f"#-{(MATE + score + 1) // 2}"
    return str(score)


def _pv_san(board, pv):
    from .movegen import to_san
    out = []
    n = 0
    for m in pv:
        out.append(to_san(board, m))
        board.make(m)
        n += 1
    for _ in range(n):
        board.unmake()
    return " ".join(out)
