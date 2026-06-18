"""Perft: count leaf nodes of the move tree to a fixed depth.

Perft node counts are a published, exact oracle. Any move-generation bug
(missing castle, broken en passant, illegal pin escape) shifts a count.
"""

from __future__ import annotations

from .board import Board
from .movegen import legal_moves


def perft(board: Board, depth: int) -> int:
    if depth == 0:
        return 1
    moves = legal_moves(board)
    if depth == 1:
        return len(moves)
    total = 0
    for mv in moves:
        board.make_move(mv)
        total += perft(board, depth - 1)
        board.unmake_move()
    return total


def perft_divide(board: Board, depth: int) -> list:
    """Return [(uci, count), ...] for each root move; useful for debugging."""
    from .board import move_uci
    out = []
    for mv in legal_moves(board):
        board.make_move(mv)
        out.append((move_uci(mv), perft(board, depth - 1)))
        board.unmake_move()
    out.sort()
    return out


# Published perft positions: (name, fen, {depth: nodes})
PERFT_POSITIONS = [
    (
        "startpos",
        "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
        {1: 20, 2: 400, 3: 8902, 4: 197281, 5: 4865609},
    ),
    (
        "kiwipete",
        "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
        {1: 48, 2: 2039, 3: 97862, 4: 4085603},
    ),
    (
        "position3",
        "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
        {1: 14, 2: 191, 3: 2812, 4: 43238, 5: 674624},
    ),
    (
        "position4",
        "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
        {1: 6, 2: 264, 3: 9467, 4: 422333},
    ),
    (
        "position5",
        "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
        {1: 44, 2: 1486, 3: 62379, 4: 2103487},
    ),
]
