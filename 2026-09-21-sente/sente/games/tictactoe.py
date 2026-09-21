"""Tic-Tac-Toe (3x3), the game with the exhaustive minimax oracle.

State representation: a length-9 tuple of cell values in {0, +1, -1},
row-major (index = row*3 + col). Player +1 always moves first. Whose turn
it is is *derived* from the piece count (never stored separately), so a
board tuple alone is a complete, hashable, canonical key -- exactly what
the minimax oracle's memoization table needs.
"""

from __future__ import annotations
from typing import List, Optional, Tuple
import numpy as np

from .base import Game

_LINES = [
    (0, 1, 2), (3, 4, 5), (6, 7, 8),   # rows
    (0, 3, 6), (1, 4, 7), (2, 5, 8),   # cols
    (0, 4, 8), (2, 4, 6),              # diagonals
]

# The 8 symmetries of a square (dihedral group D4), expressed as a
# permutation of the 9 cell indices: new_cell[i] = old_cell[perm[i]].
def _grid_perm(fn):
    perm = [0] * 9
    for r in range(3):
        for c in range(3):
            nr, nc = fn(r, c)
            perm[nr * 3 + nc] = r * 3 + c
    return tuple(perm)

_SYM_PERMS = [
    _grid_perm(lambda r, c: (r, c)),                 # identity
    _grid_perm(lambda r, c: (c, 2 - r)),              # rotate 90
    _grid_perm(lambda r, c: (2 - r, 2 - c)),          # rotate 180
    _grid_perm(lambda r, c: (2 - c, r)),              # rotate 270
    _grid_perm(lambda r, c: (r, 2 - c)),              # mirror horizontal
    _grid_perm(lambda r, c: (2 - r, c)),              # mirror vertical
    _grid_perm(lambda r, c: (c, r)),                  # transpose
    _grid_perm(lambda r, c: (2 - c, 2 - r)),          # anti-transpose
]


class TicTacToe(Game):
    name = "tictactoe"
    action_size = 9
    input_dim = 18
    rows, cols = 3, 3

    @classmethod
    def initial_state(cls):
        return (0,) * 9

    @classmethod
    def current_player(cls, state) -> int:
        n = sum(1 for v in state if v != 0)
        return 1 if n % 2 == 0 else -1

    @classmethod
    def legal_moves(cls, state) -> List[int]:
        if cls.winner(state) is not None:
            return []
        return [i for i, v in enumerate(state) if v == 0]

    @classmethod
    def apply_move(cls, state, action: int):
        if state[action] != 0:
            raise ValueError(f"illegal move {action} on {state}")
        p = cls.current_player(state)
        new = list(state)
        new[action] = p
        return tuple(new)

    @classmethod
    def _raw_winner(cls, state) -> Optional[int]:
        for a, b, c in _LINES:
            if state[a] != 0 and state[a] == state[b] == state[c]:
                return state[a]
        return None

    @classmethod
    def is_terminal(cls, state) -> bool:
        return cls._raw_winner(state) is not None or all(v != 0 for v in state)

    @classmethod
    def winner(cls, state) -> Optional[int]:
        w = cls._raw_winner(state)
        if w is not None:
            return w
        if all(v != 0 for v in state):
            return 0
        return None

    @classmethod
    def encode(cls, state) -> np.ndarray:
        cur = cls.current_player(state)
        own = np.array([1.0 if v == cur else 0.0 for v in state], dtype=np.float32)
        opp = np.array([1.0 if v == -cur else 0.0 for v in state], dtype=np.float32)
        return np.concatenate([own, opp])

    @classmethod
    def symmetries(cls, state, policy: np.ndarray):
        out = []
        seen = set()
        for perm in _SYM_PERMS:
            new_state = tuple(state[perm[i]] for i in range(9))
            new_policy = np.array([policy[perm[i]] for i in range(9)], dtype=policy.dtype)
            key = new_state
            if key in seen:
                continue
            seen.add(key)
            out.append((new_state, new_policy))
        return out

    @classmethod
    def render(cls, state) -> str:
        sym = {0: ".", 1: "X", -1: "O"}
        rows = []
        for r in range(3):
            rows.append(" ".join(sym[state[r * 3 + c]] for c in range(3)))
        return "\n".join(rows)
