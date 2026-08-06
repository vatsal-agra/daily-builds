"""Iterative-deepening alpha-beta search with quiescence search, a
Zobrist-keyed transposition table, and move ordering (TT move, MVV-LVA
captures, killer moves, history heuristic).
"""

import time

from .board import WHITE
from .movegen import generate_legal_moves, generate_legal_captures, is_in_check
from .evaluate import evaluate, PIECE_VALUES
from .zobrist import hash_board

MATE_SCORE = 100_000
INF = 10 ** 9
QS_MAX_PLY = 64  # hard cap on quiescence recursion (e.g. a long forced-check
                  # chase) so it can't blow the Python recursion limit

TT_EXACT, TT_LOWER, TT_UPPER = 0, 1, 2


class _TimeUp(Exception):
    pass


class TranspositionTable:
    def __init__(self):
        self.table = {}

    def clear(self):
        self.table.clear()

    def get(self, key):
        return self.table.get(key)

    def store(self, key, depth, score, flag, best_move):
        entry = self.table.get(key)
        if entry is None or depth >= entry[0]:
            self.table[key] = (depth, score, flag, best_move)


class Searcher:
    def __init__(self):
        self.tt = TranspositionTable()
        self.killers = {}    # ply -> [move, move]
        self.history = {}    # (frm, to) -> score
        self.nodes = 0
        self.deadline = None
        self._check_every = 2048

    # ------------------------------------------------------------- ordering
    def _score_move(self, board, move, tt_move, ply):
        if tt_move is not None and move == tt_move:
            return 1_000_000
        if move.captured:
            victim = PIECE_VALUES.get(move.captured.upper(), 0)
            attacker = PIECE_VALUES.get(move.piece.upper(), 0)
            return 100_000 + victim * 10 - attacker
        killers = self.killers.get(ply)
        if killers and move in killers:
            return 90_000
        return self.history.get((move.frm, move.to), 0)

    def _ordered_moves(self, board, moves, tt_move, ply):
        return sorted(moves, key=lambda m: self._score_move(board, m, tt_move, ply), reverse=True)

    # ------------------------------------------------------------ quiescence
    def _quiescence(self, board, alpha, beta, ply):
        self.nodes += 1
        self._check_time()

        if ply >= QS_MAX_PLY:
            score = evaluate(board)
            return score if board.to_move == WHITE else -score

        in_check = is_in_check(board, board.to_move)

        if in_check:
            # can't "stand pat" while in check -- must consider every legal
            # reply, not just captures, or a real threat gets missed
            moves = generate_legal_moves(board)
            if not moves:
                return -MATE_SCORE + ply
        else:
            stand_pat = evaluate(board)
            if board.to_move != WHITE:
                stand_pat = -stand_pat

            if stand_pat >= beta:
                return beta
            if alpha < stand_pat:
                alpha = stand_pat

            moves = generate_legal_captures(board)

        moves = self._ordered_moves(board, moves, None, ply)

        for move in moves:
            u = board.make_move(move)
            try:
                score = -self._quiescence(board, -beta, -alpha, ply + 1)
            finally:
                board.unmake_move(move, u)

            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        return alpha

    # ------------------------------------------------------------- negamax
    def _negamax(self, board, depth, alpha, beta, ply):
        self.nodes += 1
        self._check_time()

        key = hash_board(board)
        alpha_orig = alpha
        tt_entry = self.tt.get(key)
        tt_move = None
        if tt_entry is not None:
            tt_depth, tt_score, tt_flag, tt_move = tt_entry
            if tt_depth >= depth:
                if tt_flag == TT_EXACT:
                    return tt_score, tt_move
                elif tt_flag == TT_LOWER:
                    alpha = max(alpha, tt_score)
                elif tt_flag == TT_UPPER:
                    beta = min(beta, tt_score)
                if alpha >= beta:
                    return tt_score, tt_move

        color = board.to_move
        moves = generate_legal_moves(board)
        if not moves:
            if is_in_check(board, color):
                return -MATE_SCORE + ply, None
            return 0, None

        if depth <= 0:
            return self._quiescence(board, alpha, beta, ply), None

        moves = self._ordered_moves(board, moves, tt_move, ply)
        best_score = -INF
        best_move = None

        for move in moves:
            u = board.make_move(move)
            try:
                score, _ = self._negamax(board, depth - 1, -beta, -alpha, ply + 1)
            finally:
                board.unmake_move(move, u)
            score = -score

            if score > best_score:
                best_score = score
                best_move = move
            if best_score > alpha:
                alpha = best_score
            if alpha >= beta:
                if not move.captured:
                    self.killers.setdefault(ply, [None, None])
                    if move not in self.killers[ply]:
                        self.killers[ply][1] = self.killers[ply][0]
                        self.killers[ply][0] = move
                    self.history[(move.frm, move.to)] = self.history.get((move.frm, move.to), 0) + depth * depth
                break

        flag = TT_EXACT
        if best_score <= alpha_orig:
            flag = TT_UPPER
        elif best_score >= beta:
            flag = TT_LOWER
        self.tt.store(key, depth, best_score, flag, best_move)

        return best_score, best_move

    def _check_time(self):
        if self.deadline is None:
            return
        if self.nodes % self._check_every == 0 and time.time() > self.deadline:
            raise _TimeUp()

    # ------------------------------------------------------------- entrypoint
    def choose_move(self, board, seconds=3.0, max_depth=64):
        """Iterative deepening from depth 1 up to max_depth, bounded by a
        wall-clock time budget. Always returns the best move found by the
        last fully-completed depth (never a partial, unreliable result).

        seconds=None means unlimited (search to max_depth) -- intended for
        callers that explicitly want that (e.g. tests). Any non-positive
        numeric budget is clamped to a small positive floor instead of
        being treated as unlimited, so a caller passing --time 0 gets a
        fast reply rather than an accidental multi-minute hang."""
        self.nodes = 0
        self.killers.clear()
        self.history.clear()
        if seconds is not None and seconds <= 0:
            seconds = 0.05
        self.deadline = time.time() + seconds if seconds is not None else None

        legal = generate_legal_moves(board)
        if not legal:
            return None, 0, 0

        best_move = legal[0]
        best_score = 0
        completed_depth = 0

        for depth in range(1, max_depth + 1):
            try:
                score, move = self._negamax(board, depth, -INF, INF, 0)
            except _TimeUp:
                break
            if move is not None:
                best_move, best_score = move, score
            completed_depth = depth
            if abs(score) >= MATE_SCORE - 1000:
                break
            if self.deadline and time.time() > self.deadline:
                break

        return best_move, best_score, completed_depth
