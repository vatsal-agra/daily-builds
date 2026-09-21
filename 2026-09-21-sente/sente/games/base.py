"""Abstract Game interface that MCTS, self-play, and evaluation all operate over.

A "state" is any hashable, immutable object a concrete game chooses (Sente's
two games both use tuples so states can be dict/set keys directly, which
matters for the minimax oracle's memoization and for MCTS node lookup).

Every concrete game is a *stateless* collection of classmethods/staticmethods
operating on states passed in explicitly -- there is no mutable game object,
which sidesteps an entire class of "MCTS tree reuse corrupts shared state"
bugs by construction (see REVIEW.md for the ones that still had to be found).
"""

from __future__ import annotations

from typing import List, Sequence, Tuple, Optional
import numpy as np


class Game:
    """Interface. Concrete games subclass this and implement every method.

    Convention used throughout Sente: `winner(state)` and `encode(state)`
    and the value target stored in the replay buffer are always expressed
    from the perspective of **the player to move at that state**, i.e. "+1
    means the player about to move at this state eventually wins". This is
    the single convention that the whole codebase (MCTS backup, training
    targets, evaluation) is built around, so it gets one comment here and
    is then relied on everywhere else without re-explaining it.
    """

    name: str = "abstract"
    action_size: int = 0
    # Shape of the encoded board input fed to the neural network.
    input_dim: int = 0

    @classmethod
    def initial_state(cls):
        raise NotImplementedError

    @classmethod
    def current_player(cls, state) -> int:
        """Returns +1 or -1: whose turn it is to move at `state`."""
        raise NotImplementedError

    @classmethod
    def legal_moves(cls, state) -> List[int]:
        """List of legal action ids at `state`. Empty iff state is terminal."""
        raise NotImplementedError

    @classmethod
    def apply_move(cls, state, action: int):
        """Returns the new state after `action` is applied at `state`."""
        raise NotImplementedError

    @classmethod
    def is_terminal(cls, state) -> bool:
        raise NotImplementedError

    @classmethod
    def winner(cls, state) -> Optional[int]:
        """+1 if the player who moved *last* (i.e. NOT current_player) won,
        -1 if current-player-to-have-just-moved lost (impossible in
        practice for these two games since a move can only make the mover
        win or draw, never make the mover lose), 0 for a draw, or None if
        the game (state) is not terminal.

        Concrete games return the actual result of the game: +1 means
        player +1 (as tracked by an absolute, fixed player id) won, -1
        means player -1 won, 0 means draw. `outcome_for(state, player)`
        below is the helper that converts this into the perspective-
        relative value Sente uses everywhere else.
        """
        raise NotImplementedError

    @classmethod
    def outcome_for(cls, state, player: int) -> float:
        """+1/-1/0 outcome of a terminal `state` from the perspective of
        `player` (an absolute +1/-1 player id, not "player to move")."""
        w = cls.winner(state)
        if w is None:
            raise ValueError("outcome_for called on non-terminal state")
        if w == 0:
            return 0.0
        return 1.0 if w == player else -1.0

    @classmethod
    def encode(cls, state) -> np.ndarray:
        """Canonical NN input encoding, always from the perspective of the
        player to move (so the network only ever has to reason about "my
        pieces vs opponent pieces", never about absolute player identity).
        Returns a 1-D float32 array of length `cls.input_dim`.
        """
        raise NotImplementedError

    @classmethod
    def legal_mask(cls, state) -> np.ndarray:
        """Boolean array of length `action_size`, True at legal actions."""
        mask = np.zeros(cls.action_size, dtype=bool)
        for a in cls.legal_moves(state):
            mask[a] = True
        return mask

    @classmethod
    def symmetries(cls, state, policy: np.ndarray) -> List[Tuple]:
        """Returns a list of (equivalent_state, transformed_policy) pairs
        (including the identity) used for training-data augmentation.
        Default: identity only. Concrete games may override with real
        board symmetries (Sente's Tic-Tac-Toe does).
        """
        return [(state, policy)]

    @classmethod
    def render(cls, state) -> str:
        raise NotImplementedError
