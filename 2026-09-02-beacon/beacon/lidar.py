"""A simulated planar lidar: N beams over a field of view, ray-cast against
the true World, with realistic range noise and beam dropouts.

A "scan" is a list of (angle_offset_from_heading, range_or_None) pairs.
range is None for a beam that hit nothing within max_range (or was
dropped), which downstream consumers (the mapper, the localizer) must
handle as "no obstacle observed on this bearing", not as a hit at max
range -- conflating the two invents phantom walls.
"""

from __future__ import annotations

import math
import random
from dataclasses import dataclass
from typing import List, Optional, Tuple

from .robot import Pose
from .world import World

Beam = Tuple[float, Optional[float]]  # (angle offset, range or None)


@dataclass
class LidarSpec:
    num_beams: int = 60
    fov: float = 2 * math.pi  # full 360 degree scan, typical for a 2D lidar
    max_range: float = 8.0
    range_noise_std: float = 0.05
    dropout_prob: float = 0.02


def scan(world: World, pose: Pose, spec: LidarSpec, rng: random.Random) -> List[Beam]:
    x, y, theta = pose
    beams: List[Beam] = []
    if spec.num_beams == 1:
        offsets = [0.0]
    else:
        start = -spec.fov / 2
        step = spec.fov / (spec.num_beams - 1) if spec.fov < 2 * math.pi else spec.fov / spec.num_beams
        offsets = [start + i * step for i in range(spec.num_beams)]

    for off in offsets:
        angle = theta + off
        if rng.random() < spec.dropout_prob:
            beams.append((off, None))
            continue
        true_range = world.raycast((x, y), angle, spec.max_range)
        if true_range is None:
            beams.append((off, None))
            continue
        noisy = true_range + rng.gauss(0.0, spec.range_noise_std)
        noisy = max(0.0, noisy)
        if noisy >= spec.max_range:
            beams.append((off, None))
        else:
            beams.append((off, noisy))
    return beams
