"""0x88 board representation, FEN I/O, make/unmake, and incremental Zobrist keys.

Square indexing (0x88): sq = rank * 16 + file, with rank 0 = white's first rank
(a1 = 0, h1 = 7, a8 = 112, h8 = 119). A square is on-board iff (sq & 0x88) == 0.

Pieces are small ints: type in bits 0..2, color in bit 3.
"""

from __future__ import annotations

import random

# Colors
WHITE, BLACK = 0, 1

# Piece types
EMPTY = 0
PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = 1, 2, 3, 4, 5, 6

COLOR_BIT = 8  # color stored in bit 3


def make_piece(ptype: int, color: int) -> int:
    return ptype | (color << 3)


def piece_type(piece: int) -> int:
    return piece & 7


def piece_color(piece: int) -> int:
    return (piece >> 3) & 1


# Castling-rights bitmask
CASTLE_WK, CASTLE_WQ, CASTLE_BK, CASTLE_BQ = 1, 2, 4, 8

# Move flags
F_NORMAL, F_DOUBLE, F_KCASTLE, F_QCASTLE, F_EP, F_PROMO = 0, 1, 2, 3, 4, 5

# Char tables
PIECE_TO_CHAR = {
    make_piece(PAWN, WHITE): "P", make_piece(KNIGHT, WHITE): "N",
    make_piece(BISHOP, WHITE): "B", make_piece(ROOK, WHITE): "R",
    make_piece(QUEEN, WHITE): "Q", make_piece(KING, WHITE): "K",
    make_piece(PAWN, BLACK): "p", make_piece(KNIGHT, BLACK): "n",
    make_piece(BISHOP, BLACK): "b", make_piece(ROOK, BLACK): "r",
    make_piece(QUEEN, BLACK): "q", make_piece(KING, BLACK): "k",
}
CHAR_TO_PIECE = {v: k for k, v in PIECE_TO_CHAR.items()}


def sq_index(file: int, rank: int) -> int:
    return rank * 16 + file


def sq_file(sq: int) -> int:
    return sq & 7


def sq_rank(sq: int) -> int:
    return sq >> 4


def on_board(sq: int) -> bool:
    return (sq & 0x88) == 0


def sq_name(sq: int) -> str:
    return "abcdefgh"[sq_file(sq)] + str(sq_rank(sq) + 1)


def parse_sq(name: str) -> int:
    f = "abcdefgh".index(name[0])
    r = int(name[1]) - 1
    return sq_index(f, r)


# ---- Move encoding ----------------------------------------------------------
# Packed int: from (0..7) | to (8..15) | promo type (16..18) | flag (20..22)

def encode_move(frm: int, to: int, flag: int = F_NORMAL, promo: int = 0) -> int:
    return frm | (to << 8) | (promo << 16) | (flag << 20)


def move_from(mv: int) -> int:
    return mv & 0xFF


def move_to(mv: int) -> int:
    return (mv >> 8) & 0xFF


def move_promo(mv: int) -> int:
    return (mv >> 16) & 7


def move_flag(mv: int) -> int:
    return (mv >> 20) & 7


def move_uci(mv: int) -> str:
    s = sq_name(move_from(mv)) + sq_name(move_to(mv))
    if move_flag(mv) == F_PROMO:
        s += " nbrq"[move_promo(mv) - 1] if move_promo(mv) else "q"
    return s


# ---- Zobrist ----------------------------------------------------------------
_zrng = random.Random(0xC0FFEE_2026)
ZOBRIST_PIECE = [[_zrng.getrandbits(64) for _ in range(128)] for _ in range(16)]
ZOBRIST_SIDE = _zrng.getrandbits(64)
ZOBRIST_CASTLE = [_zrng.getrandbits(64) for _ in range(16)]
ZOBRIST_EP_FILE = [_zrng.getrandbits(64) for _ in range(8)]


class Board:
    __slots__ = (
        "squares", "side", "castling", "ep", "halfmove", "fullmove",
        "king_sq", "zobrist", "_undo",
    )

    START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

    def __init__(self):
        self.squares = [EMPTY] * 128
        self.side = WHITE
        self.castling = 0
        self.ep = None
        self.halfmove = 0
        self.fullmove = 1
        self.king_sq = [None, None]
        self.zobrist = 0
        self._undo = []

    # ---- FEN ----
    @classmethod
    def from_fen(cls, fen: str) -> "Board":
        b = cls()
        parts = fen.strip().split()
        if len(parts) < 4:
            raise ValueError(f"FEN needs at least 4 fields, got {len(parts)}: {fen!r}")
        placement, active, castle, ep = parts[0], parts[1], parts[2], parts[3]
        half = parts[4] if len(parts) > 4 else "0"
        full = parts[5] if len(parts) > 5 else "1"

        ranks = placement.split("/")
        if len(ranks) != 8:
            raise ValueError(f"FEN placement needs 8 ranks, got {len(ranks)}")
        for ri, row in enumerate(ranks):
            rank = 7 - ri  # FEN starts from rank 8
            file = 0
            for ch in row:
                if ch.isdigit():
                    file += int(ch)
                else:
                    if ch not in CHAR_TO_PIECE:
                        raise ValueError(f"bad piece char {ch!r} in FEN")
                    if file > 7:
                        raise ValueError("too many squares in a FEN rank")
                    piece = CHAR_TO_PIECE[ch]
                    sq = sq_index(file, rank)
                    b.squares[sq] = piece
                    if piece_type(piece) == KING:
                        b.king_sq[piece_color(piece)] = sq
                    file += 1
            if file != 8:
                raise ValueError(f"FEN rank does not sum to 8 files: {row!r}")

        if active not in ("w", "b"):
            raise ValueError(f"bad active color {active!r}")
        b.side = WHITE if active == "w" else BLACK

        b.castling = 0
        if castle != "-":
            for ch in castle:
                b.castling |= {
                    "K": CASTLE_WK, "Q": CASTLE_WQ,
                    "k": CASTLE_BK, "q": CASTLE_BQ,
                }.get(ch, 0)

        b.ep = None if ep == "-" else parse_sq(ep)
        b.halfmove = int(half)
        b.fullmove = int(full)
        if b.king_sq[WHITE] is None or b.king_sq[BLACK] is None:
            raise ValueError("FEN missing a king")
        b.zobrist = b._compute_zobrist()
        return b

    @classmethod
    def startpos(cls) -> "Board":
        return cls.from_fen(cls.START_FEN)

    def to_fen(self) -> str:
        rows = []
        for ri in range(8):
            rank = 7 - ri
            run = 0
            row = ""
            for file in range(8):
                piece = self.squares[sq_index(file, rank)]
                if piece == EMPTY:
                    run += 1
                else:
                    if run:
                        row += str(run)
                        run = 0
                    row += PIECE_TO_CHAR[piece]
            if run:
                row += str(run)
            rows.append(row)
        placement = "/".join(rows)
        active = "w" if self.side == WHITE else "b"
        cs = ""
        if self.castling & CASTLE_WK: cs += "K"
        if self.castling & CASTLE_WQ: cs += "Q"
        if self.castling & CASTLE_BK: cs += "k"
        if self.castling & CASTLE_BQ: cs += "q"
        cs = cs or "-"
        ep = "-" if self.ep is None else sq_name(self.ep)
        return f"{placement} {active} {cs} {ep} {self.halfmove} {self.fullmove}"

    # ---- Zobrist ----
    def _compute_zobrist(self) -> int:
        h = 0
        for sq in range(128):
            if on_board(sq):
                p = self.squares[sq]
                if p:
                    h ^= ZOBRIST_PIECE[p][sq]
        if self.side == BLACK:
            h ^= ZOBRIST_SIDE
        h ^= ZOBRIST_CASTLE[self.castling]
        if self.ep is not None:
            h ^= ZOBRIST_EP_FILE[sq_file(self.ep)]
        return h

    # ---- make / unmake ----
    def make_move(self, mv: int) -> None:
        frm = move_from(mv)
        to = move_to(mv)
        flag = move_flag(mv)
        piece = self.squares[frm]
        color = self.side
        opp = color ^ 1
        captured = self.squares[to]

        # save undo record
        self._undo.append((
            mv, captured, self.castling, self.ep,
            self.halfmove, self.fullmove, self.zobrist,
            self.king_sq[WHITE], self.king_sq[BLACK],
        ))

        z = self.zobrist
        # clear ep from hash (re-added later if a new ep arises)
        if self.ep is not None:
            z ^= ZOBRIST_EP_FILE[sq_file(self.ep)]
        new_ep = None

        # remove moving piece from origin
        z ^= ZOBRIST_PIECE[piece][frm]
        self.squares[frm] = EMPTY

        # handle capture on destination (non-ep)
        if captured:
            z ^= ZOBRIST_PIECE[captured][to]

        if flag == F_EP:
            # captured pawn sits behind the destination
            cap_sq = to + (-16 if color == WHITE else 16)
            cap_pawn = self.squares[cap_sq]
            z ^= ZOBRIST_PIECE[cap_pawn][cap_sq]
            self.squares[cap_sq] = EMPTY

        # place piece (with promotion)
        if flag == F_PROMO:
            promo_piece = make_piece(move_promo(mv), color)
            self.squares[to] = promo_piece
            z ^= ZOBRIST_PIECE[promo_piece][to]
        else:
            self.squares[to] = piece
            z ^= ZOBRIST_PIECE[piece][to]

        # king moves update cache
        if piece_type(piece) == KING:
            self.king_sq[color] = to

        # castling: move the rook
        if flag == F_KCASTLE:
            rfrom, rto = (to + 1, to - 1)
            rook = self.squares[rfrom]
            self.squares[rfrom] = EMPTY
            self.squares[rto] = rook
            z ^= ZOBRIST_PIECE[rook][rfrom] ^ ZOBRIST_PIECE[rook][rto]
        elif flag == F_QCASTLE:
            rfrom, rto = (to - 2, to + 1)
            rook = self.squares[rfrom]
            self.squares[rfrom] = EMPTY
            self.squares[rto] = rook
            z ^= ZOBRIST_PIECE[rook][rfrom] ^ ZOBRIST_PIECE[rook][rto]

        # double pawn push sets ep target
        if flag == F_DOUBLE:
            new_ep = (frm + to) // 2
            z ^= ZOBRIST_EP_FILE[sq_file(new_ep)]

        # update castling rights
        old_castling = self.castling
        new_castling = old_castling & _CASTLE_MASK[frm] & _CASTLE_MASK[to]
        if new_castling != old_castling:
            z ^= ZOBRIST_CASTLE[old_castling] ^ ZOBRIST_CASTLE[new_castling]
        self.castling = new_castling

        # halfmove clock
        if piece_type(piece) == PAWN or captured or flag == F_EP:
            self.halfmove = 0
        else:
            self.halfmove += 1

        if color == BLACK:
            self.fullmove += 1

        self.ep = new_ep
        self.side = opp
        z ^= ZOBRIST_SIDE
        self.zobrist = z

    def unmake_move(self) -> None:
        (mv, captured, castling, ep, halfmove, fullmove, zob,
         wk, bk) = self._undo.pop()
        frm = move_from(mv)
        to = move_to(mv)
        flag = move_flag(mv)
        color = self.side ^ 1  # side that made the move

        # restore moving piece at origin
        if flag == F_PROMO:
            self.squares[frm] = make_piece(PAWN, color)
        else:
            self.squares[frm] = self.squares[to]

        # restore destination
        self.squares[to] = captured

        if flag == F_EP:
            cap_sq = to + (-16 if color == WHITE else 16)
            self.squares[cap_sq] = make_piece(PAWN, color ^ 1)
            self.squares[to] = EMPTY

        if flag == F_KCASTLE:
            rfrom, rto = (to + 1, to - 1)
            self.squares[rfrom] = self.squares[rto]
            self.squares[rto] = EMPTY
        elif flag == F_QCASTLE:
            rfrom, rto = (to - 2, to + 1)
            self.squares[rfrom] = self.squares[rto]
            self.squares[rto] = EMPTY

        self.side = color
        self.castling = castling
        self.ep = ep
        self.halfmove = halfmove
        self.fullmove = fullmove
        self.zobrist = zob
        self.king_sq[WHITE] = wk
        self.king_sq[BLACK] = bk

    def make_null_move(self) -> None:
        """Pass the turn (for null-move pruning); ep cleared."""
        self._undo.append((
            -1, EMPTY, self.castling, self.ep,
            self.halfmove, self.fullmove, self.zobrist,
            self.king_sq[WHITE], self.king_sq[BLACK],
        ))
        z = self.zobrist
        if self.ep is not None:
            z ^= ZOBRIST_EP_FILE[sq_file(self.ep)]
        self.ep = None
        self.side ^= 1
        z ^= ZOBRIST_SIDE
        self.halfmove += 1
        self.zobrist = z

    def unmake_null_move(self) -> None:
        (_mv, _cap, castling, ep, halfmove, fullmove, zob,
         wk, bk) = self._undo.pop()
        self.side ^= 1
        self.castling = castling
        self.ep = ep
        self.halfmove = halfmove
        self.fullmove = fullmove
        self.zobrist = zob
        self.king_sq[WHITE] = wk
        self.king_sq[BLACK] = bk

    def piece_at(self, sq: int) -> int:
        return self.squares[sq]

    def __str__(self) -> str:
        lines = []
        for ri in range(8):
            rank = 7 - ri
            row = []
            for file in range(8):
                p = self.squares[sq_index(file, rank)]
                row.append(PIECE_TO_CHAR.get(p, "."))
            lines.append(f"{rank + 1}  " + " ".join(row))
        lines.append("   a b c d e f g h")
        return "\n".join(lines)


# Castling-rights mask: AND with rights when a square is touched (moved from / to).
# Moving the king or rook, or capturing a rook on its home square, clears rights.
_CASTLE_MASK = [0b1111] * 128
_CASTLE_MASK[sq_index(4, 0)] = 0b1111 & ~(CASTLE_WK | CASTLE_WQ)  # e1
_CASTLE_MASK[sq_index(0, 0)] = 0b1111 & ~CASTLE_WQ  # a1
_CASTLE_MASK[sq_index(7, 0)] = 0b1111 & ~CASTLE_WK  # h1
_CASTLE_MASK[sq_index(4, 7)] = 0b1111 & ~(CASTLE_BK | CASTLE_BQ)  # e8
_CASTLE_MASK[sq_index(0, 7)] = 0b1111 & ~CASTLE_BQ  # a8
_CASTLE_MASK[sq_index(7, 7)] = 0b1111 & ~CASTLE_BK  # h8
