"""Negamax alpha-beta search with iterative deepening, quiescence search,
move ordering (TT move, MVV-LVA captures, killers) and a Zobrist transposition
table. Returns the best move, score (centipawns, side-to-move relative) and the
principal variation.
"""

from __future__ import annotations

import time

from .board import (
    Board, move_to, move_flag, move_from, F_EP, F_PROMO, move_promo,
    piece_type, PAWN,
)
from .movegen import (
    legal_moves, gen_pseudo, gen_pseudo_captures, in_check, square_attacked,
)
from .eval import evaluate, PIECE_VALUE, MATE, INF

# TT entry flags
TT_EXACT, TT_LOWER, TT_UPPER = 0, 1, 2
MATE_THRESHOLD = MATE - 1000


class TimeUp(Exception):
    pass


class SearchResult:
    __slots__ = ("best_move", "score", "depth", "nodes", "pv", "time")

    def __init__(self, best_move, score, depth, nodes, pv, t):
        self.best_move = best_move
        self.score = score
        self.depth = depth
        self.nodes = nodes
        self.pv = pv
        self.time = t


class Search:
    def __init__(self, use_tt: bool = True):
        self.tt = {}
        self.use_tt = use_tt
        self.nodes = 0
        self.killers = []
        self.start = 0.0
        self.limit = None
        self.deadline = None
        self.rep = []
        self.stop = False

    # ---- public API ----
    def search(self, board: Board, max_depth: int = 64,
               movetime: float | None = None, history: list | None = None) -> SearchResult:
        self.nodes = 0
        self.killers = [[0, 0] for _ in range(max_depth + 64)]
        self.start = time.time()
        self.limit = movetime
        self.deadline = (self.start + movetime) if movetime else None
        self.rep = list(history) if history else []
        self.stop = False

        best = SearchResult(0, 0, 0, 0, [], 0.0)
        root_moves = legal_moves(board)
        if not root_moves:
            return best
        best.best_move = root_moves[0]

        for depth in range(1, max_depth + 1):
            try:
                score = self._negamax(board, depth, -INF, INF, 0)
            except TimeUp:
                break
            pv = self._extract_pv(board, depth)
            best = SearchResult(
                pv[0] if pv else best.best_move, score, depth,
                self.nodes, pv, time.time() - self.start,
            )
            # stop early on a proven mate
            if abs(score) >= MATE_THRESHOLD:
                break
            if self.deadline and time.time() >= self.deadline:
                break
        return best

    # ---- core ----
    def _checktime(self):
        if self.deadline and (self.nodes & 2047) == 0:
            if time.time() >= self.deadline:
                raise TimeUp()

    def _negamax(self, board: Board, depth: int, alpha: int, beta: int, ply: int) -> int:
        self.nodes += 1
        self._checktime()

        if ply > 0 and board.zobrist in self.rep:
            return 0  # repetition draw
        if board.halfmove >= 100:
            return 0  # fifty-move draw

        alpha_orig = alpha
        key = board.zobrist
        tt_move = 0
        if self.use_tt:
            entry = self.tt.get(key)
            if entry is not None:
                e_depth, e_score, e_flag, e_move = entry
                tt_move = e_move
                if e_depth >= depth:
                    val = self._from_tt_score(e_score, ply)
                    if e_flag == TT_EXACT:
                        return val
                    elif e_flag == TT_LOWER and val > alpha:
                        alpha = val
                    elif e_flag == TT_UPPER and val < beta:
                        beta = val
                    if alpha >= beta:
                        return val

        if depth <= 0:
            return self._quiesce(board, alpha, beta, ply)

        mover = board.side
        moves = gen_pseudo(board)
        self._order(board, moves, tt_move, ply)

        best = -INF
        best_move = 0
        legal_found = 0
        self.rep.append(key)
        try:
            for mv in moves:
                board.make_move(mv)
                if square_attacked(board, board.king_sq[mover], mover ^ 1):
                    board.unmake_move()
                    continue  # illegal: leaves own king in check
                legal_found += 1
                score = -self._negamax(board, depth - 1, -beta, -alpha, ply + 1)
                board.unmake_move()
                if score > best:
                    best = score
                    best_move = mv
                    if score > alpha:
                        alpha = score
                if alpha >= beta:
                    if not self._is_capture(board, mv):
                        self._add_killer(mv, ply)
                    break
        finally:
            self.rep.pop()

        if legal_found == 0:
            if in_check(board, board.side):
                return -MATE + ply  # checkmated
            return 0  # stalemate

        if self.use_tt:
            if best <= alpha_orig:
                flag = TT_UPPER
            elif best >= beta:
                flag = TT_LOWER
            else:
                flag = TT_EXACT
            self.tt[key] = (depth, self._to_tt_score(best, ply), flag, best_move)
        return best

    def _quiesce(self, board: Board, alpha: int, beta: int, ply: int) -> int:
        self.nodes += 1
        self._checktime()
        if ply > 96:
            return evaluate(board)

        mover = board.side
        checked = in_check(board, mover)
        if checked:
            moves = gen_pseudo(board)  # all evasions (filtered for legality below)
        else:
            stand = evaluate(board)
            if stand >= beta:
                return beta
            if stand > alpha:
                alpha = stand
            moves = gen_pseudo_captures(board)
            if not moves:
                return alpha

        self._order(board, moves, 0, ply)
        legal_found = 0
        for mv in moves:
            board.make_move(mv)
            if square_attacked(board, board.king_sq[mover], mover ^ 1):
                board.unmake_move()
                continue
            legal_found += 1
            score = -self._quiesce(board, -beta, -alpha, ply + 1)
            board.unmake_move()
            if score >= beta:
                return beta
            if score > alpha:
                alpha = score
        if checked and legal_found == 0:
            return -MATE + ply  # checkmate
        return alpha

    # ---- helpers ----
    def _is_capture(self, board, mv):
        return board.squares[move_to(mv)] != 0 or move_flag(mv) == F_EP

    def _order(self, board, moves, tt_move, ply):
        k0, k1 = self.killers[ply] if ply < len(self.killers) else (0, 0)

        def score(mv):
            if mv == tt_move:
                return 1_000_000
            to = move_to(mv)
            victim = board.squares[to]
            if victim or move_flag(mv) == F_EP:
                vt = PAWN if move_flag(mv) == F_EP else piece_type(victim)
                attacker = piece_type(board.squares[move_from(mv)])
                return 100_000 + PIECE_VALUE[vt] * 10 - attacker
            if move_flag(mv) == F_PROMO:
                return 90_000 + PIECE_VALUE[move_promo(mv)]
            if mv == k0:
                return 80_000
            if mv == k1:
                return 79_000
            return 0

        moves.sort(key=score, reverse=True)

    def _add_killer(self, mv, ply):
        if ply >= len(self.killers):
            return
        k = self.killers[ply]
        if k[0] != mv:
            k[1] = k[0]
            k[0] = mv

    def _to_tt_score(self, score, ply):
        if score >= MATE_THRESHOLD:
            return score + ply
        if score <= -MATE_THRESHOLD:
            return score - ply
        return score

    def _from_tt_score(self, score, ply):
        if score >= MATE_THRESHOLD:
            return score - ply
        if score <= -MATE_THRESHOLD:
            return score + ply
        return score

    def _extract_pv(self, board: Board, max_len: int) -> list:
        pv = []
        seen = set()
        for _ in range(max_len + 8):
            entry = self.tt.get(board.zobrist)
            if entry is None:
                break
            mv = entry[3]
            if not mv:
                break
            legal = legal_moves(board)
            if mv not in legal:
                break
            if board.zobrist in seen:
                break
            seen.add(board.zobrist)
            pv.append(mv)
            board.make_move(mv)
        for _ in range(len(pv)):
            board.unmake_move()
        return pv
