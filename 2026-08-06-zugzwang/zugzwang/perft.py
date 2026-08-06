"""Perft: the standard move-generator correctness harness.

perft(board, depth) counts leaf nodes of the full legal game tree at
`depth` plies. The result either matches published reference values
exactly, or the move generator has a bug -- there is no partial credit,
which is exactly what makes it a good verification tool.
"""

from .movegen import generate_legal_moves


def perft(board, depth):
    if depth == 0:
        return 1
    total = 0
    for move in generate_legal_moves(board):
        u = board.make_move(move)
        total += perft(board, depth - 1)
        board.unmake_move(move, u)
    return total


def perft_divide(board, depth):
    """Returns {move_uci: subtree_count} -- useful for diffing against a
    reference engine to localize exactly which branch has a bug."""
    result = {}
    for move in generate_legal_moves(board):
        u = board.make_move(move)
        result[move.uci()] = perft(board, depth - 1)
        board.unmake_move(move, u)
    return result
