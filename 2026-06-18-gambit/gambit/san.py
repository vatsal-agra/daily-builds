"""Standard Algebraic Notation (SAN) formatting and parsing, plus minimal PGN.

SAN is produced with correct disambiguation and check/mate suffixes. Parsing is
done by formatting every legal move and matching the (normalised) input, which is
robust against notation variants (e.g. missing/extra check marks).
"""

from __future__ import annotations

from .board import (
    Board, WHITE, PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING,
    piece_type, piece_color, sq_name, sq_file, sq_rank,
    move_from, move_to, move_flag, move_promo,
    F_KCASTLE, F_QCASTLE, F_EP, F_PROMO,
)
from .movegen import legal_moves, in_check, is_capture

PIECE_LETTER = {KNIGHT: "N", BISHOP: "B", ROOK: "R", QUEEN: "Q", KING: "K"}
LETTER_PIECE = {v: k for k, v in PIECE_LETTER.items()}


def to_san(board: Board, mv: int) -> str:
    flag = move_flag(mv)
    if flag == F_KCASTLE:
        san = "O-O"
    elif flag == F_QCASTLE:
        san = "O-O-O"
    else:
        frm = move_from(mv)
        to = move_to(mv)
        piece = board.squares[frm]
        pt = piece_type(piece)
        capture = is_capture(board, mv)

        if pt == PAWN:
            san = ""
            if capture:
                san += "abcdefgh"[sq_file(frm)] + "x"
            san += sq_name(to)
            if flag == F_PROMO:
                san += "=" + PIECE_LETTER[move_promo(mv)]
        else:
            san = PIECE_LETTER[pt]
            san += _disambiguation(board, mv, pt, to, frm)
            if capture:
                san += "x"
            san += sq_name(to)

    # check / checkmate suffix
    board.make_move(mv)
    if in_check(board, board.side):
        san += "#" if not legal_moves(board) else "+"
    board.unmake_move()
    return san


def _disambiguation(board, mv, pt, to, frm) -> str:
    """Minimal disambiguation among same-type pieces reaching the same square."""
    others = []
    for other in legal_moves(board):
        if other == mv:
            continue
        if move_to(other) != to:
            continue
        ofrm = move_from(other)
        if piece_type(board.squares[ofrm]) == pt:
            others.append(ofrm)
    if not others:
        return ""
    same_file = any(sq_file(o) == sq_file(frm) for o in others)
    same_rank = any(sq_rank(o) == sq_rank(frm) for o in others)
    if not same_file:
        return "abcdefgh"[sq_file(frm)]
    if not same_rank:
        return str(sq_rank(frm) + 1)
    return sq_name(frm)


def _normalise(s: str) -> str:
    return s.replace("+", "").replace("#", "").replace("!", "").replace("?", "") \
            .replace("0-0-0", "O-O-O").replace("0-0", "O-O").strip()


def from_san(board: Board, san: str) -> int:
    """Parse a SAN string into a legal move on `board`. Raises ValueError if none."""
    target = _normalise(san)
    for mv in legal_moves(board):
        if _normalise(to_san(board, mv)) == target:
            return mv
    raise ValueError(f"no legal move matches SAN {san!r} in position {board.to_fen()!r}")


def game_to_pgn(start_fen: str, moves_san: list, result: str = "*",
                headers: dict | None = None) -> str:
    """Build a PGN string from a starting FEN and a list of SAN strings."""
    out = []
    hdr = {
        "Event": "Gambit game",
        "Site": "local",
        "White": "Gambit",
        "Black": "Gambit",
        "Result": result,
    }
    if headers:
        hdr.update(headers)
    if start_fen.strip() != Board.START_FEN:
        hdr["FEN"] = start_fen
        hdr["SetUp"] = "1"
    for k, v in hdr.items():
        out.append(f'[{k} "{v}"]')
    out.append("")

    # move text — start move number/colour from the FEN
    b = Board.from_fen(start_fen)
    body = []
    num = b.fullmove
    if b.side != WHITE:
        body.append(f"{num}...")
    for i, s in enumerate(moves_san):
        if b.side == WHITE:
            body.append(f"{num}.")
        body.append(s)
        if b.side != WHITE:
            num += 1
        b.make_move(from_san(b, s))
    body.append(result)
    out.append(" ".join(body))
    return "\n".join(out)
