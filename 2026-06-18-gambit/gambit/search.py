"""Negamax alpha-beta search with iterative deepening, quiescence, a Zobrist
transposition table, and move ordering (TT move, MVV-LVA, killers)."""

import time

from .board import (
    EMPTY, PAWN, KING, piece_type, move_from, move_to, move_promo, move_flag,
    F_EP,
)
from .movegen import gen_legal, gen_captures
from .eval import evaluate, MATE, MATE_THRESHOLD

# TT bound flags
TT_EXACT, TT_LOWER, TT_UPPER = 0, 1, 2

# MVV-LVA: victim value * 10 - attacker value, for capture ordering.
_VICTIM = {PAWN: 1, 2: 3, 3: 3, 4: 5, 5: 9, KING: 20, EMPTY: 0}


class SearchInfo:
    def __init__(self):
        self.nodes = 0
        self.tt = {}            # zobrist -> (depth, score, flag, move)
        self.killers = [[0, 0] for _ in range(128)]
        self.stop = False
        self.deadline = None
        self.use_tt = True


class SearchResult:
    def __init__(self, move, score, depth, pv, nodes, elapsed):
        self.move = move
        self.score = score
        self.depth = depth
        self.pv = pv
        self.nodes = nodes
        self.elapsed = elapsed


def _mvv_lva(board, m):
    victim = board.squares[move_to(m)]
    if move_flag(m) == F_EP:
        vt = PAWN
    else:
        vt = piece_type(victim) if victim else EMPTY
    attacker = piece_type(board.squares[move_from(m)])
    return _VICTIM.get(vt, 0) * 10 - attacker


def _order_moves(board, moves, tt_move, info, ply):
    k1, k2 = info.killers[ply]
    scored = []
    for m in moves:
        if m == tt_move:
            s = 1_000_000
        elif board.squares[move_to(m)] != EMPTY or move_flag(m) == F_EP:
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


def _quiesce(board, alpha, beta, info):
    info.nodes += 1
    stand = evaluate(board)
    if stand >= beta:
        return beta
    if stand > alpha:
        alpha = stand
    moves = gen_captures(board)
    # order captures by MVV-LVA
    moves.sort(key=lambda m: _mvv_lva(board, m), reverse=True)
    color = board.side
    for m in moves:
        board.make(m)
        if board.is_attacked(board.king_sq[color], color ^ 1):
            board.unmake()
            continue
        score = -_quiesce(board, -beta, -alpha, info)
        board.unmake()
        if score >= beta:
            return beta
        if score > alpha:
            alpha = score
    return alpha


def _negamax(board, depth, alpha, beta, info, ply):
    if info.stop:
        return 0
    if info.deadline and (info.nodes & 2047) == 0 and time.time() > info.deadline:
        info.stop = True
        return 0

    # draw by repetition or fifty-move (not at root)
    if ply > 0 and (board.is_repetition(2) or board.halfmove >= 100):
        return 0

    alpha_orig = alpha
    tt_move = 0
    z = board.zobrist
    if info.use_tt:
        entry = info.tt.get(z)
        if entry is not None:
            e_depth, e_score, e_flag, e_move = entry
            tt_move = e_move
            if e_depth >= depth and ply > 0:
                if e_flag == TT_EXACT:
                    return e_score
                if e_flag == TT_LOWER and e_score > alpha:
                    alpha = e_score
                elif e_flag == TT_UPPER and e_score < beta:
                    beta = e_score
                if alpha >= beta:
                    return e_score

    if depth <= 0:
        return _quiesce(board, alpha, beta, info)

    info.nodes += 1
    moves = gen_legal(board)
    if not moves:
        if board.in_check():
            return -MATE + ply        # checkmated
        return 0                       # stalemate

    moves = _order_moves(board, moves, tt_move, info, ply)
    best_move = 0
    best = -MATE - 1
    for m in moves:
        board.make(m)
        score = -_negamax(board, depth - 1, -beta, -alpha, info, ply + 1)
        board.unmake()
        if info.stop:
            return 0
        if score > best:
            best = score
            best_move = m
        if score > alpha:
            alpha = score
        if alpha >= beta:
            # killer move (quiet only)
            if board.squares[move_to(m)] == EMPTY and move_flag(m) != F_EP:
                kl = info.killers[ply]
                if kl[0] != m:
                    kl[1] = kl[0]
                    kl[0] = m
            break

    if info.use_tt:
        if best <= alpha_orig:
            flag = TT_UPPER
        elif best >= beta:
            flag = TT_LOWER
        else:
            flag = TT_EXACT
        info.tt[z] = (depth, best, flag, best_move)

    return best


def _extract_pv(board, info, max_len):
    pv = []
    made = 0
    seen = set()
    while len(pv) < max_len:
        entry = info.tt.get(board.zobrist)
        if not entry or entry[3] == 0:
            break
        m = entry[3]
        legal = gen_legal(board)
        if m not in legal or board.zobrist in seen:
            break
        seen.add(board.zobrist)
        pv.append(m)
        board.make(m)
        made += 1
    for _ in range(made):
        board.unmake()
    return pv


def search(board, depth=4, movetime=None, info=None, verbose=False):
    """Iterative-deepening search. Returns a SearchResult."""
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
        score = _negamax(board, d, -MATE - 1, MATE + 1, info, 0)
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
                best_move = entry[3]
        if verbose:
            from .movegen import to_san
            elapsed = time.time() - start
            print(f"  depth {d:2}  score {score:>6}  nodes {info.nodes:>9}  "
                  f"time {elapsed:5.2f}s  pv {_pv_san(board, pv)}")
        # early exit on found forced mate
        if abs(score) > MATE_THRESHOLD:
            break

    if best_move == 0:
        legal = gen_legal(board)
        if legal:
            best_move = legal[0]
    return SearchResult(best_move, best_score, completed, pv, info.nodes,
                        time.time() - start)


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
