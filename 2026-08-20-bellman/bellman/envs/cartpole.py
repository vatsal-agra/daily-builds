"""A from-scratch CartPole-v1-style environment.

Physics: the classic cart-and-inverted-pole system (Barto, Sutton &
Anderson 1983), integrated with semi-implicit ("symplectic") Euler at a
fixed 0.02s timestep. A single scalar force is applied left/right to the
cart; the goal is to keep the pole balanced upright and the cart on the
track. State is a continuous 4-vector: [cart position, cart velocity,
pole angle (radians, 0 = upright), pole angular velocity].

Reward is +1 for every timestep the episode is still alive (including
the terminal step), matching the standard convention this environment is
modeled on. Episode ends when the pole falls past +-12 degrees, the cart
leaves +-2.4 units of the track center, or `max_steps` is reached.
"""

from __future__ import annotations

import math
import random


class CartPole:
    GRAVITY = 9.8
    MASS_CART = 1.0
    MASS_POLE = 0.1
    TOTAL_MASS = MASS_CART + MASS_POLE
    HALF_LENGTH = 0.5  # half the pole's length
    POLE_MASS_LENGTH = MASS_POLE * HALF_LENGTH
    FORCE_MAG = 10.0
    TAU = 0.02  # seconds per step

    THETA_THRESHOLD = 12 * 2 * math.pi / 360  # +-12 degrees, in radians
    X_THRESHOLD = 2.4

    n_actions = 2  # 0 = push left, 1 = push right
    state_dim = 4

    def __init__(self, max_steps=500, seed=None):
        self.max_steps = max_steps
        self._rng = random.Random(seed)
        self._state = (0.0, 0.0, 0.0, 0.0)
        self._t = 0

    def seed(self, seed):
        self._rng.seed(seed)

    def reset(self):
        self._state = tuple(self._rng.uniform(-0.05, 0.05) for _ in range(4))
        self._t = 0
        return self._state

    def step(self, action):
        if action not in (0, 1):
            raise ValueError(f"invalid action {action!r}, must be 0 or 1")
        x, x_dot, theta, theta_dot = self._state
        force = self.FORCE_MAG if action == 1 else -self.FORCE_MAG
        costheta = math.cos(theta)
        sintheta = math.sin(theta)

        temp = (
            force + self.POLE_MASS_LENGTH * theta_dot * theta_dot * sintheta
        ) / self.TOTAL_MASS
        theta_acc = (self.GRAVITY * sintheta - costheta * temp) / (
            self.HALF_LENGTH
            * (4.0 / 3.0 - self.MASS_POLE * costheta * costheta / self.TOTAL_MASS)
        )
        x_acc = temp - self.POLE_MASS_LENGTH * theta_acc * costheta / self.TOTAL_MASS

        # Semi-implicit Euler: update velocities first, then use the *new*
        # velocities to update position — unconditionally more stable than
        # explicit Euler for oscillatory systems like this one.
        x_dot = x_dot + self.TAU * x_acc
        x = x + self.TAU * x_dot
        theta_dot = theta_dot + self.TAU * theta_acc
        theta = theta + self.TAU * theta_dot

        self._state = (x, x_dot, theta, theta_dot)
        self._t += 1

        done = bool(
            x < -self.X_THRESHOLD
            or x > self.X_THRESHOLD
            or theta < -self.THETA_THRESHOLD
            or theta > self.THETA_THRESHOLD
        )
        truncated = self._t >= self.max_steps
        reward = 1.0
        return self._state, reward, (done or truncated), {"truncated": truncated, "fell": done}
