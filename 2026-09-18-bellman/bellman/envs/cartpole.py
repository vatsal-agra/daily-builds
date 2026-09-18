"""CartPole: balance a pole hinged to a cart by pushing the cart left or
right (Barto, Sutton & Anderson 1983; the version OpenAI Gym made the
standard first benchmark for policy-gradient methods). Continuous
4-dimensional state (cart position, cart velocity, pole angle, pole
angular velocity), 2 discrete actions, dense reward (+1 every tick the
pole is still up).

Physics constants and the update equations match the standard reference
implementation (Euler integration of the classic single-pole cart-pole
dynamics) rather than anything tuned to be easy.
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
        self._t = 0
        return tuple(rng.uniform(-0.05, 0.05) for _ in range(4))

    def step(self, state, action):
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

        self._t += 1
        fell = x < -X_THRESHOLD or x > X_THRESHOLD or theta < -THETA_THRESHOLD or theta > THETA_THRESHOLD
        timed_out = self._t >= self.max_steps
        done = fell or timed_out
        reward = 1.0  # every tick the pole was still up when this step was taken
        return (x, x_dot, theta, theta_dot), reward, done, timed_out and not fell

    @staticmethod
    def normalize(state):
        x, x_dot, theta, theta_dot = state
        return (
            x / X_THRESHOLD,
            x_dot / 2.0,
            theta / THETA_THRESHOLD,
            theta_dot / 3.0,
        )
