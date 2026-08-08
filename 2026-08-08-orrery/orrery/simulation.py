"""The simulation driver: owns the body list, advances time, records a
trajectory history, and can checkpoint to / resume from JSON.
"""

import json

from .body import Body, DEFAULT_G
from . import bruteforce
from . import octree
from . import integrator
from . import collision


class Simulation:
    def __init__(self, bodies, G=DEFAULT_G, method="leapfrog", theta=0.5,
                 softening=0.0, use_barnes_hut=True, collisions=False):
        if not bodies:
            raise ValueError("Simulation needs at least one body")
        if method not in integrator.METHODS:
            raise ValueError(f"Unknown method {method!r}, expected one of {sorted(integrator.METHODS)}")
        if softening < 0.0:
            raise ValueError(f"softening must be >= 0, got {softening}")
        if theta < 0.0:
            raise ValueError(f"theta must be >= 0, got {theta}")

        self.bodies = bodies
        self.G = G
        self.method = method
        self.theta = theta
        self.softening = softening
        self.use_barnes_hut = use_barnes_hut
        self.collisions = collisions

        self.t = 0.0
        self.step_count = 0
        self.collision_log = []
        self.history = []
        self._prev_accel = None  # cached acceleration, reused by leapfrog

    @classmethod
    def from_scenario(cls, scenario, method="leapfrog", theta=0.5,
                       use_barnes_hut=True, collisions=False, softening=None):
        return cls(
            scenario.bodies, G=scenario.G, method=method, theta=theta,
            softening=scenario.softening if softening is None else softening,
            use_barnes_hut=use_barnes_hut, collisions=collisions,
        )

    def _accel_fn(self):
        if self.use_barnes_hut:
            def f(bodies):
                return octree.compute_accelerations(bodies, G=self.G, theta=self.theta, softening=self.softening)
        else:
            def f(bodies):
                return bruteforce.compute_accelerations(bodies, G=self.G, softening=self.softening)
        return f

    def step(self, dt):
        if dt <= 0.0:
            raise ValueError(f"dt must be positive, got {dt}")

        accel_fn = self._accel_fn()
        if self.method == "leapfrog":
            self._prev_accel = integrator.leapfrog_step(self.bodies, dt, accel_fn, prev_accel=self._prev_accel)
        else:
            integrator.euler_step(self.bodies, dt, accel_fn)
            self._prev_accel = None

        self.t += dt
        self.step_count += 1

        if self.collisions:
            merged = collision.resolve_collisions(self.bodies, log=self.collision_log, t=self.t)
            if merged:
                # Mass/position/velocity just changed discontinuously (not
                # via the equations of motion) -- the cached acceleration
                # from the leapfrog half-kick above is now stale.
                self._prev_accel = None

        for b in self.bodies:
            if b.alive and not (b.position.is_finite() and b.velocity.is_finite()):
                raise FloatingPointError(
                    f"Simulation diverged: non-finite state for body {b.name!r} "
                    f"at t={self.t} (try a smaller dt and/or nonzero softening)"
                )

    def run(self, steps, dt, record_every=1):
        """Advance `steps` steps of size dt. Records a snapshot (state,
        energy, momentum, angular momentum) every `record_every` steps,
        always including the initial and final state. Returns the
        recorded history (also left on self.history)."""
        if steps < 0:
            raise ValueError(f"steps must be >= 0, got {steps}")
        if record_every < 1:
            raise ValueError(f"record_every must be >= 1, got {record_every}")

        self.history = []
        self._record_snapshot()
        for i in range(steps):
            self.step(dt)
            if (i + 1) % record_every == 0 or i == steps - 1:
                self._record_snapshot()
        return self.history

    def _record_snapshot(self):
        self.history.append({
            "t": self.t,
            "step": self.step_count,
            "bodies": [b.to_dict() for b in self.bodies],
            "energy": integrator.total_energy(self.bodies, self.G, self.softening),
            "momentum": integrator.total_momentum(self.bodies).to_tuple(),
            "angular_momentum": integrator.total_angular_momentum(self.bodies).to_tuple(),
        })

    # --- checkpointing ---------------------------------------------------

    def to_checkpoint(self):
        return {
            "t": self.t,
            "step_count": self.step_count,
            "G": self.G,
            "method": self.method,
            "theta": self.theta,
            "softening": self.softening,
            "use_barnes_hut": self.use_barnes_hut,
            "collisions": self.collisions,
            "bodies": [b.to_dict() for b in self.bodies],
            "collision_log": self.collision_log,
        }

    def save(self, path):
        with open(path, "w") as f:
            json.dump(self.to_checkpoint(), f)

    @staticmethod
    def from_checkpoint(d):
        required = ("t", "step_count", "G", "method", "theta", "softening", "bodies")
        missing = [k for k in required if k not in d]
        if missing:
            raise ValueError(f"Checkpoint missing required field(s): {missing}")

        bodies = [Body.from_dict(bd) for bd in d["bodies"]]
        sim = Simulation(
            bodies, G=d["G"], method=d["method"], theta=d["theta"],
            softening=d["softening"], use_barnes_hut=d.get("use_barnes_hut", True),
            collisions=d.get("collisions", False),
        )
        sim.t = d["t"]
        sim.step_count = d["step_count"]
        sim.collision_log = d.get("collision_log", [])
        return sim

    @staticmethod
    def load(path):
        with open(path) as f:
            d = json.load(f)
        return Simulation.from_checkpoint(d)
