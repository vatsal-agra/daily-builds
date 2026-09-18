"""TD(0) self-play value learning for Tic-Tac-Toe (Sutton & Barto section
1.5's original worked example, generalized to a draw-aware value target).

A single shared table V(s) estimates "the probability that X eventually
wins from board s", learned purely by playing complete games against
itself with no minimax search and no hand-coded strategy. X plays greedily
by moving to the successor board with the highest V; O plays greedily by
moving to the successor board with the *lowest* V (since a low X-win
probability is good for O). Both sides explore with probability `epsilon`
by moving to a uniformly random legal successor instead.

The learning signal is a same-player TD(0) chain: for a player's own
consecutive "afterstates" s_t -> s_{t+1} (its board right after this move,
then its board right after its *next* move, skipping over the opponent's
intervening move), the update is

    V(s_t) <- V(s_t) + alpha * (V(s_{t+1}) - V(s_t))

exactly like updating any other value function toward a bootstrapped
successor estimate, except the "step" here is one full round-trip through
the opponent's move rather than one environment tick. Only *greedy* moves
are backed up (per Sutton's original recipe) so the learned V approximates
the value of the greedy policy rather than being distorted by the
exploratory moves that were only taken to gather information. When the
game ends, whichever player did not make the final move gets one last
backup from their own last afterstate to the true terminal outcome, since
they have no further move of their own to trigger it.
"""
import random

from .envs.tictactoe import (
    apply_move, available_actions, is_terminal, other_player, winner,
)


def terminal_value(board):
    """Fixed value of a terminal board, from X's win-probability perspective."""
    w = winner(board)
    if w == "X":
        return 1.0
    if w == "O":
        return 0.0
    return 0.5  # draw


class SelfPlayAgent:
    def __init__(self, alpha=0.2, epsilon=0.1, seed=0):
        self.alpha = alpha
        self.epsilon = epsilon
        self.rng = random.Random(seed)
        self.V = {}

    def value(self, board):
        v = self.V.get(board)
        if v is None:
            v = terminal_value(board) if is_terminal(board) else 0.5
            self.V[board] = v
        return v

    def choose_move(self, board, player):
        actions = available_actions(board)
        if self.rng.random() < self.epsilon:
            return self.rng.choice(actions), True
        best_value = None
        tied_actions = []
        for action in actions:
            child = apply_move(board, action, player)
            v = self.value(child)
            better = (
                best_value is None
                or (player == "X" and v > best_value)
                or (player == "O" and v < best_value)
            )
            if better:
                best_value = v
                tied_actions = [action]
            elif v == best_value:
                tied_actions.append(action)
        return self.rng.choice(tied_actions), False

    def _backup(self, prev_state, new_state):
        self.V[prev_state] = self.value(prev_state) + self.alpha * (
            self.value(new_state) - self.value(prev_state)
        )

    def train_episode(self):
        board = tuple(" " * 9)
        player = "X"
        last_own_state = {"X": None, "O": None}
        while True:
            action, explored = self.choose_move(board, player)
            new_board = apply_move(board, action, player)

            if not explored and last_own_state[player] is not None:
                self._backup(last_own_state[player], new_board)
            last_own_state[player] = new_board

            board = new_board
            if is_terminal(board):
                mover = player
                other = other_player(mover)
                prev_other = last_own_state[other]
                if prev_other is not None:
                    self._backup(prev_other, board)
                return board
            player = other_player(player)

    def train(self, episodes):
        outcomes = {"X": 0, "O": 0, "draw": 0}
        for _ in range(episodes):
            final_board = self.train_episode()
            w = winner(final_board)
            outcomes["draw" if w is None else w] += 1
        return outcomes

    def choose_move_greedy(self, board, player):
        old_epsilon = self.epsilon
        self.epsilon = 0.0
        try:
            return self.choose_move(board, player)
        finally:
            self.epsilon = old_epsilon
