"""Pseudo-legal and legal move generation, attack detection, game state."""

from .board import Board, Move, sq, file_of, rank_of, color_of, WHITE, BLACK

KNIGHT_DELTAS = [(1, 2), (2, 1), (2, -1), (1, -2), (-1, -2), (-2, -1), (-2, 1), (-1, 2)]
KING_DELTAS = [(1, 0), (1, 1), (0, 1), (-1, 1), (-1, 0), (-1, -1), (0, -1), (1, -1)]
BISHOP_DIRS = [(1, 1), (1, -1), (-1, 1), (-1, -1)]
ROOK_DIRS = [(1, 0), (-1, 0), (0, 1), (0, -1)]
QUEEN_DIRS = BISHOP_DIRS + ROOK_DIRS

PROMO_PIECES = ("q", "r", "b", "n")


def _on_board(f, r):
    return 0 <= f < 8 and 0 <= r < 8


def opponent(color):
    return BLACK if color == WHITE else WHITE


def _build_leaper_table(deltas):
    table = []
    for square in range(64):
        f0, r0 = file_of(square), rank_of(square)
        targets = []
        for df, dr in deltas:
            f, r = f0 + df, r0 + dr
            if _on_board(f, r):
                targets.append(sq(f, r))
        table.append(targets)
    return table


def _build_rays(dirs):
    table = []
    for square in range(64):
        f0, r0 = file_of(square), rank_of(square)
        rays = []
        for df, dr in dirs:
            ray = []
            f, r = f0 + df, r0 + dr
            while _on_board(f, r):
                ray.append(sq(f, r))
                f += df
                r += dr
            rays.append(ray)
        table.append(rays)
    return table


def _build_pawn_attacker_sources():
    # PAWN_ATTACKER_SOURCES[color][square] = squares a `color` pawn would
    # need to stand on to attack `square` (i.e. the reverse of a pawn capture)
    table = {WHITE: [], BLACK: []}
    for by_color in (WHITE, BLACK):
        pawn_dr = 1 if by_color == WHITE else -1
        for square in range(64):
            f0, r0 = file_of(square), rank_of(square)
            sources = []
            for df in (-1, 1):
                f, r = f0 + df, r0 - pawn_dr
                if _on_board(f, r):
                    sources.append(sq(f, r))
            table[by_color].append(sources)
    return table


# Precomputed once at import time so hot-path attack detection is pure
# table lookups with no per-call bounds arithmetic or function-call overhead.
KNIGHT_TARGETS = _build_leaper_table(KNIGHT_DELTAS)
KING_TARGETS = _build_leaper_table(KING_DELTAS)
BISHOP_RAYS = _build_rays(BISHOP_DIRS)
ROOK_RAYS = _build_rays(ROOK_DIRS)
PAWN_ATTACKER_SOURCES = _build_pawn_attacker_sources()


def is_square_attacked(board, square, by_color):
    """True if `square` is attacked by any piece of `by_color`."""
    squares = board.squares

    pawn_char = "P" if by_color == WHITE else "p"
    for s in PAWN_ATTACKER_SOURCES[by_color][square]:
        if squares[s] == pawn_char:
            return True

    knight_char = "N" if by_color == WHITE else "n"
    for s in KNIGHT_TARGETS[square]:
        if squares[s] == knight_char:
            return True

    king_char = "K" if by_color == WHITE else "k"
    for s in KING_TARGETS[square]:
        if squares[s] == king_char:
            return True

    bishop_like = ("B", "Q") if by_color == WHITE else ("b", "q")
    for ray in BISHOP_RAYS[square]:
        for s in ray:
            p = squares[s]
            if p != ".":
                if p in bishop_like:
                    return True
                break

    rook_like = ("R", "Q") if by_color == WHITE else ("r", "q")
    for ray in ROOK_RAYS[square]:
        for s in ray:
            p = squares[s]
            if p != ".":
                if p in rook_like:
                    return True
                break

    return False


def is_in_check(board, color):
    king_sq = board.king_sq(color)
    if king_sq is None:
        return False
    return is_square_attacked(board, king_sq, opponent(color))


def generate_pseudo_legal_moves(board):
    moves = []
    color = board.to_move
    squares = board.squares
    for square in range(64):
        piece = squares[square]
        if piece == "." or color_of(piece) != color:
            continue
        kind = piece.upper()
        if kind == "P":
            _pawn_moves(board, square, piece, color, moves)
        elif kind == "N":
            _leaper_moves(board, square, piece, color, KNIGHT_DELTAS, moves)
        elif kind == "K":
            _leaper_moves(board, square, piece, color, KING_DELTAS, moves)
            _castle_moves(board, color, moves)
        elif kind == "B":
            _slider_moves(board, square, piece, color, BISHOP_DIRS, moves)
        elif kind == "R":
            _slider_moves(board, square, piece, color, ROOK_DIRS, moves)
        elif kind == "Q":
            _slider_moves(board, square, piece, color, QUEEN_DIRS, moves)
    return moves


def _pawn_moves(board, square, piece, color, moves):
    squares = board.squares
    f0, r0 = file_of(square), rank_of(square)
    forward = 1 if color == WHITE else -1
    start_rank = 1 if color == WHITE else 6
    promo_rank = 7 if color == WHITE else 0

    r1 = r0 + forward
    if _on_board(f0, r1):
        target = sq(f0, r1)
        if squares[target] == ".":
            if r1 == promo_rank:
                for promo in PROMO_PIECES:
                    p = promo.upper() if color == WHITE else promo
                    moves.append(Move(square, target, piece, None, p))
            else:
                moves.append(Move(square, target, piece))
            r2 = r0 + 2 * forward
            if r0 == start_rank and _on_board(f0, r2):
                target2 = sq(f0, r2)
                if squares[target2] == ".":
                    moves.append(Move(square, target2, piece, is_double=True))

    for df in (-1, 1):
        f, r = f0 + df, r1
        if not _on_board(f, r):
            continue
        target = sq(f, r)
        occ = squares[target]
        if occ != "." and color_of(occ) != color:
            if r == promo_rank:
                for promo in PROMO_PIECES:
                    p = promo.upper() if color == WHITE else promo
                    moves.append(Move(square, target, piece, occ, p))
            else:
                moves.append(Move(square, target, piece, occ))
        elif occ == "." and board.ep_square == target:
            moves.append(Move(square, target, piece, "p" if color == WHITE else "P", is_ep=True))


def _leaper_moves(board, square, piece, color, deltas, moves):
    squares = board.squares
    f0, r0 = file_of(square), rank_of(square)
    for df, dr in deltas:
        f, r = f0 + df, r0 + dr
        if not _on_board(f, r):
            continue
        target = sq(f, r)
        occ = squares[target]
        if occ == "." :
            moves.append(Move(square, target, piece))
        elif color_of(occ) != color:
            moves.append(Move(square, target, piece, occ))


def _slider_moves(board, square, piece, color, dirs, moves):
    squares = board.squares
    f0, r0 = file_of(square), rank_of(square)
    for df, dr in dirs:
        f, r = f0 + df, r0 + dr
        while _on_board(f, r):
            target = sq(f, r)
            occ = squares[target]
            if occ == ".":
                moves.append(Move(square, target, piece))
            else:
                if color_of(occ) != color:
                    moves.append(Move(square, target, piece, occ))
                break
            f += df
            r += dr


def _castle_moves(board, color, moves):
    squares = board.squares
    opp = opponent(color)
    if color == WHITE:
        rank = 0
        king_from = sq(4, 0)
        rights = (("K", sq(6, 0), (sq(5, 0), sq(6, 0)), (sq(4, 0), sq(5, 0), sq(6, 0))),
                  ("Q", sq(2, 0), (sq(1, 0), sq(2, 0), sq(3, 0)), (sq(4, 0), sq(3, 0), sq(2, 0))))
    else:
        rank = 7
        king_from = sq(4, 7)
        rights = (("k", sq(6, 7), (sq(5, 7), sq(6, 7)), (sq(4, 7), sq(5, 7), sq(6, 7))),
                  ("q", sq(2, 7), (sq(1, 7), sq(2, 7), sq(3, 7)), (sq(4, 7), sq(3, 7), sq(2, 7))))

    if squares[king_from] not in ("K", "k"):
        return
    if is_square_attacked(board, king_from, opp):
        return  # can't castle out of check

    for right, king_to, empty_squares, king_path in rights:
        if right not in board.castling:
            continue
        if any(squares[s] != "." for s in empty_squares):
            continue
        if any(is_square_attacked(board, s, opp) for s in king_path):
            continue
        piece = "K" if color == WHITE else "k"
        moves.append(Move(king_from, king_to, piece, castle=right))


def generate_legal_moves(board):
    """Filter pseudo-legal moves down to ones that don't leave own king in check."""
    color = board.to_move
    legal = []
    for move in generate_pseudo_legal_moves(board):
        u = board.make_move(move)
        if not is_in_check(board, color):
            legal.append(move)
        board.unmake_move(move, u)
    return legal


def generate_legal_captures(board):
    """Like generate_legal_moves, but only captures/promotions -- cheaper
    to call at quiescence-search leaves since it skips legality-checking
    every quiet move in the position."""
    color = board.to_move
    legal = []
    for move in generate_pseudo_legal_moves(board):
        if not (move.captured or move.promotion):
            continue
        u = board.make_move(move)
        if not is_in_check(board, color):
            legal.append(move)
        board.unmake_move(move, u)
    return legal


def has_insufficient_material(board):
    pieces = [p for p in board.squares if p != "."]
    non_king = [p for p in pieces if p.upper() != "K"]
    if not non_king:
        return True
    if len(non_king) == 1 and non_king[0].upper() in ("N", "B"):
        return True
    if len(non_king) == 2 and all(p.upper() == "B" for p in non_king):
        # same-color bishops only (opposite-color bishops can still mate)
        squares_of = [i for i, p in enumerate(board.squares) if p.upper() == "B"]
        colors = {(file_of(s) + rank_of(s)) % 2 for s in squares_of}
        if len(colors) == 1:
            return True
    return False


def game_state(board, position_history=None):
    """Returns one of: 'ongoing', 'checkmate', 'stalemate',
    'draw_fifty', 'draw_insufficient', 'draw_repetition'.

    `position_history`, if given, is the list of Zobrist hashes of every
    position that has occurred so far in the *actual game* (append one
    after each real move played -- not search lookahead). Threefold
    repetition is only checkable with that history, since a bare Board
    has no memory of prior positions beyond one ply of undo info.
    """
    legal = generate_legal_moves(board)
    in_check = is_in_check(board, board.to_move)
    if not legal:
        return "checkmate" if in_check else "stalemate"
    if board.halfmove_clock >= 100:
        return "draw_fifty"
    if has_insufficient_material(board):
        return "draw_insufficient"
    if position_history is not None and position_history:
        if position_history.count(position_history[-1]) >= 3:
            return "draw_repetition"
    return "ongoing"
