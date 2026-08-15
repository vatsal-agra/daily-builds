"""Environments, built from scratch — no `gym`/`gymnasium` dependency anywhere.

Every environment exposes the same minimal interface:
    reset() -> state
    step(action) -> (next_state, reward, done, info)

`GridWorldEnv` additionally exposes `states`, `actions`, `is_terminal`, and
`transition_model(state, action) -> [(prob, next_state, reward, done), ...]`
so `dp.py` can compute the exact Bellman-optimal policy from the true model
-- something the TD/MC learners in `td.py`/`mc.py` are never given; they only
ever see samples from `step()`.
"""
import math
import random

# Grid actions: 0=up, 1=right, 2=down, 3=left
ACTION_DELTAS = {0: (-1, 0), 1: (0, 1), 2: (1, 0), 3: (0, -1)}
ACTION_ARROWS = {0: "^", 1: ">", 2: "v", 3: "<"}


class GridWorldEnv:
    """Classic Cliff Walking (Sutton & Barto, Example 6.6), with optional slip.

    A rows x cols grid. Agent starts bottom-left, goal is bottom-right.
    The bottom row between them is a cliff: stepping into it costs -100 and
    sends the agent back to start. Every other step costs -1. Reaching the
    goal ends the episode. `slip_prob` (0 = classic deterministic dynamics)
    is the probability the actual move is one of the other three directions
    instead of the intended one, split evenly -- turns this into a genuine
    stochastic MDP rather than a maze with a single deterministic path.
    """

    actions = [0, 1, 2, 3]

    def __init__(self, rows=4, cols=12, slip_prob=0.0, seed=None):
        self.rows, self.cols = rows, cols
        self.slip_prob = slip_prob
        self.start = (rows - 1, 0)
        self.goal = (rows - 1, cols - 1)
        self.cliff = {(rows - 1, c) for c in range(1, cols - 1)}
        self.states = list(range(rows * cols))
        self.rng = random.Random(seed)
        self.state = self.encode(*self.start)

    def encode(self, row, col):
        return row * self.cols + col

    def decode(self, s):
        return divmod(s, self.cols)

    def is_terminal(self, s):
        return self.decode(s) == self.goal

    def reset(self):
        self.state = self.encode(*self.start)
        return self.state

    def _clamped_move(self, row, col, action):
        dr, dc = ACTION_DELTAS[action]
        nr = min(max(row + dr, 0), self.rows - 1)
        nc = min(max(col + dc, 0), self.cols - 1)
        return nr, nc

    def transition_model(self, s, action):
        """The exact model: list of (probability, next_state, reward, done)."""
        row, col = self.decode(s)
        if (row, col) == self.goal:
            return [(1.0, s, 0.0, True)]

        if self.slip_prob <= 0.0:
            outcomes = [(action, 1.0)]
        else:
            others = [a for a in self.actions if a != action]
            outcomes = [(action, 1.0 - self.slip_prob)] + \
                       [(a, self.slip_prob / len(others)) for a in others]

        merged = {}  # next_state -> [prob, reward, done]
        for a, p in outcomes:
            nr, nc = self._clamped_move(row, col, a)
            if (nr, nc) in self.cliff:
                ns, r, done = self.encode(*self.start), -100.0, False
            elif (nr, nc) == self.goal:
                ns, r, done = self.encode(nr, nc), -1.0, True
            else:
                ns, r, done = self.encode(nr, nc), -1.0, False
            key = (ns, r, done)
            merged[key] = merged.get(key, 0.0) + p

        return [(p, ns, r, done) for (ns, r, done), p in merged.items()]

    def step(self, action):
        outcomes = self.transition_model(self.state, action)
        roll = self.rng.random()
        cum = 0.0
        chosen = outcomes[-1]
        for outcome in outcomes:
            cum += outcome[0]
            if roll <= cum:
                chosen = outcome
                break
        _, ns, r, done = chosen
        self.state = ns
        return ns, r, done, {}

    def render_ascii(self, policy=None):
        lines = []
        for r in range(self.rows):
            row_chars = []
            for c in range(self.cols):
                if (r, c) == self.start:
                    row_chars.append("S")
                elif (r, c) == self.goal:
                    row_chars.append("G")
                elif (r, c) in self.cliff:
                    row_chars.append("#")
                elif policy is not None:
                    row_chars.append(ACTION_ARROWS[policy[self.encode(r, c)]])
                else:
                    row_chars.append(".")
            lines.append(" ".join(row_chars))
        return "\n".join(lines)


class CartPoleEnv:
    """The classic pole-balancing control problem, hand-integrated.

    Real nonlinear equations of motion for a pole hinged to a cart (Barto,
    Sutton & Anderson 1983 / the formulation OpenAI Gym's CartPole-v1 uses),
    integrated with semi-implicit ("Euler-Cromer") Euler -- no physics
    engine, no `gym` import. Actions: 0 = push cart left, 1 = push right.
    """

    actions = [0, 1]

    GRAVITY = 9.8
    MASSCART = 1.0
    MASSPOLE = 0.1
    TOTAL_MASS = MASSCART + MASSPOLE
    LENGTH = 0.5  # half the pole's length
    POLEMASS_LENGTH = MASSPOLE * LENGTH
    FORCE_MAG = 10.0
    TAU = 0.02  # seconds per simulation step

    X_THRESHOLD = 2.4
    THETA_THRESHOLD_RADIANS = 12 * 2 * math.pi / 360  # 12 degrees

    def __init__(self, max_steps=500, seed=None):
        self.max_steps = max_steps
        self.rng = random.Random(seed)
        self.state = (0.0, 0.0, 0.0, 0.0)
        self.steps = 0

    def reset(self):
        self.state = tuple(self.rng.uniform(-0.05, 0.05) for _ in range(4))
        self.steps = 0
        return self.state

    def step(self, action):
        x, x_dot, theta, theta_dot = self.state
        force = self.FORCE_MAG if action == 1 else -self.FORCE_MAG
        costheta, sintheta = math.cos(theta), math.sin(theta)

        temp = (force + self.POLEMASS_LENGTH * theta_dot ** 2 * sintheta) / self.TOTAL_MASS
        thetaacc = (self.GRAVITY * sintheta - costheta * temp) / (
            self.LENGTH * (4.0 / 3.0 - self.MASSPOLE * costheta ** 2 / self.TOTAL_MASS)
        )
        xacc = temp - self.POLEMASS_LENGTH * thetaacc * costheta / self.TOTAL_MASS

        # semi-implicit Euler: update velocity first, then position with the *new* velocity
        x_dot += self.TAU * xacc
        x += self.TAU * x_dot
        theta_dot += self.TAU * thetaacc
        theta += self.TAU * theta_dot

        self.state = (x, x_dot, theta, theta_dot)
        self.steps += 1

        done = (abs(x) > self.X_THRESHOLD
                or abs(theta) > self.THETA_THRESHOLD_RADIANS
                or self.steps >= self.max_steps)
        reward = 1.0
        return self.state, reward, done, {}


class BlackjackEnv:
    """Simplified infinite-deck Blackjack (Sutton & Barto, Example 5.1).

    State: (player_sum, dealer_showing_card, usable_ace). Actions: 0=stick,
    1=hit. Dealer plays a fixed policy (hits while sum < 17). No splits or
    doubling -- hit/stick only, matching the textbook formulation exactly so
    the reference optimal policy in `dp.py`'s Blackjack solver is comparable.
    """

    actions = [0, 1]  # 0 = stick, 1 = hit

    def __init__(self, seed=None):
        self.rng = random.Random(seed)
        self.player = []
        self.dealer = []
        self.done = False

    def _draw(self):
        return min(self.rng.randint(1, 13), 10)

    @staticmethod
    def _sum_hand(cards):
        total = sum(cards)
        usable_ace = False
        if 1 in cards and total + 10 <= 21:
            total += 10
            usable_ace = True
        return total, usable_ace

    def _obs(self):
        total, usable_ace = self._sum_hand(self.player)
        return (total, self.dealer[0], usable_ace)

    def reset(self):
        self.player = [self._draw(), self._draw()]
        self.dealer = [self._draw(), self._draw()]
        self.done = False
        return self._obs()

    def reset_to(self, player_total, dealer_showing, usable_ace):
        """Force the environment into a specific (player_total, dealer_showing,
        usable_ace) state by fabricating a matching hand -- the "exploring
        starts" hook Monte Carlo ES needs: every episode begins at a uniformly
        random (state, action) pair instead of only states reachable from a
        fresh natural deal, so every state-action pair the policy is graded on
        actually gets visited during training.
        """
        assert 12 <= player_total <= 21, "reset_to only covers the graded 12..21 range"
        if usable_ace:
            self.player = [1, player_total - 11]  # ace (=1) + a card making the soft total
        elif player_total == 21:
            self.player = [1, 10, 10]  # hard 21 via a "downgraded" ace (A+10+10=21, not soft)
        else:
            hi = min(10, player_total - 2)
            self.player = [hi, player_total - hi]
        self.dealer = [dealer_showing, self._draw()]
        self.done = False
        assert self._obs() == (player_total, dealer_showing, usable_ace)
        return self._obs()

    def resolve_natural(self):
        """If the player was just dealt a natural 21, resolve it immediately
        (push against a dealer natural, otherwise a win) instead of silently
        ending the episode with no reward -- used by callers that don't want
        a hit/stick decision offered on an un-actionable dealt blackjack."""
        p_total, _ = self._sum_hand(self.player)
        if p_total != 21:
            return None
        d_total, _ = self._sum_hand(self.dealer)
        self.done = True
        reward = 0.0 if d_total == 21 else 1.0
        return self._obs(), reward, True, {}

    def step(self, action):
        assert not self.done, "step() called on a finished episode"
        p_total, _ = self._sum_hand(self.player)

        if action == 1:  # hit
            self.player.append(self._draw())
            p_total, _ = self._sum_hand(self.player)
            if p_total > 21:
                self.done = True
                return self._obs(), -1.0, True, {}
            return self._obs(), 0.0, False, {}

        # stick: dealer plays out a fixed policy, then compare
        self.done = True
        d_total, _ = self._sum_hand(self.dealer)
        while d_total < 17:
            self.dealer.append(self._draw())
            d_total, _ = self._sum_hand(self.dealer)

        if d_total > 21 or p_total > d_total:
            reward = 1.0
        elif p_total < d_total:
            reward = -1.0
        else:
            reward = 0.0
        return self._obs(), reward, True, {}
