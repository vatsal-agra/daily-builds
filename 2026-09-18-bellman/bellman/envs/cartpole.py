"""CartPole: balance a pole hinged to a cart by pushing the cart left or
right (Barto, Sutton & Anderson 1983; the version OpenAI Gym made the
standard first benchmark for policy-gradient methods). Continuous
4-dimensional state (cart position, cart velocity, pole angle, pole
angular velocity), 2 discrete actions, dense reward (+1 every tick the
pole is still up).

Physics constants and the update equations match the standard reference
implementation (Euler integration of the classic single-pole cart-pole
dynamics) rather than anything tuned to be easy.

step() is a pure function of (state, action), same as CliffWalking's --
it does not track how many ticks have elapsed on `self`. An earlier
version did (an instance counter set by reset() and incremented by every
step()), which meant step() before reset() crashed, and two interleaved
episodes sharing one CartPole instance would corrupt each other's step
count; a test calling step() directly (to check the falling-over case at
a specific hand-built state) caught it. The episode-length cutoff is the
*caller's* concern (bellman/reinforce.py's run_episode loops at most
`env.max_steps` times), not the environment's.
"""
import math

GRAVITY = 9.8
MASSCART = 1.0
MASSPOLE = 0.1
TOTAL_MASS = MASSCART + MASSPOLE
LENGTH = 0.5  # half the pole's length
POLEMASS_LENGTH = MASSPOLE * LENGTH
FORCE_MAG = 10.0
TAU = 0.02  # seconds per simulation tick

X_THRESHOLD = 2.4
THETA_THRESHOLD = 12 * 2 * math.pi / 360  # 12 degrees, in radians

ACTIONS = (0, 1)  # push left, push right
ACTION_NAMES = {0: "left", 1: "right"}


class CartPole:
    def __init__(self, max_steps=200):
        self.max_steps = max_steps
        self.n_actions = len(ACTIONS)

    def reset(self, rng):
        return tuple(rng.uniform(-0.05, 0.05) for _ in range(4))

    def step(self, state, action):
        """Return (next_state, reward, fell). `fell` means the pole
        dropped past the angle threshold or the cart left the track --
        the *only* failure this environment itself knows about. Running
        out of time is not a failure of the physics, so it is not this
        function's job to report it; see the module docstring."""
        x, x_dot, theta, theta_dot = state
        force = FORCE_MAG if action == 1 else -FORCE_MAG
        costheta = math.cos(theta)
        sintheta = math.sin(theta)

        temp = (force + POLEMASS_LENGTH * theta_dot * theta_dot * sintheta) / TOTAL_MASS
        theta_acc = (GRAVITY * sintheta - costheta * temp) / (
            LENGTH * (4.0 / 3.0 - MASSPOLE * costheta * costheta / TOTAL_MASS)
        )
        x_acc = temp - POLEMASS_LENGTH * theta_acc * costheta / TOTAL_MASS

        x = x + TAU * x_dot
        x_dot = x_dot + TAU * x_acc
        theta = theta + TAU * theta_dot
        theta_dot = theta_dot + TAU * theta_acc

        fell = x < -X_THRESHOLD or x > X_THRESHOLD or theta < -THETA_THRESHOLD or theta > THETA_THRESHOLD
        reward = 1.0  # every tick the pole was still up when this step was taken
        return (x, x_dot, theta, theta_dot), reward, fell

    @staticmethod
    def normalize(state):
        x, x_dot, theta, theta_dot = state
        return (
            x / X_THRESHOLD,
            x_dot / 2.0,
            theta / THETA_THRESHOLD,
            theta_dot / 3.0,
        )
