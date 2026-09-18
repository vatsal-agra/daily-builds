"""Cliff Walking: the classic Sutton & Barto (Example 6.6) gridworld MDP.

A 4-row x 12-col grid. The agent starts at the bottom-left corner and must
reach the bottom-right corner. Every step costs -1. The entire bottom row
between start and goal (exclusive) is a cliff: stepping onto it costs -100
and instantly teleports the agent back to the start (the episode does NOT
end). Reaching the goal ends the episode.

This is deliberately implemented as an *explicit* finite MDP (every
(state, action) -> (next_state, reward, done) is a pure function with no
hidden randomness) so bellman/dp.py can solve it exactly with dynamic
programming and use that exact solution as a ground-truth oracle for the
learned (TD) methods in bellman/td.py.
"""

ROWS = 4
COLS = 12

UP, DOWN, LEFT, RIGHT = 0, 1, 2, 3
ACTIONS = (UP, DOWN, LEFT, RIGHT)
ACTION_NAMES = {UP: "up", DOWN: "down", LEFT: "left", RIGHT: "right"}
ACTION_ARROWS = {UP: "↑", DOWN: "↓", LEFT: "←", RIGHT: "→"}

START = (ROWS - 1, 0)
GOAL = (ROWS - 1, COLS - 1)


def is_cliff(row, col):
    return row == ROWS - 1 and 0 < col < COLS - 1


def to_state(row, col):
    return row * COLS + col


def to_rc(state):
    return divmod(state, COLS)


class CliffWalking:
    """A deterministic, episodic, finite MDP.

    States are integers 0..ROWS*COLS-1 (row-major (row, col)). The goal
    state is terminal: no action taken from it has any effect, so it is
    excluded from `states` (an agent never needs to choose an action there).
    """

    def __init__(self):
        self.n_states = ROWS * COLS
        self.n_actions = len(ACTIONS)
        self.start_state = to_state(*START)
        self.goal_state = to_state(*GOAL)
        # states an agent can actually be asked to act from (excludes goal)
        self.states = [s for s in range(self.n_states) if s != self.goal_state]

    def step(self, state, action):
        """Return (next_state, reward, done) for taking `action` in `state`."""
        row, col = to_rc(state)
        if (row, col) == GOAL:
            return state, 0.0, True

        if action == UP:
            row = max(0, row - 1)
        elif action == DOWN:
            row = min(ROWS - 1, row + 1)
        elif action == LEFT:
            col = max(0, col - 1)
        elif action == RIGHT:
            col = min(COLS - 1, col + 1)
        else:
            raise ValueError(f"invalid action {action!r}")

        if is_cliff(row, col):
            return self.start_state, -100.0, False
        if (row, col) == GOAL:
            return to_state(row, col), -1.0, True
        return to_state(row, col), -1.0, False

    def reset(self):
        return self.start_state

    def is_terminal(self, state):
        return state == self.goal_state
