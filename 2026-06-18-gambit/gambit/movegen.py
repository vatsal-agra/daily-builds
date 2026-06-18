"""Pseudo-legal and fully-legal move generation, plus SAN conversion."""

from .board import (
    Board, WHITE, BLACK, EMPTY, PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING,
    make_piece, piece_color, piece_type, on_board, sq_index, sq_rank, sq_file,
    sq_name, parse_square, make_move, move_from, move_to, move_promo, move_flag,
    F_NORMAL, F_DOUBLE, F_EP, F_CASTLE, N, S, E, W,
    KNIGHT_DELTAS, BISHOP_DIRS, ROOK_DIRS, KING_DIRS,
    CR_WK, CR_WQ, CR_BK, CR_BQ,
)

_SLIDER_DIRS = {
    BISHOP: BISHOP_DIRS,
    ROOK: ROOK_DIRS,
    QUEEN: KING_DIRS,
}


def gen_pseudo(board):
    """Generate all pseudo-legal moves for the side to move (king may be left
    in check; castling here already excludes moving through/into check)."""
    moves = []
    sqs = board.squares
    color = board.side
    enemy = color ^ 1
    push = N if color == WHITE else S
    start_rank = 1 if color == WHITE else 6
    promo_rank = 7 if color == WHITE else 0

    for frm in range(128):
        if frm & 0x88:
            continue
        pc = sqs[frm]
        if pc == EMPTY or piece_color(pc) != color:
            continue
        pt = piece_type(pc)

        if pt == PAWN:
            # single push
            one = frm + push
            if on_board(one) and sqs[one] == EMPTY:
                if sq_rank(one) == promo_rank:
                    for pr in (QUEEN, ROOK, BISHOP, KNIGHT):
                        moves.append(make_move(frm, one, pr))
                else:
                    moves.append(make_move(frm, one))
                    # double push
                    if sq_rank(frm) == start_rank:
                        two = one + push
                        if sqs[two] == EMPTY:
                            moves.append(make_move(frm, two, 0, F_DOUBLE))
            # captures
            for cd in (push + E, push + W):
                tsq = frm + cd
                if not on_board(tsq):
                    continue
                tpc = sqs[tsq]
                if tpc != EMPTY and piece_color(tpc) == enemy:
                    if sq_rank(tsq) == promo_rank:
                        for pr in (QUEEN, ROOK, BISHOP, KNIGHT):
                            moves.append(make_move(frm, tsq, pr))
                    else:
                        moves.append(make_move(frm, tsq))
                elif tsq == board.ep:
                    moves.append(make_move(frm, tsq, 0, F_EP))

        elif pt == KNIGHT:
            for d in KNIGHT_DELTAS:
                tsq = frm + d
                if on_board(tsq):
                    tpc = sqs[tsq]
                    if tpc == EMPTY or piece_color(tpc) == enemy:
                        moves.append(make_move(frm, tsq))

        elif pt == KING:
            for d in KING_DIRS:
                tsq = frm + d
                if on_board(tsq):
                    tpc = sqs[tsq]
                    if tpc == EMPTY or piece_color(tpc) == enemy:
                        moves.append(make_move(frm, tsq))
            _gen_castles(board, frm, color, moves)

        else:  # sliders
            for d in _SLIDER_DIRS[pt]:
                tsq = frm + d
                while on_board(tsq):
                    tpc = sqs[tsq]
                    if tpc == EMPTY:
                        moves.append(make_move(frm, tsq))
                    else:
                        if piece_color(tpc) == enemy:
                            moves.append(make_move(frm, tsq))
                        break
                    tsq += d

    return moves


def _gen_castles(board, ksq, color, moves):
    sqs = board.squares
    enemy = color ^ 1
    if board.is_attacked(ksq, enemy):
        return  # cannot castle out of check
    if color == WHITE:
        if board.castling & CR_WK:
            if sqs[ksq + E] == EMPTY and sqs[ksq + 2 * E] == EMPTY:
                if not board.is_attacked(ksq + E, enemy) and \
                   not board.is_attacked(ksq + 2 * E, enemy):
                    moves.append(make_move(ksq, ksq + 2 * E, 0, F_CASTLE))
        if board.castling & CR_WQ:
            if sqs[ksq + W] == EMPTY and sqs[ksq + 2 * W] == EMPTY and \
               sqs[ksq + 3 * W] == EMPTY:
                if not board.is_attacked(ksq + W, enemy) and \
                   not board.is_attacked(ksq + 2 * W, enemy):
                    moves.append(make_move(ksq, ksq + 2 * W, 0, F_CASTLE))
    else:
        if board.castling & CR_BK:
            if sqs[ksq + E] == EMPTY and sqs[ksq + 2 * E] == EMPTY:
                if not board.is_attacked(ksq + E, enemy) and \
                   not board.is_attacked(ksq + 2 * E, enemy):
                    moves.append(make_move(ksq, ksq + 2 * E, 0, F_CASTLE))
        if board.castling & CR_BQ:
            if sqs[ksq + W] == EMPTY and sqs[ksq + 2 * W] == EMPTY and \
               sqs[ksq + 3 * W] == EMPTY:
                if not board.is_attacked(ksq + W, enemy) and \
                   not board.is_attacked(ksq + 2 * W, enemy):
                    moves.append(make_move(ksq, ksq + 2 * W, 0, F_CASTLE))


def gen_legal(board):
    """Filter pseudo-legal moves: a move is legal iff it does not leave the
    mover's own king in check. Castling is already check-validated above."""
    legal = []
    color = board.side
    for m in gen_pseudo(board):
        board.make(m)
        if not board.is_attacked(board.king_sq[color], color ^ 1):
            legal.append(m)
        board.unmake()
    return legal


def is_capture(board, m):
    if move_flag(m) == F_EP:
        return True
    return board.squares[move_to(m)] != EMPTY


def gen_captures(board):
    """Pseudo-legal captures and promotions only (for quiescence)."""
    out = []
    for m in gen_pseudo(board):
        if move_flag(m) == F_EP or board.squares[move_to(m)] != EMPTY \
                or move_promo(m):
            out.append(m)
    return out


# ----- SAN ----------------------------------------------------------------

_PT_LETTER = {KNIGHT: "N", BISHOP: "B", ROOK: "R", QUEEN: "Q", KING: "K"}


def to_san(board, m):
    """Standard Algebraic Notation for a *legal* move in the current position."""
    frm, to = move_from(m), move_to(m)
    if frm == to:
        return "(none)"
    flag = move_flag(m)
    pc = board.squares[frm]
    pt = piece_type(pc)

    if flag == F_CASTLE:
        san = "O-O" if to > frm else "O-O-O"
    else:
        capture = is_capture(board, m)
        if pt == PAWN:
            san = ""
            if capture:
                san += "abcdefgh"[sq_file(frm)] + "x"
            san += sq_name(to)
            if move_promo(m):
                san += "=" + _PT_LETTER[move_promo(m)]
        else:
            san = _PT_LETTER[pt]
            san += _disambig(board, m, pt, frm, to)
            if capture:
                san += "x"
            san += sq_name(to)

    # check / checkmate suffix
    board.make(m)
    if board.in_check():
        san += "#" if not gen_legal(board) else "+"
    board.unmake()
    return san


def _disambig(board, m, pt, frm, to):
    """Minimal file/rank disambiguation among same-type pieces that can also
    move to `to`."""
    others = []
    for mv in gen_legal(board):
        if move_to(mv) == to and move_from(mv) != frm:
            p = board.squares[move_from(mv)]
            if piece_type(p) == pt:
                others.append(move_from(mv))
    if not others:
        return ""
    same_file = any(sq_file(o) == sq_file(frm) for o in others)
    same_rank = any(sq_rank(o) == sq_rank(frm) for o in others)
    if not same_file:
        return "abcdefgh"[sq_file(frm)]
    if not same_rank:
        return str(sq_rank(frm) + 1)
    return sq_name(frm)


def parse_san(board, san):
    """Parse a SAN (or coordinate) string into a legal move, or None."""
    s = san.strip().rstrip("+#!?")
    legal = gen_legal(board)
    # try coordinate notation first (e2e4, e7e8q)
    if len(s) >= 4 and s[0] in "abcdefgh" and s[1] in "12345678" \
            and s[2] in "abcdefgh" and s[3] in "12345678":
        frm = parse_square(s[:2])
        to = parse_square(s[2:4])
        promo = 0
        if len(s) >= 5:
            promo = {"n": KNIGHT, "b": BISHOP, "r": ROOK,
                     "q": QUEEN}.get(s[4].lower(), 0)
        for m in legal:
            if move_from(m) == frm and move_to(m) == to and \
                    (not promo or move_promo(m) == promo):
                return m
        return None
    # otherwise match against generated SAN
    for m in legal:
        if to_san(board, m).rstrip("+#") == s:
            return m
    # tolerate missing capture 'x' / disambiguation differences
    for m in legal:
        if to_san(board, m).replace("x", "").rstrip("+#") == s.replace("x", ""):
            return m
    return None
