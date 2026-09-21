"""An independent, from-scratch, exhaustive minimax oracle for
Tic-Tac-Toe. Shares no code with the neural network or MCTS -- this is
the ground truth Sente's "never loses to perfect play" claim is checked
against, in the spirit of Gambit's perft counts or Quantum's Belady's-MIN
oracle.

Tic-Tac-Toe has at most 5478 reachable legal board states, so full
minimax with memoization is exact and instant (no pruning needed, though
alpha-beta would work identically).
"""

from __future__ import annotations
from functools import lru_cache
from typing import List, Tuple

from .games.tictactoe import TicTacToe as G


@lru_cache(maxsize=None)
def minimax_value(state) -> int:
    """Exact game-theoretic value of `state` from the perspective of the
    player to move at `state`: +1 = that player can force a win, -1 =
    that player will lose against best play, 0 = best play draws."""
    w = G.winner(state)
    if w is not None:
        # w is the absolute winner (+1/-1/0). Convert to "value for the
        # player to move at this (terminal) state" -- for a terminal
        # state this is only used for consistency with the recursion
        # below and is never really "the mover's" outcome since the game
        # is already over, but it must equal outcome_for(state, cur).
        cur = G.current_player(state)
        return int(G.outcome_for(state, cur))
    best = -2
    for a in G.legal_moves(state):
        child = G.apply_move(state, a)
        # child's value is from the perspective of the player to move at
        # child, i.e. the opponent -- negate to get value for us.
        v = -minimax_value(child)
        if v > best:
            best = v
    return best


def best_moves(state) -> List[int]:
    """All actions achieving the game-theoretic optimum from `state`
    (there can be several equally-optimal moves -- the "never loses to
    perfect play" check must branch over ALL of them, not just one, to
    honestly test "perfect play" rather than "one particular perfect
    opponent's habits")."""
    if G.is_terminal(state):
        return []
    val = minimax_value(state)
    moves = []
    for a in G.legal_moves(state):
        child = G.apply_move(state, a)
        if -minimax_value(child) == val:
            moves.append(a)
    return moves


def optimal_value_and_moves(state) -> Tuple[int, List[int]]:
    return minimax_value(state), best_moves(state)


def warm_cache():
    """Forces the memo table to be populated for every reachable state
    from the empty board, and returns the count of distinct reachable
    legal states (a sanity number worth reporting: Tic-Tac-Toe has 5478
    of them)."""
    seen = set()

    def rec(state):
        if state in seen:
            return
        seen.add(state)
        minimax_value(state)
        if G.is_terminal(state):
            return
        for a in G.legal_moves(state):
            rec(G.apply_move(state, a))

    rec(G.initial_state())
    return len(seen)
