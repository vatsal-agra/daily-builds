"""Zobrist hashing: an incremental-friendly position hash used for the
transposition table and threefold-repetition detection.

Keys are generated from a fixed seed so hashes are reproducible run to run
(useful for tests), via Python's stdlib `random` with a local Random
instance -- this never touches the global random state.
"""

import random

from .board import sq, file_of, rank_of

PIECES = "PNBRQKpnbrqk"
_rng = random.Random(0xC0FFEE)

PIECE_SQUARE_KEYS = {p: [_rng.getrandbits(64) for _ in range(64)] for p in PIECES}
CASTLING_KEYS = {c: _rng.getrandbits(64) for c in "KQkq"}
EP_FILE_KEYS = [_rng.getrandbits(64) for _ in range(8)]
SIDE_KEY = _rng.getrandbits(64)


def hash_board(board):
    h = 0
    for square, piece in enumerate(board.squares):
        if piece != ".":
            h ^= PIECE_SQUARE_KEYS[piece][square]
    for c in board.castling:
        h ^= CASTLING_KEYS[c]
    if board.ep_square is not None:
        h ^= EP_FILE_KEYS[file_of(board.ep_square)]
    if board.to_move == "b":
        h ^= SIDE_KEY
    return h
