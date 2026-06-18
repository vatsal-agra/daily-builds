"""perft: count leaf nodes of the move tree to a fixed depth.

This is the correctness gate for move generation. Published reference values
exist for standard positions; matching them exactly proves the rules are right.
"""

from .board import move_uci
from .movegen import gen_legal


def perft(board, depth):
    if depth == 0:
        return 1
    if depth == 1:
        return len(gen_legal(board))
    nodes = 0
    for m in gen_legal(board):
        board.make(m)
        nodes += perft(board, depth - 1)
        board.unmake()
    return nodes


def perft_divide(board, depth):
    """Return {uci_move: subtree_count} for the root moves (debugging tool)."""
    result = {}
    for m in gen_legal(board):
        board.make(m)
        result[move_uci(m)] = perft(board, depth - 1)
        board.unmake()
    return dict(sorted(result.items()))


# Standard reference suite (Chess Programming Wiki perft results).
# Each entry: (name, fen, [counts indexed by depth starting at depth 1]).
REFERENCE = [
    ("startpos",
     "rnbqkbnr/pppppppp/8/8/8/8/PPPPPPPP/RNBQKBNR w KQkq - 0 1",
     [20, 400, 8902, 197281, 4865609]),
    ("kiwipete",
     "r3k2r/p1ppqpb1/bn2pnp1/3PN3/1p2P3/2N2Q1p/PPPBBPPP/R3K2R w KQkq - 0 1",
     [48, 2039, 97862, 4085603]),
    ("position3",
     "8/2p5/3p4/KP5r/1R3p1k/8/4P1P1/8 w - - 0 1",
     [14, 191, 2812, 43238, 674624]),
    ("position4",
     "r3k2r/Pppp1ppp/1b3nbN/nP6/BBP1P3/q4N2/Pp1P2PP/R2Q1RK1 w kq - 0 1",
     [6, 264, 9467, 422333]),
    ("position5",
     "rnbq1k1r/pp1Pbppp/2p5/8/2B5/8/PPP1NnPP/RNBQK2R w KQ - 1 8",
     [44, 1486, 62379, 2103487]),
]
