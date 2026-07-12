"""Wires a Genome to the physics engine: builds the phenotype, steps the
CPG controller + physics world for a fixed duration, and scores the
result. Fitness rewards horizontal distance traveled and penalizes
toppling over and gratuitous motor effort, so evolution can't win by
spamming max-torque jitter or being flung ballistically once and never
recovering an upright gait.
"""
from dataclasses import dataclass, field

from .body import build_phenotype
from .physics import World

DT = 1.0 / 240.0
# Toppled = the torso has rotated past this many radians from its rest
# orientation (~103 deg) -- an angle criterion works for any body plan
# (tall biped or flat snake) unlike a height threshold, which would need
# per-genome calibration. Sustained, not instantaneous, so a creature
# that's mid-stride-wobble but recovering isn't penalized.
TOPPLE_ANGLE = 1.8
TOPPLE_GRACE_STEPS = 72     # ~0.3s at DT=1/240, must stay toppled this long to end the run early
ENERGY_COEFF = 0.0025
TRACE_STRIDE = 4            # record a trace frame every N physics steps (~60 Hz at DT=1/240)


@dataclass
class SimResult:
    fitness: float
    distance: float
    energy: float
    toppled: bool
    duration_simulated: float
    trace: list = field(default_factory=list)   # list of (t, [(x,y,angle), ...]) if requested
    body_dims: list = field(default_factory=list)  # [(half_length, half_width), ...] parallel to bodies


def run_simulation(genome, duration=8.0, record_trace=False):
    phenotype = build_phenotype(genome)
    world = World(phenotype.bodies, phenotype.joints)

    start_x = phenotype.root_body.pos[0]
    rest_angle = phenotype.root_body.angle
    toppled_streak = 0
    toppled = False
    steps = int(duration / DT)

    trace = []
    body_dims = [(b.hl, b.hw) for b in phenotype.bodies] if record_trace else []

    t = 0.0
    stopped_at = duration
    for i in range(steps):
        phenotype.update_controller(genome.base_freq, t)
        world.step(DT)
        t += DT

        if record_trace and i % TRACE_STRIDE == 0:
            frame = [(b.pos[0], b.pos[1], b.angle) for b in phenotype.bodies]
            trace.append((t, frame))

        angle_dev = abs(_wrap_pi(phenotype.root_body.angle - rest_angle))
        if angle_dev > TOPPLE_ANGLE:
            toppled_streak += 1
            if toppled_streak >= TOPPLE_GRACE_STEPS:
                toppled = True
                stopped_at = t
                break
        else:
            toppled_streak = 0

        if any(math_isnan(b.pos[0]) or math_isnan(b.pos[1]) for b in phenotype.bodies):
            # a numerically unstable genome (e.g. degenerate zero-mass edge
            # case) must fail fitness cleanly, not crash the whole GA run.
            toppled = True
            stopped_at = t
            break

    end_x = phenotype.root_body.pos[0]
    distance = end_x - start_x
    energy = world.motor_energy

    fitness = distance - ENERGY_COEFF * energy
    if toppled:
        fitness -= 1.0

    return SimResult(
        fitness=fitness,
        distance=distance,
        energy=energy,
        toppled=toppled,
        duration_simulated=stopped_at,
        trace=trace,
        body_dims=body_dims,
    )


def math_isnan(x):
    return x != x


def _wrap_pi(angle):
    import math
    return (angle + math.pi) % (2 * math.pi) - math.pi
