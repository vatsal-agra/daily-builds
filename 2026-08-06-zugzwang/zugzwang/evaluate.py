"""Static position evaluation: material, tapered piece-square tables,
mobility, king safety (pawn shield), and pawn structure. Returns a score
in centipawns from White's perspective (positive = good for White); the
search layer negates it for the side to move.
"""

from .board import sq, file_of, rank_of, color_of, WHITE, BLACK

PIECE_VALUES = {"P": 100, "N": 320, "B": 330, "R": 500, "Q": 900, "K": 0}

# Tables below are written in "FEN reading order": row 0 = rank 8 (Black's
# back rank) down to row 7 = rank 1 (White's back rank), each row a8..h8
# style left-to-right. _to_sq_table() remaps them into our a1=0 indexing.

_PAWN_TOP_DOWN = [
    0, 0, 0, 0, 0, 0, 0, 0,
    50, 50, 50, 50, 50, 50, 50, 50,
    10, 10, 20, 30, 30, 20, 10, 10,
    5, 5, 10, 25, 25, 10, 5, 5,
    0, 0, 0, 20, 20, 0, 0, 0,
    5, -5, -10, 0, 0, -10, -5, 5,
    5, 10, 10, -20, -20, 10, 10, 5,
    0, 0, 0, 0, 0, 0, 0, 0,
]
_KNIGHT_TOP_DOWN = [
    -50, -40, -30, -30, -30, -30, -40, -50,
    -40, -20, 0, 0, 0, 0, -20, -40,
    -30, 0, 10, 15, 15, 10, 0, -30,
    -30, 5, 15, 20, 20, 15, 5, -30,
    -30, 0, 15, 20, 20, 15, 0, -30,
    -30, 5, 10, 15, 15, 10, 5, -30,
    -40, -20, 0, 5, 5, 0, -20, -40,
    -50, -40, -30, -30, -30, -30, -40, -50,
]
_BISHOP_TOP_DOWN = [
    -20, -10, -10, -10, -10, -10, -10, -20,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -10, 0, 5, 10, 10, 5, 0, -10,
    -10, 5, 5, 10, 10, 5, 5, -10,
    -10, 0, 10, 10, 10, 10, 0, -10,
    -10, 10, 10, 10, 10, 10, 10, -10,
    -10, 5, 0, 0, 0, 0, 5, -10,
    -20, -10, -10, -10, -10, -10, -10, -20,
]
_ROOK_TOP_DOWN = [
    0, 0, 0, 0, 0, 0, 0, 0,
    5, 10, 10, 10, 10, 10, 10, 5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    -5, 0, 0, 0, 0, 0, 0, -5,
    0, 0, 0, 5, 5, 0, 0, 0,
]
_QUEEN_TOP_DOWN = [
    -20, -10, -10, -5, -5, -10, -10, -20,
    -10, 0, 0, 0, 0, 0, 0, -10,
    -10, 0, 5, 5, 5, 5, 0, -10,
    -5, 0, 5, 5, 5, 5, 0, -5,
    0, 0, 5, 5, 5, 5, 0, -5,
    -10, 5, 5, 5, 5, 5, 0, -10,
    -10, 0, 5, 0, 0, 0, 0, -10,
    -20, -10, -10, -5, -5, -10, -10, -20,
]
_KING_MG_TOP_DOWN = [
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -30, -40, -40, -50, -50, -40, -40, -30,
    -20, -30, -30, -40, -40, -30, -30, -20,
    -10, -20, -20, -20, -20, -20, -20, -10,
    20, 20, 0, 0, 0, 0, 20, 20,
    20, 30, 10, 0, 0, 10, 30, 20,
]
_KING_EG_TOP_DOWN = [
    -50, -40, -30, -20, -20, -30, -40, -50,
    -40, -20, -10, 0, 0, -10, -20, -40,
    -30, -10, 20, 30, 30, 20, -10, -30,
    -20, 0, 30, 40, 40, 30, 0, -20,
    -20, 0, 30, 40, 40, 30, 0, -20,
    -30, -10, 20, 30, 30, 20, -10, -30,
    -40, -20, -10, 0, 0, -10, -20, -40,
    -50, -40, -30, -20, -20, -30, -40, -50,
]


def _to_sq_table(top_down):
    table = [0] * 64
    for row in range(8):
        for col in range(8):
            table[sq(col, 7 - row)] = top_down[row * 8 + col]
    return table


PST = {
    "P": _to_sq_table(_PAWN_TOP_DOWN),
    "N": _to_sq_table(_KNIGHT_TOP_DOWN),
    "B": _to_sq_table(_BISHOP_TOP_DOWN),
    "R": _to_sq_table(_ROOK_TOP_DOWN),
    "Q": _to_sq_table(_QUEEN_TOP_DOWN),
}
KING_PST_MG = _to_sq_table(_KING_MG_TOP_DOWN)
KING_PST_EG = _to_sq_table(_KING_EG_TOP_DOWN)


def _mirror(square):
    return sq(file_of(square), 7 - rank_of(square))


PHASE_WEIGHT = {"N": 1, "B": 1, "R": 2, "Q": 4}
MAX_PHASE = 24  # 2N+2B+2R+Q per side = (2+2+4+4) = 12, x2 sides = 24


def game_phase(board):
    """0 == pure endgame material, MAX_PHASE == full midgame material."""
    phase = 0
    for piece in board.squares:
        if piece == "." or piece.upper() not in PHASE_WEIGHT:
            continue
        phase += PHASE_WEIGHT[piece.upper()]
    return min(phase, MAX_PHASE)


def _mobility_count(board, color):
    # cheap pseudo-legal move count as a mobility proxy (full legality
    # filtering here would be too slow to call at every search node)
    from .movegen import generate_pseudo_legal_moves
    if board.to_move == color:
        return len(generate_pseudo_legal_moves(board))
    saved = board.to_move
    board.to_move = color
    try:
        return len(generate_pseudo_legal_moves(board))
    finally:
        board.to_move = saved


def _pawn_files(board, pawn_char):
    """ranks[file] = sorted list of ranks holding a pawn of `pawn_char`."""
    files = [[] for _ in range(8)]
    for square, piece in enumerate(board.squares):
        if piece == pawn_char:
            files[file_of(square)].append(rank_of(square))
    return files


def _pawn_structure(board, color):
    pawn_char = "P" if color == WHITE else "p"
    enemy_pawn_char = "p" if color == WHITE else "P"
    own_files = _pawn_files(board, pawn_char)
    enemy_files = _pawn_files(board, enemy_pawn_char)

    score = 0
    forward = 1 if color == WHITE else -1
    for f in range(8):
        ranks_here = own_files[f]
        if not ranks_here:
            continue
        if len(ranks_here) > 1:
            score -= 12 * (len(ranks_here) - 1)  # doubled pawns
        neighbors = (own_files[f - 1] if f > 0 else []) + (own_files[f + 1] if f < 7 else [])
        if not neighbors:
            score -= 10 * len(ranks_here)  # isolated pawns

        enemy_ahead = enemy_files[f]
        if f > 0:
            enemy_ahead = enemy_ahead + enemy_files[f - 1]
        if f < 7:
            enemy_ahead = enemy_ahead + enemy_files[f + 1]
        for r in ranks_here:
            blocked = any((er > r) if forward == 1 else (er < r) for er in enemy_ahead)
            if not blocked:
                advancement = r if color == WHITE else 7 - r
                score += 6 + 4 * advancement  # passed pawn bonus, bigger the further advanced
    return score


def _king_shield(board, color):
    king_sq = board.king_sq(color)
    if king_sq is None:
        return 0
    squares = board.squares
    pawn_char = "P" if color == WHITE else "p"
    kf, kr = file_of(king_sq), rank_of(king_sq)
    shield_rank = kr + 1 if color == WHITE else kr - 1
    score = 0
    if 0 <= shield_rank <= 7:
        for f in (kf - 1, kf, kf + 1):
            if 0 <= f <= 7:
                if squares[sq(f, shield_rank)] == pawn_char:
                    score += 10
                else:
                    score -= 8
    return score


def evaluate(board):
    """Absolute score in centipawns, positive favors White."""
    phase = game_phase(board)
    mg_score = 0
    eg_score = 0

    for square, piece in enumerate(board.squares):
        if piece == ".":
            continue
        kind = piece.upper()
        color = color_of(piece)
        sign = 1 if color == WHITE else -1
        value = PIECE_VALUES[kind]
        if kind == "K":
            idx = square if color == WHITE else _mirror(square)
            mg_score += sign * (value + KING_PST_MG[idx])
            eg_score += sign * (value + KING_PST_EG[idx])
        else:
            idx = square if color == WHITE else _mirror(square)
            pst_val = PST[kind][idx]
            mg_score += sign * (value + pst_val)
            eg_score += sign * (value + pst_val)

    tapered = (mg_score * phase + eg_score * (MAX_PHASE - phase)) / MAX_PHASE

    mobility = 2 * (_mobility_count(board, WHITE) - _mobility_count(board, BLACK))
    pawn_structure = _pawn_structure(board, WHITE) - _pawn_structure(board, BLACK)
    king_safety = 0
    if phase > MAX_PHASE // 3:  # king safety matters mostly outside the endgame
        king_safety = _king_shield(board, WHITE) - _king_shield(board, BLACK)

    return int(tapered + mobility + pawn_structure + king_safety)
