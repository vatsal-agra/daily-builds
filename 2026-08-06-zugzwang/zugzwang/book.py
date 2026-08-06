"""A small curated opening book (stretch feature #7).

Lines are stored as SAN move sequences. `OpeningBook.lookup` finds every
book line consistent with the moves played so far in the current game and
returns a legal `Move` for a randomly chosen matching continuation, so the
engine doesn't burn search time reinventing well-known opening theory --
once the game leaves the book, `lookup` returns None and the search engine
takes over.
"""

import random

OPENING_LINES = [
    # Italian Game
    "e4 e5 Nf3 Nc6 Bc4 Bc5 c3 Nf6 d3 O-O".split(),
    "e4 e5 Nf3 Nc6 Bc4 Bc5 O-O Nf6 d3 d6".split(),
    # Ruy Lopez
    "e4 e5 Nf3 Nc6 Bb5 a6 Ba4 Nf6 O-O Be7 Re1 b5 Bb3 d6".split(),
    "e4 e5 Nf3 Nc6 Bb5 Nf6 O-O Nxe4 d4 Nd6 Bxc6 dxc6".split(),
    # Sicilian Defense
    "e4 c5 Nf3 d6 d4 cxd4 Nxd4 Nf6 Nc3 a6".split(),
    "e4 c5 Nf3 Nc6 d4 cxd4 Nxd4 Nf6 Nc3 e5".split(),
    "e4 c5 Nc3 Nc6 g3 g6 Bg2 Bg7 d3 d6".split(),
    # French Defense
    "e4 e6 d4 d5 Nc3 Bb4 e5 c5 a3 Bxc3+ bxc3".split(),
    # Caro-Kann
    "e4 c6 d4 d5 Nc3 dxe4 Nxe4 Bf5 Ng3 Bg6".split(),
    # Queen's Gambit
    "d4 d5 c4 e6 Nc3 Nf6 Bg5 Be7 e3 O-O".split(),
    "d4 d5 c4 c6 Nf3 Nf6 Nc3 dxc4 a4 Bf5".split(),
    "d4 d5 c4 dxc4 Nf3 Nf6 e3 e6 Bxc4 c5".split(),
    # Nimzo/Queen's Indian family
    "d4 Nf6 c4 e6 Nc3 Bb4 e3 O-O Bd3 d5".split(),
    "d4 Nf6 c4 g6 Nc3 Bg7 e4 d6 Nf3 O-O".split(),
    # London System
    "d4 d5 Nf3 Nf6 Bf4 e6 e3 Bd6 Bg3 O-O".split(),
    # English Opening
    "c4 e5 Nc3 Nf6 Nf3 Nc6 g3 d5 cxd5 Nxd5".split(),
]


class OpeningBook:
    def __init__(self, lines=None):
        self.lines = lines if lines is not None else OPENING_LINES

    def lookup(self, board, played_sans):
        """played_sans: SAN moves played so far this game, in order.
        Returns a legal Move to play next, or None if out of book."""
        n = len(played_sans)
        candidates = [line for line in self.lines
                      if len(line) > n and line[:n] == played_sans]
        if not candidates:
            return None
        next_sans = list({line[n] for line in candidates})
        chosen = random.choice(next_sans)
        from .pgn import san_to_move
        try:
            return san_to_move(board, chosen)
        except ValueError:
            return None
