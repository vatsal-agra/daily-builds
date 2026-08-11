"""From-scratch continuous-state cart-pole environment.

The classic Barto/Sutton/Anderson (1983) cart-pole: a pole hinged to a
cart that can only move along a rail, pushed left or right by a fixed-
magnitude force each timestep. The physics is a coupled nonlinear ODE (no
closed-form solution, unlike the gridworlds) -- this is a real, if small,
instance of the control problem that made function approximation (DQN,
REINFORCE) necessary for RL in the first place: the 4-dimensional
continuous state space (cart position/velocity, pole angle/angular
velocity) can't be tabulated.

Equations of motion follow the standard formulation used by every
cart-pole RL benchmark (Sutton & Barto section 3.4 / the classic OpenAI
Gym CartPole-v1 physics), integrated here from scratch with
semi-implicit ("symplectic") Euler -- no gym, no pymunk/box2d.
"""
import math
import random

GRAVITY = 9.8
MASS_CART = 1.0
MASS_POLE = 0.1
TOTAL_MASS = MASS_CART + MASS_POLE
HALF_LENGTH = 0.5  # half the pole's length
POLE_MASS_LENGTH = MASS_POLE * HALF_LENGTH
FORCE_MAG = 10.0
TAU = 0.02  # seconds per simulation step

X_THRESHOLD = 2.4
THETA_THRESHOLD_RADIANS = 12 * 2 * math.pi / 360  # 12 degrees

ACTIONS = (0, 1)  # 0 = push left, 1 = push right
STATE_DIM = 4


class CartPoleEnv:
    def __init__(self, max_steps=500, seed=None):
        self.max_steps = max_steps
        self.rng = random.Random(seed)
        self.state = None
        self._t = 0

    def reset(self):
        # small random perturbation near the balanced upright state, the
        # standard cart-pole initial-state distribution
        self.state = tuple(self.rng.uniform(-0.05, 0.05) for _ in range(4))
        self._t = 0
        return self.state

    def step(self, action):
        if self.state is None:
            raise RuntimeError("call reset() before step()")
        if action not in ACTIONS:
            raise ValueError(f"action must be 0 or 1, got {action!r}")
        x, x_dot, theta, theta_dot = self.state
        force = FORCE_MAG if action == 1 else -FORCE_MAG
        costheta = math.cos(theta)
        sintheta = math.sin(theta)

        temp = (force + POLE_MASS_LENGTH * theta_dot ** 2 * sintheta) / TOTAL_MASS
        theta_acc = (GRAVITY * sintheta - costheta * temp) / (
            HALF_LENGTH * (4.0 / 3.0 - MASS_POLE * costheta ** 2 / TOTAL_MASS)
        )
        x_acc = temp - POLE_MASS_LENGTH * theta_acc * costheta / TOTAL_MASS

        # semi-implicit Euler: update velocities first, then use the *new*
        # velocities to update positions -- more stable than naive Euler
        # for oscillatory systems like this one
        x_dot = x_dot + TAU * x_acc
        x = x + TAU * x_dot
        theta_dot = theta_dot + TAU * theta_acc
        theta = theta + TAU * theta_dot

        self.state = (x, x_dot, theta, theta_dot)
        self._t += 1

        done = bool(
            x < -X_THRESHOLD
            or x > X_THRESHOLD
            or theta < -THETA_THRESHOLD_RADIANS
            or theta > THETA_THRESHOLD_RADIANS
        )
        truncated = self._t >= self.max_steps
        reward = 1.0  # +1 for every step the pole stayed up, incl. the terminal one
        return self.state, reward, done, truncated

    @staticmethod
    def action_space():
        return list(ACTIONS)
