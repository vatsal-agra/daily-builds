"""0x88 mailbox board: representation, FEN, Zobrist, make/unmake.

Squares use the 0x88 scheme: sq = rank*16 + file, with a1=0, h1=7, a8=112,
h8=119. A square is off the board iff (sq & 0x88) != 0, which makes off-board
detection a single bitwise AND.

Piece codes: type in low 3 bits (PAWN..KING = 1..6), color bit is bit 3
(WHITE=0 -> 1..6, BLACK=1 -> 9..14). EMPTY = 0.
"""

import random

# Colors
WHITE, BLACK = 0, 1

# Piece types
EMPTY = 0
PAWN, KNIGHT, BISHOP, ROOK, QUEEN, KING = 1, 2, 3, 4, 5, 6

COLOR_BIT = 8


def make_piece(color, ptype):
    return (color << 3) | ptype


def piece_color(pc):
    return (pc >> 3) & 1


def piece_type(pc):
    return pc & 7


# Castling-rights bit flags
CR_WK, CR_WQ, CR_BK, CR_BQ = 1, 2, 4, 8

# Move flags
F_NORMAL, F_DOUBLE, F_EP, F_CASTLE = 0, 1, 2, 3

# Direction offsets (0x88)
N, S, E, W = 16, -16, 1, -1
KNIGHT_DELTAS = (33, 31, 18, 14, -33, -31, -18, -14)
BISHOP_DIRS = (17, 15, -17, -15)
ROOK_DIRS = (16, -16, 1, -1)
KING_DIRS = (16, -16, 1, -1, 17, 15, -17, -15)

PIECE_LETTERS = ".PNBRQK"  # index by piece type for white; lower for black


# ----- square helpers -----------------------------------------------------

def sq_index(file, rank):
    return rank * 16 + file


def sq_file(sq):
    return sq & 7


def sq_rank(sq):
    return sq >> 4


def on_board(sq):
    return not (sq & 0x88)


def sq_name(sq):
    return "abcdefgh"[sq_file(sq)] + str(sq_rank(sq) + 1)


def parse_square(name):
    f = "abcdefgh".index(name[0])
    r = int(name[1]) - 1
    return sq_index(f, r)


# ----- move encoding (packed int) -----------------------------------------
# bits 0-7: from, 8-15: to, 16-18: promo type, 19-21: flag

def make_move(frm, to, promo=0, flag=F_NORMAL):
    return frm | (to << 8) | (promo << 16) | (flag << 19)


def move_from(m):
    return m & 0xFF


def move_to(m):
    return (m >> 8) & 0xFF


def move_promo(m):
    return (m >> 16) & 7


def move_flag(m):
    return (m >> 19) & 7


def move_uci(m):
    s = sq_name(move_from(m)) + sq_name(move_to(m))
    p = move_promo(m)
    if p:
        s += " nbrqk"[p]
    return s


# ----- Zobrist keys (deterministic) ---------------------------------------

_rng = random.Random(0xC0FFEE)
ZOBRIST_PIECE = [[_rng.getrandbits(64) for _ in range(128)] for _ in range(15)]
ZOBRIST_SIDE = _rng.getrandbits(64)
ZOBRIST_CASTLE = [_rng.getrandbits(64) for _ in range(16)]
ZOBRIST_EP = [_rng.getrandbits(64) for _ in range(8)]  # by file


class Board:
    __slots__ = ("squares", "side", "castling", "ep", "halfmove", "fullmove",
                 "king_sq", "zobrist", "_undo", "_hist")

    def __init__(self):
        self.squares = [EMPTY] * 128
        self.side = WHITE
        self.castling = 0
        self.ep = -1          # en-passant target square, or -1
        self.halfmove = 0
        self.fullmove = 1
        self.king_sq = [-1, -1]
        self.zobrist = 0
        self._undo = []
        self._hist = []       # zobrist history for repetition detection

    # ----- FEN ------------------------------------------------------------
    @classmethod
    def from_fen(cls, fen):
        b = cls()
        parts = fen.strip().split()
        if len(parts) < 4:
            raise ValueError("FEN needs at least 4 fields")
        placement, side, castling, ep = parts[0], parts[1], parts[2], parts[3]
        half = parts[4] if len(parts) > 4 else "0"
        full = parts[5] if len(parts) > 5 else "1"

        ranks = placement.split("/")
        if len(ranks) != 8:
            raise ValueError("FEN must have 8 ranks")
        king_count = [0, 0]
        for ri, row in enumerate(ranks):
            rank = 7 - ri
            file = 0
            for ch in row:
                if ch.isdigit():
                    file += int(ch)
                elif ch.lower() in "pnbrqk":
                    color = WHITE if ch.isupper() else BLACK
                    pt = " pnbrqk".index(ch.lower())
                    if file > 7:
                        raise ValueError(f"rank '{row}' overflows 8 files")
                    sq = sq_index(file, rank)
                    pc = make_piece(color, pt)
                    b.squares[sq] = pc
                    if pt == KING:
                        b.king_sq[color] = sq
                        king_count[color] += 1
                    file += 1
                else:
                    raise ValueError(f"illegal piece char {ch!r} in FEN")
            if file != 8:
                raise ValueError(f"rank '{row}' does not sum to 8 files")
        if king_count != [1, 1]:
            raise ValueError(
                f"FEN must have exactly one king per side, got "
                f"{king_count[WHITE]} white / {king_count[BLACK]} black")
        if side not in ("w", "b"):
            raise ValueError(f"side to move must be 'w' or 'b', got {side!r}")

        b.side = WHITE if side == "w" else BLACK
        b.castling = 0
        if "K" in castling:
            b.castling |= CR_WK
        if "Q" in castling:
            b.castling |= CR_WQ
        if "k" in castling:
            b.castling |= CR_BK
        if "q" in castling:
            b.castling |= CR_BQ
        b.ep = parse_square(ep) if ep != "-" else -1
        b.halfmove = int(half)
        b.fullmove = int(full)
        b.zobrist = b._compute_zobrist()
        b._hist = [b.zobrist]
        return b

    @classmethod
    def startpos(cls):
        return cls.from_fen(
            "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1")

    def to_fen(self):
        rows = []
        for ri in range(8):
            rank = 7 - ri
            row = ""
            empty = 0
            for file in range(8):
                pc = self.squares[sq_index(file, rank)]
                if pc == EMPTY:
                    empty += 1
                else:
                    if empty:
                        row += str(empty)
                        empty = 0
                    letter = PIECE_LETTERS[piece_type(pc)]
                    row += letter if piece_color(pc) == WHITE else letter.lower()
            if empty:
                row += str(empty)
            rows.append(row)
        placement = "/".join(rows)
        side = "w" if self.side == WHITE else "b"
        cr = ""
        if self.castling & CR_WK:
            cr += "K"
        if self.castling & CR_WQ:
            cr += "Q"
        if self.castling & CR_BK:
            cr += "k"
        if self.castling & CR_BQ:
            cr += "q"
        cr = cr or "-"
        ep = sq_name(self.ep) if self.ep >= 0 else "-"
        return f"{placement} {side} {cr} {ep} {self.halfmove} {self.fullmove}"

    # ----- Zobrist --------------------------------------------------------
    def _compute_zobrist(self):
        z = 0
        for sq in range(128):
            if sq & 0x88:
                continue
            pc = self.squares[sq]
            if pc:
                z ^= ZOBRIST_PIECE[pc][sq]
        if self.side == BLACK:
            z ^= ZOBRIST_SIDE
        z ^= ZOBRIST_CASTLE[self.castling]
        if self.ep >= 0:
            z ^= ZOBRIST_EP[sq_file(self.ep)]
        return z

    # ----- make / unmake --------------------------------------------------
    def make(self, m):
        frm, to = move_from(m), move_to(m)
        flag = move_flag(m)
        promo = move_promo(m)
        pc = self.squares[frm]
        color = self.side
        captured = self.squares[to]

        # save undo record
        self._undo.append((m, captured, self.castling, self.ep,
                           self.halfmove, self.zobrist))

        z = self.zobrist
        z ^= ZOBRIST_CASTLE[self.castling]
        if self.ep >= 0:
            z ^= ZOBRIST_EP[sq_file(self.ep)]

        # reset ep; will set again on double push
        new_ep = -1

        # halfmove clock
        if piece_type(pc) == PAWN or captured != EMPTY or flag == F_EP:
            self.halfmove = 0
        else:
            self.halfmove += 1

        # remove moving piece from origin
        z ^= ZOBRIST_PIECE[pc][frm]
        self.squares[frm] = EMPTY

        # handle captures (normal capture handled by overwriting 'to')
        if flag == F_EP:
            cap_sq = to + (S if color == WHITE else N)
            cap_pc = self.squares[cap_sq]
            z ^= ZOBRIST_PIECE[cap_pc][cap_sq]
            self.squares[cap_sq] = EMPTY
        elif captured != EMPTY:
            z ^= ZOBRIST_PIECE[captured][to]

        # place piece (with promotion)
        if promo:
            new_pc = make_piece(color, promo)
        else:
            new_pc = pc
        z ^= ZOBRIST_PIECE[new_pc][to]
        self.squares[to] = new_pc

        if piece_type(pc) == KING:
            self.king_sq[color] = to

        # castling rook move
        if flag == F_CASTLE:
            if to == frm + 2 * E:            # king-side
                rook_from, rook_to = frm + 3 * E, frm + E
            else:                            # queen-side
                rook_from, rook_to = frm + 4 * W, frm + W
            rk = self.squares[rook_from]
            z ^= ZOBRIST_PIECE[rk][rook_from]
            self.squares[rook_from] = EMPTY
            z ^= ZOBRIST_PIECE[rk][rook_to]
            self.squares[rook_to] = rk

        # double pawn push sets ep target
        if flag == F_DOUBLE:
            new_ep = (frm + to) // 2

        # update castling rights
        self.castling &= _CASTLE_MASK[frm] & _CASTLE_MASK[to]

        self.ep = new_ep
        z ^= ZOBRIST_CASTLE[self.castling]
        if self.ep >= 0:
            z ^= ZOBRIST_EP[sq_file(self.ep)]
        z ^= ZOBRIST_SIDE
        self.side ^= 1
        if self.side == WHITE:
            self.fullmove += 1
        self.zobrist = z
        self._hist.append(z)

    def unmake(self):
        m, captured, castling, ep, halfmove, zobrist = self._undo.pop()
        self._hist.pop()
        frm, to = move_from(m), move_to(m)
        flag = move_flag(m)
        promo = move_promo(m)

        self.side ^= 1
        if self.side == BLACK:
            self.fullmove -= 1
        color = self.side

        moved_pc = self.squares[to]
        # undo promotion
        if promo:
            moved_pc = make_piece(color, PAWN)
        self.squares[frm] = moved_pc
        self.squares[to] = EMPTY

        if piece_type(moved_pc) == KING:
            self.king_sq[color] = frm

        if flag == F_EP:
            cap_sq = to + (S if color == WHITE else N)
            self.squares[cap_sq] = make_piece(color ^ 1, PAWN)
        elif captured != EMPTY:
            self.squares[to] = captured

        if flag == F_CASTLE:
            if to == frm + 2 * E:
                rook_from, rook_to = frm + 3 * E, frm + E
            else:
                rook_from, rook_to = frm + 4 * W, frm + W
            self.squares[rook_from] = self.squares[rook_to]
            self.squares[rook_to] = EMPTY

        self.castling = castling
        self.ep = ep
        self.halfmove = halfmove
        self.zobrist = zobrist

    def make_null(self):
        """Make a null move (pass). Used by search null-move pruning."""
        self._undo.append((None, EMPTY, self.castling, self.ep,
                           self.halfmove, self.zobrist))
        z = self.zobrist
        if self.ep >= 0:
            z ^= ZOBRIST_EP[sq_file(self.ep)]
        self.ep = -1
        z ^= ZOBRIST_SIDE
        self.side ^= 1
        self.halfmove += 1
        self.zobrist = z
        self._hist.append(z)

    def unmake_null(self):
        m, captured, castling, ep, halfmove, zobrist = self._undo.pop()
        self._hist.pop()
        self.side ^= 1
        self.castling = castling
        self.ep = ep
        self.halfmove = halfmove
        self.zobrist = zobrist

    # ----- attack detection ----------------------------------------------
    def is_attacked(self, sq, by_color):
        """Is square `sq` attacked by any piece of color `by_color`?"""
        sqs = self.squares
        # pawn attacks: a pawn of by_color on sq-+ attacks sq
        if by_color == WHITE:
            for d in (-17, -15):  # white pawn sits SW/SE of target
                s = sq + d
                if on_board(s) and sqs[s] == make_piece(WHITE, PAWN):
                    return True
        else:
            for d in (17, 15):
                s = sq + d
                if on_board(s) and sqs[s] == make_piece(BLACK, PAWN):
                    return True
        # knights
        kn = make_piece(by_color, KNIGHT)
        for d in KNIGHT_DELTAS:
            s = sq + d
            if on_board(s) and sqs[s] == kn:
                return True
        # king
        kg = make_piece(by_color, KING)
        for d in KING_DIRS:
            s = sq + d
            if on_board(s) and sqs[s] == kg:
                return True
        # sliders: bishop/queen on diagonals, rook/queen on orthogonals
        bq = (make_piece(by_color, BISHOP), make_piece(by_color, QUEEN))
        for d in BISHOP_DIRS:
            s = sq + d
            while on_board(s):
                pc = sqs[s]
                if pc:
                    if pc in bq:
                        return True
                    break
                s += d
        rq = (make_piece(by_color, ROOK), make_piece(by_color, QUEEN))
        for d in ROOK_DIRS:
            s = sq + d
            while on_board(s):
                pc = sqs[s]
                if pc:
                    if pc in rq:
                        return True
                    break
                s += d
        return False

    def in_check(self, color=None):
        if color is None:
            color = self.side
        return self.is_attacked(self.king_sq[color], color ^ 1)

    def is_repetition(self, count=2):
        """True if current position has appeared `count` times in history
        (including now). count=2 detects a single repeat; threefold is 3."""
        z = self.zobrist
        seen = 0
        # only positions since the last irreversible move matter, but scanning
        # the bounded halfmove window is sufficient and simple.
        lookback = min(len(self._hist), self.halfmove + 1)
        for i in range(len(self._hist) - 1, len(self._hist) - 1 - lookback, -1):
            if self._hist[i] == z:
                seen += 1
                if seen >= count:
                    return True
        return False

    def __str__(self):
        out = []
        for ri in range(8):
            rank = 7 - ri
            row = []
            for file in range(8):
                pc = self.squares[sq_index(file, rank)]
                if pc == EMPTY:
                    row.append(".")
                else:
                    letter = PIECE_LETTERS[piece_type(pc)]
                    row.append(letter if piece_color(pc) == WHITE
                               else letter.lower())
            out.append(f"{rank+1} " + " ".join(row))
        out.append("  a b c d e f g h")
        return "\n".join(out)


# Castling-rights mask: moving from/to a square clears the relevant rights.
_CASTLE_MASK = [0xF] * 128
_CASTLE_MASK[sq_index(4, 0)] = ~(CR_WK | CR_WQ) & 0xF   # e1 king
_CASTLE_MASK[sq_index(0, 0)] = ~CR_WQ & 0xF             # a1 rook
_CASTLE_MASK[sq_index(7, 0)] = ~CR_WK & 0xF             # h1 rook
_CASTLE_MASK[sq_index(4, 7)] = ~(CR_BK | CR_BQ) & 0xF   # e8 king
_CASTLE_MASK[sq_index(0, 7)] = ~CR_BQ & 0xF             # a8 rook
_CASTLE_MASK[sq_index(7, 7)] = ~CR_BK & 0xF             # h8 rook
