"""Position evaluation: tapered material + piece-square tables plus pawn-structure,
bishop-pair and king-shelter terms. Scores are in centipawns from the perspective
of the side to move (positive = side to move is better).

The static evaluation is colour-symmetric: eval(pos) == -eval(mirror(pos)).
"""

from __future__ import annotations

from .board import (
    Board, WHITE, BLACK, EMPTY, PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING,
    make_piece, piece_type, piece_color, on_board, sq_index, sq_rank, sq_file,
)

PIECE_VALUE = {PAWN: 100, KNIGHT: 320, BISHOP: 330, ROOK: 500, QUEEN: 900, KING: 0}

# Piece-square tables in rank-8-first layout (Michniewski "Simplified Evaluation").
_PAWN = [
     0,  0,  0,  0,  0,  0,  0,  0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
     5,  5, 10, 25, 25, 10,  5,  5,
     0,  0,  0, 20, 20,  0,  0,  0,
     5, -5,-10,  0,  0,-10, -5,  5,
     5, 10, 10,-20,-20, 10, 10,  5,
     0,  0,  0,  0,  0,  0,  0,  0,
]
_KNIGHT = [
    -50,-40,-30,-30,-30,-30,-40,-50,
    -40,-20,  0,  0,  0,  0,-20,-40,
    -30,  0, 10, 15, 15, 10,  0,-30,
    -30,  5, 15, 20, 20, 15,  5,-30,
    -30,  0, 15, 20, 20, 15,  0,-30,
    -30,  5, 10, 15, 15, 10,  5,-30,
    -40,-20,  0,  5,  5,  0,-20,-40,
    -50,-40,-30,-30,-30,-30,-40,-50,
]
_BISHOP = [
    -20,-10,-10,-10,-10,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0,  5, 10, 10,  5,  0,-10,
    -10,  5,  5, 10, 10,  5,  5,-10,
    -10,  0, 10, 10, 10, 10,  0,-10,
    -10, 10, 10, 10, 10, 10, 10,-10,
    -10,  5,  0,  0,  0,  0,  5,-10,
    -20,-10,-10,-10,-10,-10,-10,-20,
]
_ROOK = [
     0,  0,  0,  0,  0,  0,  0,  0,
     5, 10, 10, 10, 10, 10, 10,  5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
    -5,  0,  0,  0,  0,  0,  0, -5,
     0,  0,  0,  5,  5,  0,  0,  0,
]
_QUEEN = [
    -20,-10,-10, -5, -5,-10,-10,-20,
    -10,  0,  0,  0,  0,  0,  0,-10,
    -10,  0,  5,  5,  5,  5,  0,-10,
     -5,  0,  5,  5,  5,  5,  0, -5,
      0,  0,  5,  5,  5,  5,  0, -5,
    -10,  5,  5,  5,  5,  5,  0,-10,
    -10,  0,  5,  0,  0,  0,  0,-10,
    -20,-10,-10, -5, -5,-10,-10,-20,
]
_KING_MG = [
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -30,-40,-40,-50,-50,-40,-40,-30,
    -20,-30,-30,-40,-40,-30,-30,-20,
    -10,-20,-20,-20,-20,-20,-20,-10,
     20, 20,  0,  0,  0,  0, 20, 20,
     20, 30, 10,  0,  0, 10, 30, 20,
]
_KING_EG = [
    -50,-40,-30,-20,-20,-30,-40,-50,
    -30,-20,-10,  0,  0,-10,-20,-30,
    -30,-10, 20, 30, 30, 20,-10,-30,
    -30,-10, 30, 40, 40, 30,-10,-30,
    -30,-10, 30, 40, 40, 30,-10,-30,
    -30,-10, 20, 30, 30, 20,-10,-30,
    -30,-30,  0,  0,  0,  0,-30,-30,
    -50,-30,-30,-30,-30,-30,-30,-50,
]

PST = {PAWN: _PAWN, KNIGHT: _KNIGHT, BISHOP: _BISHOP, ROOK: _ROOK, QUEEN: _QUEEN}

# Phase weights for tapering (sum over the board = 24 at full material).
PHASE_WEIGHT = {PAWN: 0, KNIGHT: 1, BISHOP: 1, ROOK: 2, QUEEN: 4, KING: 0}
TOTAL_PHASE = 24

MATE = 30000
INF = 1 << 20


def _table_index(sq: int, color: int) -> int:
    """Map a 0x88 square to a rank-8-first table index for the given colour."""
    r = sq_rank(sq)
    f = sq_file(sq)
    if color == WHITE:
        return (7 - r) * 8 + f
    else:
        return r * 8 + f


def evaluate(board: Board) -> int:
    sqs = board.squares
    score = 0  # white-positive accumulator
    phase = 0

    # pawn file counts per colour for structure terms
    pawn_files = [[0] * 8, [0] * 8]
    pawn_squares = [[], []]
    king_pos = [None, None]
    bishops = [0, 0]

    for sq in range(128):
        if sq & 0x88:
            continue
        p = sqs[sq]
        if not p:
            continue
        pt = piece_type(p)
        color = piece_color(p)
        sign = 1 if color == WHITE else -1
        phase += PHASE_WEIGHT[pt]

        val = PIECE_VALUE[pt]
        if pt == KING:
            king_pos[color] = sq
        else:
            val += PST[pt][_table_index(sq, color)]
        score += sign * val

        if pt == PAWN:
            pawn_files[color][sq_file(sq)] += 1
            pawn_squares[color].append(sq)
        elif pt == BISHOP:
            bishops[color] += 1

    # King PST, tapered between middlegame and endgame.
    phase = min(phase, TOTAL_PHASE)
    mg_w = phase
    eg_w = TOTAL_PHASE - phase
    for color in (WHITE, BLACK):
        sign = 1 if color == WHITE else -1
        ks = king_pos[color]
        if ks is None:
            continue
        idx = _table_index(ks, color)
        king_val = (_KING_MG[idx] * mg_w + _KING_EG[idx] * eg_w) // TOTAL_PHASE
        score += sign * king_val

    # Bishop pair
    if bishops[WHITE] >= 2:
        score += 30
    if bishops[BLACK] >= 2:
        score -= 30

    # Pawn structure: doubled, isolated, passed
    for color in (WHITE, BLACK):
        sign = 1 if color == WHITE else -1
        files = pawn_files[color]
        opp_files = pawn_files[color ^ 1]
        for f in range(8):
            if files[f] > 1:
                score -= sign * 12 * (files[f] - 1)  # doubled
            if files[f] > 0:
                left = files[f - 1] if f > 0 else 0
                right = files[f + 1] if f < 7 else 0
                if left == 0 and right == 0:
                    score -= sign * 16 * files[f]  # isolated
        # passed pawns
        for sq in pawn_squares[color]:
            f = sq_file(sq)
            r = sq_rank(sq)
            blocked = False
            for df in (-1, 0, 1):
                nf = f + df
                if 0 <= nf <= 7 and opp_files[nf]:
                    # check if an enemy pawn is actually ahead on that file
                    for osq in pawn_squares[color ^ 1]:
                        if sq_file(osq) == nf:
                            orank = sq_rank(osq)
                            ahead = orank > r if color == WHITE else orank < r
                            if ahead:
                                blocked = True
                                break
                if blocked:
                    break
            if not blocked:
                adv = r if color == WHITE else 7 - r
                score += sign * (10 + adv * adv * 3)

    # King pawn shelter (middlegame only): reward friendly pawns in front of king.
    if mg_w > 8:
        for color in (WHITE, BLACK):
            sign = 1 if color == WHITE else -1
            ks = king_pos[color]
            if ks is None:
                continue
            shield = 0
            fwd = 16 if color == WHITE else -16
            kf = sq_file(ks)
            for df in (-1, 0, 1):
                nf = kf + df
                if 0 <= nf <= 7:
                    s1 = ks + fwd + (df)
                    if on_board(s1) and sqs[s1] == make_piece(PAWN, color):
                        shield += 8
            score += sign * shield * mg_w // TOTAL_PHASE

    return score if board.side == WHITE else -score
