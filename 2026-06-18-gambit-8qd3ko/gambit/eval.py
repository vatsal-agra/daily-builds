"""Tapered evaluation: material + piece-square tables (middlegame/endgame),
bishop pair, doubled pawns. Score is from the side-to-move's perspective in
centipawns (positive = good for side to move)."""

from .board import (
    WHITE, BLACK, EMPTY, PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING,
    piece_color, piece_type, sq_index, sq_file, sq_rank,
)

# Middlegame material values (centipawns).
MAT_MG = {PAWN: 82, KNIGHT: 337, BISHOP: 365, ROOK: 477, QUEEN: 1025, KING: 0}
MAT_EG = {PAWN: 94, KNIGHT: 281, BISHOP: 297, ROOK: 512, QUEEN: 936, KING: 0}

# Phase weights for tapering (sum over non-king pieces).
PHASE_WEIGHT = {PAWN: 0, KNIGHT: 1, BISHOP: 1, ROOK: 2, QUEEN: 4, KING: 0}
PHASE_MAX = 24  # 4 knights/bishops*1 + 4 rooks*2 + 2 queens*4

# Piece-square tables, indexed for WHITE from white's a1=0 .. h8=63 viewpoint.
# Values are roughly the well-known PeSTO tables (compact public-domain set).
PST_MG = {
    PAWN: [
        0, 0, 0, 0, 0, 0, 0, 0,
        -35, -1, -20, -23, -15, 24, 38, -22,
        -26, -4, -4, -10, 3, 3, 33, -12,
        -27, -2, -5, 12, 17, 6, 10, -25,
        -14, 13, 6, 21, 23, 12, 17, -23,
        -6, 7, 26, 31, 65, 56, 25, -20,
        98, 134, 61, 95, 68, 126, 34, -11,
        0, 0, 0, 0, 0, 0, 0, 0,
    ],
    KNIGHT: [
        -105, -21, -58, -33, -17, -28, -19, -23,
        -29, -53, -12, -3, -1, 18, -14, -19,
        -23, -9, 12, 10, 19, 17, 25, -16,
        -13, 4, 16, 13, 28, 19, 21, -8,
        -9, 17, 19, 53, 37, 69, 18, 22,
        -47, 60, 37, 65, 84, 129, 73, 44,
        -73, -41, 72, 36, 23, 62, 7, -17,
        -167, -89, -34, -49, 61, -97, -15, -107,
    ],
    BISHOP: [
        -33, -3, -14, -21, -13, -12, -39, -21,
        4, 15, 16, 0, 7, 21, 33, 1,
        0, 15, 15, 15, 14, 27, 18, 10,
        -6, 13, 13, 26, 34, 12, 10, 4,
        -4, 5, 19, 50, 37, 37, 7, -2,
        -16, 37, 43, 40, 35, 50, 37, -2,
        -26, 16, -18, -13, 30, 59, 18, -47,
        -29, 4, -82, -37, -25, -42, 7, -8,
    ],
    ROOK: [
        -19, -13, 1, 17, 16, 7, -37, -26,
        -44, -16, -20, -9, -1, 11, -6, -71,
        -45, -25, -16, -17, 3, 0, -5, -33,
        -36, -26, -12, -1, 9, -7, 6, -23,
        -24, -11, 7, 26, 24, 35, -8, -20,
        -5, 19, 26, 36, 17, 45, 61, 16,
        27, 32, 58, 62, 80, 67, 26, 44,
        32, 42, 32, 51, 63, 9, 31, 43,
    ],
    QUEEN: [
        -1, -18, -9, 10, -15, -25, -31, -50,
        -35, -8, 11, 2, 8, 15, -3, 1,
        -14, 2, -11, -2, -5, 2, 14, 5,
        -9, -26, -9, -10, -2, -4, 3, -3,
        -27, -27, -16, -16, -1, 17, -2, 1,
        -13, -17, 7, 8, 29, 56, 47, 57,
        -24, -39, -5, 1, -16, 57, 28, 54,
        -28, 0, 29, 12, 59, 44, 43, 45,
    ],
    KING: [
        -15, 36, 12, -54, 8, -28, 24, 14,
        1, 7, -8, -64, -43, -16, 9, 8,
        -14, -14, -22, -46, -44, -30, -15, -27,
        -49, -1, -27, -39, -46, -44, -33, -51,
        -17, -20, -12, -27, -30, -25, -14, -36,
        -9, 24, 2, -16, -20, 6, 22, -22,
        29, -1, -20, -7, -8, -4, -38, -29,
        -65, 23, 16, -15, -56, -34, 2, 13,
    ],
}
PST_EG = {
    PAWN: [
        0, 0, 0, 0, 0, 0, 0, 0,
        13, 8, 8, 10, 13, 0, 2, -7,
        4, 7, -6, 1, 0, -5, -1, -8,
        13, 9, -3, -7, -7, -8, 3, -1,
        32, 24, 13, 5, -2, 4, 17, 17,
        94, 100, 85, 67, 56, 53, 82, 84,
        178, 173, 158, 134, 147, 132, 165, 187,
        0, 0, 0, 0, 0, 0, 0, 0,
    ],
    KNIGHT: [
        -29, -51, -23, -15, -22, -18, -50, -64,
        -42, -20, -10, -5, -2, -20, -23, -44,
        -23, -3, -1, 15, 10, -3, -20, -22,
        -18, -6, 16, 25, 16, 17, 4, -18,
        -17, 3, 22, 22, 22, 11, 8, -18,
        -24, -20, 10, 9, -1, -9, -19, -41,
        -25, -8, -25, -2, -9, -25, -24, -52,
        -58, -38, -13, -28, -31, -27, -63, -99,
    ],
    BISHOP: [
        -23, -9, -23, -5, -9, -16, -5, -17,
        -14, -18, -7, -1, 4, -9, -15, -27,
        -12, -3, 8, 10, 13, 3, -7, -15,
        -6, 3, 13, 19, 7, 10, -3, -9,
        -3, 9, 12, 9, 14, 10, 3, 2,
        2, -8, 0, -1, -2, 6, 0, 4,
        -8, -4, 7, -12, -3, -13, -4, -14,
        -14, -21, -11, -8, -7, -9, -17, -24,
    ],
    ROOK: [
        -9, 2, 3, -1, -5, -13, 4, -20,
        -6, -6, 0, 2, -9, -9, -11, -3,
        -4, 0, -5, -1, -7, -12, -8, -16,
        3, 5, 8, 4, -5, -6, -8, -11,
        4, 3, 13, 1, 2, 1, -1, 2,
        7, 7, 7, 5, 4, -3, -5, -3,
        11, 13, 13, 11, -3, 3, 8, 3,
        13, 10, 18, 15, 12, 12, 8, 5,
    ],
    QUEEN: [
        -33, -28, -22, -43, -5, -32, -20, -41,
        -22, -23, -30, -16, -16, -23, -36, -32,
        -16, -27, 15, 6, 9, 17, 10, 5,
        -18, 28, 19, 47, 31, 34, 39, 23,
        3, 22, 24, 45, 57, 40, 57, 36,
        -20, 6, 9, 49, 47, 35, 19, 9,
        -17, 20, 32, 41, 58, 25, 30, 0,
        -9, 22, 22, 27, 27, 19, 10, 20,
    ],
    KING: [
        -53, -34, -21, -11, -28, -14, -24, -43,
        -27, -11, 4, 13, 14, 4, -5, -17,
        -19, -3, 11, 21, 23, 16, 7, -9,
        -18, -4, 21, 24, 27, 23, 9, -11,
        -8, 22, 24, 27, 26, 33, 26, 3,
        10, 17, 23, 15, 20, 45, 44, 13,
        -12, 17, 14, 17, 17, 38, 23, 11,
        -74, -35, -18, -18, -11, 15, 4, -17,
    ],
}

MATE = 30000
MATE_THRESHOLD = MATE - 1000

# Precompute combined [piece_type][square_for_white] tables incl. material.
_MG_TABLE = {pt: [PST_MG[pt][i] + MAT_MG[pt] for i in range(64)]
             for pt in PST_MG}
_EG_TABLE = {pt: [PST_EG[pt][i] + MAT_EG[pt] for i in range(64)]
             for pt in PST_EG}

# 0x88 square -> 0..63 index (white view).  Black mirrors the rank.
def _idx64(sq, color):
    f = sq_file(sq)
    r = sq_rank(sq)
    if color == BLACK:
        r = 7 - r
    return r * 8 + f


def evaluate(board):
    """Static evaluation in centipawns from the side-to-move perspective."""
    mg = [0, 0]
    eg = [0, 0]
    phase = 0
    bishops = [0, 0]
    pawn_files = [[0] * 8, [0] * 8]
    sqs = board.squares

    for sq in range(128):
        if sq & 0x88:
            continue
        pc = sqs[sq]
        if pc == EMPTY:
            continue
        c = piece_color(pc)
        pt = piece_type(pc)
        i = _idx64(sq, c)
        mg[c] += _MG_TABLE[pt][i]
        eg[c] += _EG_TABLE[pt][i]
        phase += PHASE_WEIGHT[pt]
        if pt == BISHOP:
            bishops[c] += 1
        elif pt == PAWN:
            pawn_files[c][sq_file(sq)] += 1

    # bishop pair bonus
    for c in (WHITE, BLACK):
        if bishops[c] >= 2:
            mg[c] += 30
            eg[c] += 45
        # doubled pawn penalty
        for cnt in pawn_files[c]:
            if cnt > 1:
                mg[c] -= 12 * (cnt - 1)
                eg[c] -= 24 * (cnt - 1)

    mg_score = mg[WHITE] - mg[BLACK]
    eg_score = eg[WHITE] - eg[BLACK]
    phase = min(phase, PHASE_MAX)
    num = mg_score * phase + eg_score * (PHASE_MAX - phase)
    # Truncate toward zero so the value is exactly anti-symmetric under a
    # color swap (floor division would introduce a 1cp color bias).
    score = abs(num) // PHASE_MAX
    if num < 0:
        score = -score

    return score if board.side == WHITE else -score
