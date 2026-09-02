"""Particle filter localization (Monte Carlo Localization), using the
likelihood-field observation model.

Standard MCL loop (Probabilistic Robotics, Table 8.2):
  1. predict  -- move every particle with the same control the real robot
                 got, corrupted by the filter's own (larger, "I don't
                 actually know how noisy that was") motion noise
  2. update   -- weight each particle by how well the live scan matches
                 what that particle's hypothesized pose would predict,
                 using the likelihood field so this is O(beams) per
                 particle rather than a full raycast per particle per beam
  3. resample -- draw a new particle set proportional to weight (systematic
                 resampling), only when the filter has actually lost
                 diversity (effective-sample-size trigger), to avoid
                 needless particle impoverishment every single step
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass, field
from typing import List, Optional, Sequence, Tuple

from .distance_field import DistanceField
from .lidar import Beam
from .robot import MotionNoise, Pose, sample_velocity_motion

Particle = List[float]  # [x, y, theta]


@dataclass
class ObservationModel:
    sigma_hit: float = 0.25       # meters, width of the "matches a wall" bump
    z_hit: float = 0.85           # weight on the Gaussian-hit component
    z_rand: float = 0.15          # weight on the uniform "could be anything" component
    beam_stride: int = 4          # use every Nth beam (cost control)


class ParticleFilter:
    def __init__(
        self,
        num_particles: int,
        init_pose: Pose,
        init_std: Tuple[float, float, float],
        motion_noise: MotionNoise,
        obs_model: ObservationModel,
        rng: Optional[random.Random] = None,
        neff_resample_frac: float = 0.5,
    ):
        self.n = num_particles
        self.motion_noise = motion_noise
        self.obs_model = obs_model
        self.rng = rng or random.Random()
        self.neff_resample_frac = neff_resample_frac

        sx, sy, st = init_std
        self.particles: List[Particle] = [
            [
                init_pose[0] + self.rng.gauss(0.0, sx),
                init_pose[1] + self.rng.gauss(0.0, sy),
                init_pose[2] + self.rng.gauss(0.0, st),
            ]
            for _ in range(num_particles)
        ]
        self.weights: List[float] = [1.0 / num_particles] * num_particles
        self.last_neff = float(num_particles)

    # -- prediction ---------------------------------------------------------
    def predict(self, v: float, w: float, dt: float) -> None:
        for i, p in enumerate(self.particles):
            nx, ny, nth = sample_velocity_motion(
                (p[0], p[1], p[2]), v, w, dt, self.motion_noise, self.rng
            )
            p[0], p[1], p[2] = nx, ny, nth

    # -- weighting ------------------------------------------------------------
    def update(self, beams: Sequence[Beam], dfield: DistanceField, max_range: float) -> None:
        om = self.obs_model
        used = beams[:: om.beam_stride]
        # Beams with no return carry no positional evidence in the
        # likelihood-field model (a "no hit" could mean anything past the
        # sensor's reach) -- skip them rather than inventing a penalty.
        used = [b for b in used if b[1] is not None]
        if not used:
            return  # nothing to update on; keep current weights

        rand_component = om.z_rand / max_range
        two_sigma_sq = 2.0 * om.sigma_hit * om.sigma_hit
        gauss_norm = 1.0 / (om.sigma_hit * math.sqrt(2.0 * math.pi))

        log_weights = []
        for p in self.particles:
            px, py, pth = p
            log_w = 0.0
            for off, r in used:
                angle = pth + off
                ex = px + r * math.cos(angle)
                ey = py + r * math.sin(angle)
                d = dfield.distance_world(ex, ey)
                prob = om.z_hit * gauss_norm * math.exp(-(d * d) / two_sigma_sq) + rand_component
                log_w += math.log(max(prob, 1e-12))
            log_weights.append(log_w)

        max_lw = max(log_weights)
        exp_weights = [math.exp(lw - max_lw) for lw in log_weights]
        total = sum(exp_weights)
        if total <= 0.0:
            self.weights = [1.0 / self.n] * self.n
        else:
            self.weights = [w / total for w in exp_weights]

        self.last_neff = 1.0 / sum(w * w for w in self.weights)
        if self.last_neff < self.neff_resample_frac * self.n:
            self._resample_systematic()

    # -- resampling -----------------------------------------------------------
    def _resample_systematic(self) -> None:
        n = self.n
        positions = [(self.rng.random() + i) / n for i in range(n)]
        cumulative = []
        acc = 0.0
        for w in self.weights:
            acc += w
            cumulative.append(acc)
        cumulative[-1] = 1.0  # guard against float drift leaving a gap at the end

        new_particles: List[Particle] = []
        j = 0
        for pos in positions:
            while cumulative[j] < pos:
                j += 1
            src = self.particles[j]
            # Copy, with a whisper of jitter so resampled duplicates don't
            # collapse to literally identical points (standard "roughening").
            new_particles.append(
                [
                    src[0] + self.rng.gauss(0.0, 0.01),
                    src[1] + self.rng.gauss(0.0, 0.01),
                    src[2] + self.rng.gauss(0.0, 0.005),
                ]
            )
        self.particles = new_particles
        self.weights = [1.0 / n] * n
        self.last_neff = float(n)

    # -- estimate -------------------------------------------------------------
    def estimate(self) -> Pose:
        sx = sy = 0.0
        sin_sum = cos_sum = 0.0
        for p, w in zip(self.particles, self.weights):
            sx += p[0] * w
            sy += p[1] * w
            sin_sum += math.sin(p[2]) * w
            cos_sum += math.cos(p[2]) * w
        theta = math.atan2(sin_sum, cos_sum)
        return (sx, sy, theta)
