"""Connect Four Jr: a reduced Connect Four on a 5-column x 4-row board,
4-in-a-row to win. See PLAN.md/README.md for why this size was chosen
(full 7x6 is not tractable to train from scratch on a CPU-only sandbox
in this session's time budget).

State representation: a tuple of `cols` columns, each column itself a
tuple of piece values (+1/-1) from bottom to top -- length = number of
pieces dropped in that column so far. This makes "is column c full"
and "apply a drop" both O(1)-ish tuple operations, and (crucially) makes
the state itself a complete, hashable, immutable key with no separate
mutable board object anywhere -- so there is nothing for MCTS tree reuse
to accidentally alias or corrupt between moves (see REVIEW.md).
"""

from __future__ import annotations
from typing import List, Optional
import numpy as np

from .base import Game

ROWS = 4
COLS = 5
WIN_LEN = 4


class Connect4Jr(Game):
    name = "connect4jr"
    action_size = COLS
    input_dim = 2 * ROWS * COLS
    rows, cols = ROWS, COLS

    @classmethod
    def initial_state(cls):
        return tuple(() for _ in range(COLS))

    @classmethod
    def current_player(cls, state) -> int:
        n = sum(len(c) for c in state)
        return 1 if n % 2 == 0 else -1

    @classmethod
    def legal_moves(cls, state) -> List[int]:
        if cls._raw_winner(state) is not None:
            return []
        return [c for c in range(COLS) if len(state[c]) < ROWS]

    @classmethod
    def apply_move(cls, state, action: int):
        if len(state[action]) >= ROWS:
            raise ValueError(f"illegal move (column full) {action} on {state}")
        p = cls.current_player(state)
        new = list(state)
        new[action] = state[action] + (p,)
        return tuple(new)

    @classmethod
    def _grid(cls, state):
        """Dense ROWS x COLS int array, row 0 = bottom, 0 = empty."""
        g = np.zeros((ROWS, COLS), dtype=np.int8)
        for c in range(COLS):
            for r, v in enumerate(state[c]):
                g[r, c] = v
        return g

    @classmethod
    def _raw_winner(cls, state) -> Optional[int]:
        g = cls._grid(state)
        for r in range(ROWS):
            for c in range(COLS):
                v = g[r, c]
                if v == 0:
                    continue
                # 4 directions: right, up, up-right, up-left
                for dr, dc in ((0, 1), (1, 0), (1, 1), (1, -1)):
                    ok = True
                    for k in range(1, WIN_LEN):
                        rr, cc = r + dr * k, c + dc * k
                        if not (0 <= rr < ROWS and 0 <= cc < COLS) or g[rr, cc] != v:
                            ok = False
                            break
                    if ok:
                        return int(v)
        return None

    @classmethod
    def is_terminal(cls, state) -> bool:
        if cls._raw_winner(state) is not None:
            return True
        return all(len(c) >= ROWS for c in state)

    @classmethod
    def winner(cls, state) -> Optional[int]:
        w = cls._raw_winner(state)
        if w is not None:
            return w
        if all(len(c) >= ROWS for c in state):
            return 0
        return None

    @classmethod
    def encode(cls, state) -> np.ndarray:
        cur = cls.current_player(state)
        g = cls._grid(state)
        own = (g == cur).astype(np.float32).flatten()
        opp = (g == -cur).astype(np.float32).flatten()
        return np.concatenate([own, opp])

    @classmethod
    def symmetries(cls, state, policy: np.ndarray):
        mirrored_state = tuple(state[COLS - 1 - c] for c in range(COLS))
        mirrored_policy = np.array([policy[COLS - 1 - c] for c in range(COLS)], dtype=policy.dtype)
        out = [(state, policy)]
        if mirrored_state != state:
            out.append((mirrored_state, mirrored_policy))
        return out

    @classmethod
    def render(cls, state) -> str:
        sym = {0: ".", 1: "X", -1: "O"}
        g = cls._grid(state)
        lines = []
        for r in range(ROWS - 1, -1, -1):
            lines.append(" ".join(sym[int(g[r, c])] for c in range(COLS)))
        lines.append(" ".join(str(c) for c in range(COLS)))
        return "\n".join(lines)
