"""A tabular GridWorld MDP, plus the classic Cliff Walking variant.

State is encoded as a single integer ``row * width + col`` so tabular
agents can index a flat Q-table/array directly. Transitions are
deterministic, which keeps the environment small enough to solve exactly
with value iteration (bellman.value_iteration) — the ground truth every
learned agent gets checked against.

Actions: 0=up, 1=right, 2=down, 3=left. Moving into a wall or off the grid
edge leaves the agent in place (still costs a step).
"""

from __future__ import annotations

ACTIONS = (0, 1, 2, 3)  # up, right, down, left
ACTION_NAMES = ("up", "right", "down", "left")
_DELTA = {0: (-1, 0), 1: (0, 1), 2: (1, 0), 3: (0, -1)}


class GridWorld:
    """A rectangular grid MDP with walls, a goal, and optional 'cliff' cells."""

    def __init__(
        self,
        width,
        height,
        start,
        goal,
        walls=frozenset(),
        cliffs=frozenset(),
        step_reward=-1.0,
        goal_reward=0.0,
        cliff_reward=-100.0,
        cliff_terminates=False,
        max_steps=200,
    ):
        if not (0 <= start[0] < height and 0 <= start[1] < width):
            raise ValueError("start out of bounds")
        if not (0 <= goal[0] < height and 0 <= goal[1] < width):
            raise ValueError("goal out of bounds")
        if start in walls or goal in walls:
            raise ValueError("start/goal cannot be a wall cell")
        if start in cliffs or goal in cliffs:
            raise ValueError("start/goal cannot be a cliff cell")

        self.width = width
        self.height = height
        self.start_rc = tuple(start)
        self.goal_rc = tuple(goal)
        self.walls = frozenset(walls)
        self.cliffs = frozenset(cliffs)
        self.step_reward = step_reward
        self.goal_reward = goal_reward
        self.cliff_reward = cliff_reward
        self.cliff_terminates = cliff_terminates
        self.max_steps = max_steps

        self.n_states = width * height
        self.n_actions = len(ACTIONS)
        self._rc = self.start_rc
        self._t = 0

    # -- state <-> (row, col) encoding -----------------------------------
    def rc_to_state(self, rc):
        r, c = rc
        return r * self.width + c

    def state_to_rc(self, state):
        return divmod(state, self.width)

    def all_states(self):
        return [
            self.rc_to_state((r, c))
            for r in range(self.height)
            for c in range(self.width)
            if (r, c) not in self.walls
        ]

    def is_terminal(self, state):
        rc = self.state_to_rc(state)
        return rc == self.goal_rc

    # -- deterministic model, used by value iteration ---------------------
    def transition(self, state, action):
        """Pure function: (state, action) -> (next_state, reward, done).

        Does not mutate environment/episode state — used by value
        iteration to solve the exact MDP, and by the environment's own
        step() below so the two never drift apart.
        """
        rc = self.state_to_rc(state)
        if rc == self.goal_rc:
            # Absorbing: taking any action from the goal stays put, no reward.
            return state, 0.0, True

        dr, dc = _DELTA[action]
        nr, nc = rc[0] + dr, rc[1] + dc
        if not (0 <= nr < self.height and 0 <= nc < self.width) or (nr, nc) in self.walls:
            nr, nc = rc  # bump into wall/edge: no movement

        if (nr, nc) in self.cliffs:
            next_rc = self.start_rc if not self.cliff_terminates else (nr, nc)
            done = self.cliff_terminates
            return self.rc_to_state(next_rc), self.cliff_reward, done

        if (nr, nc) == self.goal_rc:
            return self.rc_to_state((nr, nc)), self.goal_reward, True

        return self.rc_to_state((nr, nc)), self.step_reward, False

    # -- stateful episode API, used by agents ------------------------------
    def reset(self):
        self._rc = self.start_rc
        self._t = 0
        return self.rc_to_state(self._rc)

    def step(self, action):
        if action not in ACTIONS:
            raise ValueError(f"invalid action {action!r}")
        state = self.rc_to_state(self._rc)
        next_state, reward, done = self.transition(state, action)
        self._rc = self.state_to_rc(next_state)
        self._t += 1
        truncated = self._t >= self.max_steps
        info = {"truncated": truncated}
        return next_state, reward, (done or truncated), info

    def render_ascii(self, agent_rc=None):
        agent_rc = agent_rc if agent_rc is not None else self._rc
        rows = []
        for r in range(self.height):
            row = []
            for c in range(self.width):
                cell = (r, c)
                if cell == agent_rc:
                    row.append("A")
                elif cell == self.goal_rc:
                    row.append("G")
                elif cell in self.cliffs:
                    row.append("C")
                elif cell in self.walls:
                    row.append("#")
                else:
                    row.append(".")
            rows.append("".join(row))
        return "\n".join(rows)


def make_simple_grid():
    """A small 5x5 grid with a couple of interior walls — the default
    GridWorld used to verify Q-learning/SARSA against value iteration."""
    walls = {(1, 1), (1, 2), (1, 3), (3, 1)}
    return GridWorld(
        width=5,
        height=5,
        start=(4, 0),
        goal=(0, 4),
        walls=walls,
        step_reward=-1.0,
        goal_reward=0.0,
        max_steps=100,
    )


def make_cliff_walking():
    """The classic Cliff Walking task (Sutton & Barto, Example 6.6):
    a 4x12 grid, start at bottom-left, goal at bottom-right, and the
    entire bottom row in between is a cliff that costs -100 and sends the
    agent back to start without ending the episode. Off-policy Q-learning
    converges to the optimal (risky, cliff-hugging) path; on-policy SARSA
    converges to a safer path one row up.
    """
    height, width = 4, 12
    cliffs = {(height - 1, c) for c in range(1, width - 1)}
    return GridWorld(
        width=width,
        height=height,
        start=(height - 1, 0),
        goal=(height - 1, width - 1),
        cliffs=cliffs,
        step_reward=-1.0,
        goal_reward=-1.0,
        cliff_reward=-100.0,
        cliff_terminates=False,
        max_steps=200,
    )
