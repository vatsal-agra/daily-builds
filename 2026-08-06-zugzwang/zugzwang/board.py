"""Board representation, FEN import/export, and make/unmake move.

Squares are indexed 0..63, little-endian rank-file: a1=0, b1=1, ..., h1=7,
a2=8, ..., h8=63. Pieces are single characters, uppercase = White,
lowercase = Black: P N B R Q K / p n b r q k. Empty square = '.'.
"""

START_FEN = "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1"

FILES = "abcdefgh"
RANKS = "12345678"

WHITE, BLACK = "w", "b"


def sq(file_idx, rank_idx):
    return rank_idx * 8 + file_idx


def file_of(square):
    return square % 8


def rank_of(square):
    return square // 8


def square_name(square):
    return f"{FILES[file_of(square)]}{RANKS[rank_of(square)]}"


def parse_square(name):
    f = FILES.index(name[0])
    r = RANKS.index(name[1])
    return sq(f, r)


def color_of(piece):
    if piece == ".":
        return None
    return WHITE if piece.isupper() else BLACK


def is_white(piece):
    return piece != "." and piece.isupper()


def is_black(piece):
    return piece != "." and piece.islower()


class Move:
    __slots__ = ("frm", "to", "piece", "captured", "promotion", "is_ep", "castle", "is_double")

    def __init__(self, frm, to, piece, captured=None, promotion=None,
                 is_ep=False, castle=None, is_double=False):
        self.frm = frm
        self.to = to
        self.piece = piece          # piece character that is moving
        self.captured = captured    # piece character captured, or None
        self.promotion = promotion  # 'q','r','b','n' (case matches mover) or None
        self.is_ep = is_ep          # True if this is an en-passant capture
        self.castle = castle        # 'K','Q','k','q' or None
        self.is_double = is_double  # True if this is a pawn's initial two-square push

    def uci(self):
        s = square_name(self.frm) + square_name(self.to)
        if self.promotion:
            s += self.promotion.lower()
        return s

    def __eq__(self, other):
        if not isinstance(other, Move):
            return NotImplemented
        return (self.frm, self.to, self.promotion) == (other.frm, other.to, other.promotion)

    def __hash__(self):
        return hash((self.frm, self.to, self.promotion))

    def __repr__(self):
        return f"Move({self.uci()})"


class _Undo:
    """Bundle of state needed to unmake a move."""
    __slots__ = ("captured", "captured_sq", "castling", "ep_square",
                 "halfmove_clock", "rook_from", "rook_to", "rook_piece",
                 "white_king_sq", "black_king_sq")


class Board:
    def __init__(self):
        self.squares = ["."] * 64
        self.to_move = WHITE
        self.castling = set()          # subset of {'K','Q','k','q'}
        self.ep_square = None          # square behind a pawn that just double-pushed
        self.halfmove_clock = 0
        self.fullmove_number = 1
        self.white_king_sq = None
        self.black_king_sq = None
        self._hash_history = []        # zobrist keys of prior positions, for repetition

    # ------------------------------------------------------------------ FEN
    @classmethod
    def from_fen(cls, fen):
        b = cls()
        parts = fen.strip().split()
        placement, stm, castling, ep, halfmove, fullmove = (parts + ["-", "0", "1"])[:6]
        square = 56  # a8, FEN starts at rank 8
        for ch in placement:
            if ch == "/":
                square -= 16
            elif ch.isdigit():
                square += int(ch)
            else:
                b.squares[square] = ch
                if ch == "K":
                    b.white_king_sq = square
                elif ch == "k":
                    b.black_king_sq = square
                square += 1
        b.to_move = WHITE if stm == "w" else BLACK
        b.castling = set(c for c in castling if c in "KQkq")
        b.ep_square = parse_square(ep) if ep != "-" else None
        b.halfmove_clock = int(halfmove)
        b.fullmove_number = int(fullmove)
        return b

    def to_fen(self):
        rows = []
        for rank in range(7, -1, -1):
            row = ""
            empty = 0
            for file in range(8):
                p = self.squares[sq(file, rank)]
                if p == ".":
                    empty += 1
                else:
                    if empty:
                        row += str(empty)
                        empty = 0
                    row += p
            if empty:
                row += str(empty)
            rows.append(row)
        placement = "/".join(rows)
        stm = "w" if self.to_move == WHITE else "b"
        castling = "".join(c for c in "KQkq" if c in self.castling) or "-"
        ep = square_name(self.ep_square) if self.ep_square is not None else "-"
        return f"{placement} {stm} {castling} {ep} {self.halfmove_clock} {self.fullmove_number}"

    def copy(self):
        b = Board()
        b.squares = self.squares[:]
        b.to_move = self.to_move
        b.castling = set(self.castling)
        b.ep_square = self.ep_square
        b.halfmove_clock = self.halfmove_clock
        b.fullmove_number = self.fullmove_number
        b.white_king_sq = self.white_king_sq
        b.black_king_sq = self.black_king_sq
        return b

    def king_sq(self, color):
        return self.white_king_sq if color == WHITE else self.black_king_sq

    # ------------------------------------------------------------- make/unmake
    def make_move(self, move):
        u = _Undo()
        u.captured = move.captured
        u.captured_sq = move.to
        u.castling = set(self.castling)
        u.ep_square = self.ep_square
        u.halfmove_clock = self.halfmove_clock
        u.rook_from = u.rook_to = u.rook_piece = None
        u.white_king_sq = self.white_king_sq
        u.black_king_sq = self.black_king_sq

        mover_color = color_of(move.piece)

        # en-passant capture removes a pawn NOT on the destination square
        if move.is_ep:
            cap_sq = move.to + (-8 if mover_color == WHITE else 8)
            u.captured_sq = cap_sq
            self.squares[cap_sq] = "."

        self.squares[move.frm] = "."
        placed = move.promotion if move.promotion else move.piece
        self.squares[move.to] = placed

        # move the rook on castling
        if move.castle:
            rank = 0 if move.castle in ("K", "Q") else 7
            if move.castle in ("K", "k"):
                rf, rt = sq(7, rank), sq(5, rank)
            else:
                rf, rt = sq(0, rank), sq(3, rank)
            rook_piece = self.squares[rf]
            u.rook_from, u.rook_to, u.rook_piece = rf, rt, rook_piece
            self.squares[rf] = "."
            self.squares[rt] = rook_piece

        # king position tracking
        if move.piece == "K":
            self.white_king_sq = move.to
        elif move.piece == "k":
            self.black_king_sq = move.to

        # castling rights: moving king or rook, or capturing a rook, revokes rights
        self._update_castling_rights(move)

        # en-passant target square for the *next* move
        self.ep_square = None
        if move.is_double:
            self.ep_square = (move.frm + move.to) // 2

        # halfmove clock: reset on pawn move or capture
        if move.piece.upper() == "P" or move.captured or move.is_ep:
            self.halfmove_clock = 0
        else:
            self.halfmove_clock += 1

        if self.to_move == BLACK:
            self.fullmove_number += 1
        self.to_move = BLACK if self.to_move == WHITE else WHITE

        return u

    def unmake_move(self, move, u):
        self.to_move = BLACK if self.to_move == WHITE else WHITE
        if self.to_move == BLACK:
            self.fullmove_number -= 1

        self.squares[move.frm] = move.piece
        self.squares[move.to] = "."

        if move.is_ep:
            mover_color = color_of(move.piece)
            cap_sq = move.to + (-8 if mover_color == WHITE else 8)
            self.squares[cap_sq] = u.captured
        elif move.captured:
            self.squares[move.to] = move.captured

        if move.castle:
            self.squares[u.rook_to] = "."
            self.squares[u.rook_from] = u.rook_piece

        self.white_king_sq = u.white_king_sq
        self.black_king_sq = u.black_king_sq
        self.castling = u.castling
        self.ep_square = u.ep_square
        self.halfmove_clock = u.halfmove_clock

    def _update_castling_rights(self, move):
        if not self.castling:
            return
        if move.piece == "K":
            self.castling.discard("K")
            self.castling.discard("Q")
        elif move.piece == "k":
            self.castling.discard("k")
            self.castling.discard("q")

        for corner, right in ((sq(0, 0), "Q"), (sq(7, 0), "K"), (sq(0, 7), "q"), (sq(7, 7), "k")):
            if move.frm == corner or move.to == corner:
                self.castling.discard(right)

    def piece_at(self, square):
        return self.squares[square]

    def __str__(self):
        lines = []
        for rank in range(7, -1, -1):
            row = f"{rank + 1} "
            for file in range(8):
                row += self.squares[sq(file, rank)] + " "
            lines.append(row)
        lines.append("  " + " ".join(FILES))
        return "\n".join(lines)
