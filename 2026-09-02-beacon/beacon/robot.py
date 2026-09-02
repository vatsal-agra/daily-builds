"""Differential-drive kinematics and the velocity motion model.

Implements the noisy velocity motion model from Thrun/Burgard/Fox,
*Probabilistic Robotics*, Table 5.3: a commanded (v, w) is corrupted by
noise that scales with the commanded speeds themselves (alpha1..alpha6),
then integrated exactly along the resulting circular arc (with a
straight-line special case as w -> 0, since the arc-radius formula is
singular there).

This same function is used for two different things with two different
noise parameters, which is the whole point of the simulator:
  - the *true* robot moving through the world (robot.py, small "reality"
    noise -- real wheels really do slip a little)
  - each *particle*'s predicted next pose in the particle filter
    (pf_localizer.py, larger "belief" noise -- the filter must hedge
    against not knowing the realized noise, only the noise model)
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import Optional, Tuple

from .geometry import Point, normalize_angle
from .world import World

Pose = Tuple[float, float, float]  # x, y, theta


@dataclass
class MotionNoise:
    """alpha1..alpha6 from Probabilistic Robotics Table 5.3."""

    a1: float = 0.02
    a2: float = 0.02
    a3: float = 0.02
    a4: float = 0.02
    a5: float = 0.01
    a6: float = 0.01


def sample_velocity_motion(
    pose: Pose, v: float, w: float, dt: float, noise: MotionNoise, rng: random.Random
) -> Pose:
    x, y, theta = pose

    var_v = noise.a1 * v * v + noise.a2 * w * w
    var_w = noise.a3 * v * v + noise.a4 * w * w
    var_g = noise.a5 * v * v + noise.a6 * w * w

    v_hat = v + rng.gauss(0.0, math.sqrt(var_v)) if var_v > 0 else v
    w_hat = w + rng.gauss(0.0, math.sqrt(var_w)) if var_w > 0 else w
    gamma_hat = rng.gauss(0.0, math.sqrt(var_g)) if var_g > 0 else 0.0

    if abs(w_hat) < 1e-6:
        # Straight-line special case: the arc radius v_hat/w_hat blows up.
        nx = x + v_hat * dt * math.cos(theta)
        ny = y + v_hat * dt * math.sin(theta)
        ntheta = theta + gamma_hat * dt
    else:
        radius = v_hat / w_hat
        ntheta_arc = theta + w_hat * dt
        nx = x - radius * math.sin(theta) + radius * math.sin(ntheta_arc)
        ny = y + radius * math.cos(theta) - radius * math.cos(ntheta_arc)
        ntheta = ntheta_arc + gamma_hat * dt

    return (nx, ny, normalize_angle(ntheta))


class Robot:
    """The one true physical robot in the simulation. Its exact pose is
    ground truth -- visible to the test harness and the visualizer for
    scoring/rendering, but never passed into any estimation algorithm."""

    def __init__(
        self,
        world: World,
        pose: Pose,
        radius: float = 0.3,
        noise: Optional[MotionNoise] = None,
        rng: Optional[random.Random] = None,
    ):
        self.world = world
        self.pose = pose
        self.radius = radius
        self.noise = noise or MotionNoise()
        self.rng = rng or random.Random()
        self.collided_last_step = False

    def drive(self, v: float, w: float, dt: float) -> Pose:
        """Execute one noisy motion step. If the noisy motion would drive
        the robot's body into a wall, the translation is rejected (the
        robot "bumps" and stays put) but the noisy rotation still applies
        -- a real differential-drive base can still turn in place against
        a wall it's nosed up against."""
        candidate = sample_velocity_motion(self.pose, v, w, dt, self.noise, self.rng)
        if self.world.collides((candidate[0], candidate[1]), self.radius):
            self.collided_last_step = True
            _, _, old_theta = self.pose
            self.pose = (self.pose[0], self.pose[1], candidate[2])
        else:
            self.collided_last_step = False
            self.pose = candidate
        return self.pose
