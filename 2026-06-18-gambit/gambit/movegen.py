"""Pseudo-legal and fully-legal move generation, plus attack/check detection.

Legality is enforced by the make-and-test method: generate pseudo-legal moves,
play each, and keep it only if it does not leave the mover's king in check. This
is simple and provably correct (it naturally handles pins, en-passant discovered
checks, and castling-through-check when combined with the explicit castling-square
attack tests).
"""

from __future__ import annotations

from .board import (
    Board, WHITE, BLACK, EMPTY, PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING,
    make_piece, piece_type, piece_color, on_board, sq_index, sq_rank, sq_file,
    encode_move, move_from, move_to, move_flag,
    F_NORMAL, F_DOUBLE, F_KCASTLE, F_QCASTLE, F_EP, F_PROMO,
    CASTLE_WK, CASTLE_WQ, CASTLE_BK, CASTLE_BQ,
)

KNIGHT_OFFSETS = (33, 31, 18, 14, -33, -31, -18, -14)
KING_OFFSETS = (16, 17, 1, -15, -16, -17, -1, 15)
BISHOP_DIRS = (17, 15, -17, -15)
ROOK_DIRS = (16, -16, 1, -1)
QUEEN_DIRS = BISHOP_DIRS + ROOK_DIRS

# Pawn capture offsets by color (toward the opponent)
PAWN_CAPS = {WHITE: (15, 17), BLACK: (-15, -17)}
PAWN_PUSH = {WHITE: 16, BLACK: -16}
START_RANK = {WHITE: 1, BLACK: 6}
PROMO_RANK = {WHITE: 7, BLACK: 0}

SLIDER_DIRS = {BISHOP: BISHOP_DIRS, ROOK: ROOK_DIRS, QUEEN: QUEEN_DIRS}


def square_attacked(board: Board, sq: int, by_color: int) -> bool:
    """Is `sq` attacked by any piece of `by_color`?"""
    sqs = board.squares

    # Pawn attacks: a pawn of by_color on sq-cap would attack sq.
    # White pawns attack upward (+15/+17), so they sit at sq-15/sq-17.
    if by_color == WHITE:
        for d in (-15, -17):
            s = sq + d
            if on_board(s) and sqs[s] == make_piece(PAWN, WHITE):
                return True
    else:
        for d in (15, 17):
            s = sq + d
            if on_board(s) and sqs[s] == make_piece(PAWN, BLACK):
                return True

    # Knights
    kn = make_piece(KNIGHT, by_color)
    for d in KNIGHT_OFFSETS:
        s = sq + d
        if on_board(s) and sqs[s] == kn:
            return True

    # King
    kg = make_piece(KING, by_color)
    for d in KING_OFFSETS:
        s = sq + d
        if on_board(s) and sqs[s] == kg:
            return True

    # Bishop/Queen diagonals
    bishop = make_piece(BISHOP, by_color)
    queen = make_piece(QUEEN, by_color)
    for d in BISHOP_DIRS:
        s = sq + d
        while on_board(s):
            p = sqs[s]
            if p:
                if p == bishop or p == queen:
                    return True
                break
            s += d

    # Rook/Queen lines
    rook = make_piece(ROOK, by_color)
    for d in ROOK_DIRS:
        s = sq + d
        while on_board(s):
            p = sqs[s]
            if p:
                if p == rook or p == queen:
                    return True
                break
            s += d

    return False


def in_check(board: Board, color: int) -> bool:
    return square_attacked(board, board.king_sq[color], color ^ 1)


def _gen_pseudo(board: Board) -> list:
    """All pseudo-legal moves for the side to move (king may be left in check)."""
    moves = []
    color = board.side
    opp = color ^ 1
    sqs = board.squares
    push = PAWN_PUSH[color]
    start_rank = START_RANK[color]
    promo_rank = PROMO_RANK[color]
    caps = PAWN_CAPS[color]

    for frm in range(128):
        if frm & 0x88:
            continue
        piece = sqs[frm]
        if not piece or piece_color(piece) != color:
            continue
        pt = piece_type(piece)

        if pt == PAWN:
            # single push
            one = frm + push
            if on_board(one) and sqs[one] == EMPTY:
                if sq_rank(one) == promo_rank:
                    for promo in (QUEEN, ROOK, BISHOP, KNIGHT):
                        moves.append(encode_move(frm, one, F_PROMO, promo))
                else:
                    moves.append(encode_move(frm, one, F_NORMAL))
                    # double push
                    if sq_rank(frm) == start_rank:
                        two = one + push
                        if sqs[two] == EMPTY:
                            moves.append(encode_move(frm, two, F_DOUBLE))
            # captures
            for d in caps:
                to = frm + d
                if not on_board(to):
                    continue
                target = sqs[to]
                if target and piece_color(target) == opp:
                    if sq_rank(to) == promo_rank:
                        for promo in (QUEEN, ROOK, BISHOP, KNIGHT):
                            moves.append(encode_move(frm, to, F_PROMO, promo))
                    else:
                        moves.append(encode_move(frm, to, F_NORMAL))
                elif board.ep is not None and to == board.ep:
                    moves.append(encode_move(frm, to, F_EP))

        elif pt == KNIGHT:
            for d in KNIGHT_OFFSETS:
                to = frm + d
                if on_board(to):
                    target = sqs[to]
                    if not target or piece_color(target) == opp:
                        moves.append(encode_move(frm, to, F_NORMAL))

        elif pt == KING:
            for d in KING_OFFSETS:
                to = frm + d
                if on_board(to):
                    target = sqs[to]
                    if not target or piece_color(target) == opp:
                        moves.append(encode_move(frm, to, F_NORMAL))
            _gen_castles(board, frm, color, moves)

        else:  # sliders
            for d in SLIDER_DIRS[pt]:
                to = frm + d
                while on_board(to):
                    target = sqs[to]
                    if not target:
                        moves.append(encode_move(frm, to, F_NORMAL))
                    else:
                        if piece_color(target) == opp:
                            moves.append(encode_move(frm, to, F_NORMAL))
                        break
                    to += d

    return moves


def _gen_castles(board: Board, king_sq: int, color: int, moves: list) -> None:
    sqs = board.squares
    opp = color ^ 1
    if color == WHITE:
        home = sq_index(4, 0)
        if king_sq != home:
            return
        if board.castling & CASTLE_WK:
            if sqs[sq_index(5, 0)] == EMPTY and sqs[sq_index(6, 0)] == EMPTY:
                if not (square_attacked(board, sq_index(4, 0), opp)
                        or square_attacked(board, sq_index(5, 0), opp)
                        or square_attacked(board, sq_index(6, 0), opp)):
                    moves.append(encode_move(home, sq_index(6, 0), F_KCASTLE))
        if board.castling & CASTLE_WQ:
            if (sqs[sq_index(3, 0)] == EMPTY and sqs[sq_index(2, 0)] == EMPTY
                    and sqs[sq_index(1, 0)] == EMPTY):
                if not (square_attacked(board, sq_index(4, 0), opp)
                        or square_attacked(board, sq_index(3, 0), opp)
                        or square_attacked(board, sq_index(2, 0), opp)):
                    moves.append(encode_move(home, sq_index(2, 0), F_QCASTLE))
    else:
        home = sq_index(4, 7)
        if king_sq != home:
            return
        if board.castling & CASTLE_BK:
            if sqs[sq_index(5, 7)] == EMPTY and sqs[sq_index(6, 7)] == EMPTY:
                if not (square_attacked(board, sq_index(4, 7), opp)
                        or square_attacked(board, sq_index(5, 7), opp)
                        or square_attacked(board, sq_index(6, 7), opp)):
                    moves.append(encode_move(home, sq_index(6, 7), F_KCASTLE))
        if board.castling & CASTLE_BQ:
            if (sqs[sq_index(3, 7)] == EMPTY and sqs[sq_index(2, 7)] == EMPTY
                    and sqs[sq_index(1, 7)] == EMPTY):
                if not (square_attacked(board, sq_index(4, 7), opp)
                        or square_attacked(board, sq_index(3, 7), opp)
                        or square_attacked(board, sq_index(2, 7), opp)):
                    moves.append(encode_move(home, sq_index(2, 7), F_QCASTLE))


def gen_pseudo(board: Board) -> list:
    """Public alias: all pseudo-legal moves for the side to move."""
    return _gen_pseudo(board)


def gen_pseudo_captures(board: Board) -> list:
    """Pseudo-legal captures and promotions only (for quiescence)."""
    return [mv for mv in _gen_pseudo(board)
            if is_capture(board, mv) or move_flag(mv) == F_PROMO]


def legal_moves(board: Board) -> list:
    """Fully-legal moves for the side to move."""
    color = board.side
    result = []
    for mv in _gen_pseudo(board):
        board.make_move(mv)
        if not square_attacked(board, board.king_sq[color], color ^ 1):
            result.append(mv)
        board.unmake_move()
    return result


def is_capture(board: Board, mv: int) -> bool:
    return board.squares[move_to(mv)] != EMPTY or move_flag(mv) == F_EP


def gen_captures(board: Board) -> list:
    """Legal captures and promotions only (for quiescence search)."""
    color = board.side
    result = []
    for mv in _gen_pseudo(board):
        if not (is_capture(board, mv) or move_flag(mv) == F_PROMO):
            continue
        board.make_move(mv)
        if not square_attacked(board, board.king_sq[color], color ^ 1):
            result.append(mv)
        board.unmake_move()
    return result
