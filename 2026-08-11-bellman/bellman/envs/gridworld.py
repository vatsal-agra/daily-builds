"""From-scratch discrete MDP gridworld environments.

Every env here exposes the *full* transition model P(s'|s,a) -> (prob,
next_state, reward, done), not just a sampling step() function. That's
what lets bellman.agents.dp solve them exactly with value iteration, and
what lets bellman.agents.tabular's Q-learning/SARSA/Monte-Carlo agents be
checked for convergence against that exact answer.

Four named configurations of one underlying grid MDP:

  GridWorld      - a plain maze with walls and a goal. Deterministic.
  CliffWalking   - Sutton & Barto figure 6.13. Stepping onto a cliff cell
                   costs -100 and snaps back to start (episode continues).
  WindyGridworld - Sutton & Barto example 6.5. Certain columns push the
                   agent north by a fixed amount regardless of action.
  FrozenLake     - stochastic "slippery ice": the intended action only
                   happens with probability (1 - slip_prob); the rest of
                   the mass goes to the two perpendicular directions.
"""

UP, RIGHT, DOWN, LEFT = 0, 1, 2, 3
ACTIONS = (UP, RIGHT, DOWN, LEFT)
ACTION_NAMES = {UP: "up", RIGHT: "right", DOWN: "down", LEFT: "left"}
# (d_row, d_col) for each action
_DELTA = {UP: (-1, 0), RIGHT: (0, 1), DOWN: (1, 0), LEFT: (0, -1)}
# perpendicular actions, used for slip probability mass
_PERP = {UP: (LEFT, RIGHT), DOWN: (LEFT, RIGHT), LEFT: (UP, DOWN), RIGHT: (UP, DOWN)}


class GridWorld:
    """A configurable rectangular-grid MDP.

    grid: list of equal-length strings. Cell codes:
        '.' empty      'S' start (treated as empty otherwise)
        '#' wall (impassable, staying in place is the only outcome)
        'G' goal (terminal, +goal_reward)
        'H' hole (terminal, +hole_reward -- typically negative)
        'C' cliff (non-terminal, +cliff_reward, snaps back to start)
    """

    def __init__(
        self,
        grid,
        step_reward=-1.0,
        goal_reward=0.0,
        hole_reward=-1.0,
        cliff_reward=-100.0,
        wind=None,
        slip_prob=0.0,
        max_steps=200,
        name="GridWorld",
    ):
        self.name = name
        self.rows = [row for row in grid]
        if not self.rows:
            raise ValueError("grid must contain at least one row")
        self.n_rows = len(self.rows)
        self.n_cols = len(self.rows[0])
        for row in self.rows:
            if len(row) != self.n_cols:
                raise ValueError("all grid rows must have equal length")

        self.step_reward = step_reward
        self.goal_reward = goal_reward
        self.hole_reward = hole_reward
        self.cliff_reward = cliff_reward
        self.wind = wind or {}
        self.slip_prob = slip_prob
        self.max_steps = max_steps

        self.actions = list(ACTIONS)
        self.n_actions = len(self.actions)

        self.states = []
        self._rc_to_s = {}
        self.start_state = None
        self.walls = set()
        self.goals = set()
        self.holes = set()
        self.cliffs = set()

        for r, row in enumerate(self.rows):
            for c, ch in enumerate(row):
                s = len(self.states)
                self.states.append((r, c))
                self._rc_to_s[(r, c)] = s
                if ch == "#":
                    self.walls.add(s)
                elif ch == "G":
                    self.goals.add(s)
                elif ch == "H":
                    self.holes.add(s)
                elif ch == "C":
                    self.cliffs.add(s)
                elif ch == "S":
                    self.start_state = s
        if self.start_state is None:
            self.start_state = 0
        self.n_states = len(self.states)
        self._terminal = self.goals | self.holes

        self._cur = None
        self._t = 0

    # ---- MDP model, used by the DP oracle -----------------------------
    def is_terminal(self, s):
        return s in self._terminal

    def is_wall(self, s):
        return s in self.walls

    def rc(self, s):
        return self.states[s]

    def state_of(self, r, c):
        return self._rc_to_s.get((r, c))

    def _move(self, s, action):
        """One deterministic step of physics: walls block, edges block,
        wind (if any) is applied *after* the intentional move, cliff
        landings snap back to start. Returns (next_state, reward)."""
        r, c = self.states[s]
        dr, dc = _DELTA[action]
        nr, nc = r + dr, c + dc
        # wind pushes north (row decreases) by wind[c] cells, applied on
        # top of the chosen action, from the *original* column
        w = self.wind.get(c, 0)
        nr -= w
        nr = max(0, min(self.n_rows - 1, nr))
        nc = max(0, min(self.n_cols - 1, nc))
        ns = self._rc_to_s[(nr, nc)]
        if ns in self.walls:
            ns = s  # bump into wall -> stay
        if ns in self.cliffs:
            return self.start_state, self.cliff_reward
        if ns in self.goals:
            return ns, self.goal_reward
        if ns in self.holes:
            return ns, self.hole_reward
        return ns, self.step_reward

    def transitions(self, s, action):
        """Full model: list of (prob, next_state, reward, done).
        Terminal states have no outgoing transitions (self-loop, reward 0,
        done True) so DP can treat them uniformly."""
        if self.is_terminal(s):
            return [(1.0, s, 0.0, True)]
        if self.slip_prob <= 0.0:
            ns, r = self._move(s, action)
            return [(1.0, ns, r, self.is_terminal(ns))]
        outcomes = []
        intended_p = 1.0 - self.slip_prob
        ns, r = self._move(s, action)
        outcomes.append((intended_p, ns, r, self.is_terminal(ns)))
        each = self.slip_prob / 2.0
        for perp in _PERP[action]:
            ns2, r2 = self._move(s, perp)
            outcomes.append((each, ns2, r2, self.is_terminal(ns2)))
        return outcomes

    # ---- sampling interface, used by tabular/online agents -------------
    def reset(self):
        self._cur = self.start_state
        self._t = 0
        return self._cur

    def step(self, action):
        if self._cur is None:
            raise RuntimeError("call reset() before step()")
        self._t += 1
        outcomes = self.transitions(self._cur, action)
        if len(outcomes) == 1:
            _, ns, r, done = outcomes[0]
        else:
            probs = [o[0] for o in outcomes]
            ns, r, done = _weighted_choice(outcomes, probs)
        self._cur = ns
        truncated = self._t >= self.max_steps
        return ns, r, done, truncated

    def render_ascii(self, agent_state=None):
        lines = []
        for r, row in enumerate(self.rows):
            line = []
            for c, ch in enumerate(row):
                s = self._rc_to_s[(r, c)]
                if agent_state is not None and s == agent_state:
                    line.append("A")
                else:
                    line.append(ch)
            lines.append("".join(line))
        return "\n".join(lines)


def _weighted_choice(outcomes, probs):
    import random

    x = random.random()
    acc = 0.0
    for (p, ns, r, done), pr in zip(outcomes, probs):
        acc += pr
        if x <= acc:
            return ns, r, done
    p, ns, r, done = outcomes[-1]
    return ns, r, done


# ---- named factory configurations --------------------------------------

def make_gridworld():
    grid = [
        "S...",
        ".##.",
        "....",
        "..#G",
    ]
    return GridWorld(grid, step_reward=-1.0, goal_reward=10.0, name="GridWorld")


def make_cliff_walking():
    grid = [
        "......",
        "......",
        "......",
        "SCCCCG",
    ]
    return GridWorld(grid, step_reward=-1.0, goal_reward=0.0, cliff_reward=-100.0,
                      max_steps=200, name="CliffWalking")


def make_windy_gridworld():
    grid = [
        "..........",
        "..........",
        "..........",
        "S.........",
        "..........",
        "..........",
        ".........G",
        "..........",
        "..........",
        "..........",
    ]
    wind = {3: 1, 4: 1, 5: 1, 6: 2, 7: 2, 8: 1}
    return GridWorld(grid, step_reward=-1.0, goal_reward=0.0, wind=wind,
                      max_steps=200, name="WindyGridworld")


def make_frozen_lake():
    grid = [
        "S...",
        ".H.H",
        "...H",
        "H..G",
    ]
    return GridWorld(grid, step_reward=0.0, goal_reward=1.0, hole_reward=0.0,
                      slip_prob=1.0 / 3.0, max_steps=100, name="FrozenLake")


REGISTRY = {
    "gridworld": make_gridworld,
    "cliffwalking": make_cliff_walking,
    "windygridworld": make_windy_gridworld,
    "frozenlake": make_frozen_lake,
}


def make(name):
    key = name.strip().lower().replace("_", "").replace("-", "")
    if key not in REGISTRY:
        raise KeyError(f"unknown env {name!r}; choices: {sorted(REGISTRY)}")
    return REGISTRY[key]()
