"""Tumble core: a deterministic 2D Verlet / Position-Based-Dynamics engine.

This is the *reference* implementation. ``web/engine.js`` is a byte-for-byte
mirror that performs the same operations in the same order, so the two can be
cross-checked for bit-close parity (see tests/test_tumble.py).

Design notes
------------
* Particles store position (x, y) and previous position (px, py); velocity is
  implicit (v = pos - prev), which is the essence of Verlet integration.
* ``inv_mass == 0`` means a particle is pinned (infinite mass) and never moves.
* The ``step`` loop is, every frame, exactly:
    1. integrate (Verlet, with gravity + wind + damping)
    2. solve constraints/collisions for ``iterations`` passes, each pass in a
       fixed order: distance constraints, particle collisions, segments, bounds
    3. (the tearing check happens inside the distance-constraint solve)
  The fixed order + fixed timestep make a scene replay identically every run.
"""
import json
import math


class Particle:
    __slots__ = ("x", "y", "px", "py", "inv_mass", "radius")

    def __init__(self, x, y, inv_mass=1.0, radius=6.0, vx=0.0, vy=0.0):
        self.x = float(x)
        self.y = float(y)
        # prev position encodes the initial velocity: v = pos - prev
        self.px = float(x) - float(vx)
        self.py = float(y) - float(vy)
        self.inv_mass = float(inv_mass)
        self.radius = float(radius)

    @property
    def pinned(self):
        return self.inv_mass == 0.0

    def to_dict(self):
        return {
            "x": self.x, "y": self.y, "px": self.px, "py": self.py,
            "inv_mass": self.inv_mass, "radius": self.radius,
        }

    @classmethod
    def from_dict(cls, d):
        p = cls.__new__(cls)
        p.x = float(d["x"]); p.y = float(d["y"])
        p.px = float(d["px"]); p.py = float(d["py"])
        p.inv_mass = float(d["inv_mass"]); p.radius = float(d["radius"])
        return p


class DistanceConstraint:
    __slots__ = ("i", "j", "rest", "stiffness", "tearable", "active")

    def __init__(self, i, j, rest, stiffness=1.0, tearable=True):
        self.i = i
        self.j = j
        self.rest = float(rest)
        self.stiffness = float(stiffness)
        self.tearable = bool(tearable)
        self.active = True

    def to_dict(self):
        return {
            "i": self.i, "j": self.j, "rest": self.rest,
            "stiffness": self.stiffness, "tearable": self.tearable,
            "active": self.active,
        }

    @classmethod
    def from_dict(cls, d):
        c = cls(d["i"], d["j"], d["rest"], d.get("stiffness", 1.0),
                d.get("tearable", True))
        c.active = bool(d.get("active", True))
        return c


class LineSegment:
    """A static line-segment obstacle (with thickness = radius)."""
    __slots__ = ("ax", "ay", "bx", "by", "radius")

    def __init__(self, ax, ay, bx, by, radius=0.0):
        self.ax = float(ax); self.ay = float(ay)
        self.bx = float(bx); self.by = float(by)
        self.radius = float(radius)

    def to_dict(self):
        return {"ax": self.ax, "ay": self.ay, "bx": self.bx, "by": self.by,
                "radius": self.radius}

    @classmethod
    def from_dict(cls, d):
        return cls(d["ax"], d["ay"], d["bx"], d["by"], d.get("radius", 0.0))


class World:
    def __init__(self, width=800.0, height=600.0, gravity=(0.0, 980.0),
                 dt=1.0 / 60.0, iterations=8, damping=0.01,
                 restitution=0.3, friction=0.05, wind=(0.0, 0.0),
                 self_collision=False, tearing=False, tear_strain=0.6,
                 cell_size=40.0):
        self.width = float(width)
        self.height = float(height)
        self.gx, self.gy = float(gravity[0]), float(gravity[1])
        self.dt = float(dt)
        self.iterations = int(iterations)
        self.damping = float(damping)        # velocity *= (1 - damping)
        self.restitution = float(restitution)
        self.friction = float(friction)
        self.wx, self.wy = float(wind[0]), float(wind[1])
        self.self_collision = bool(self_collision)
        self.tearing = bool(tearing)
        self.tear_strain = float(tear_strain)
        self.cell_size = float(cell_size)
        if self.cell_size <= 0.0:
            self.cell_size = 1.0
        self.particles = []
        self.constraints = []
        self.segments = []
        self.time = 0.0

    # ---- construction helpers ------------------------------------------
    def add_particle(self, p):
        self.particles.append(p)
        return len(self.particles) - 1

    def connect(self, i, j, rest=None, stiffness=1.0, tearable=True):
        if rest is None:
            a, b = self.particles[i], self.particles[j]
            rest = math.sqrt((a.x - b.x) ** 2 + (a.y - b.y) ** 2)
        c = DistanceConstraint(i, j, rest, stiffness, tearable)
        self.constraints.append(c)
        return c

    def add_segment(self, seg):
        self.segments.append(seg)
        return seg

    # ---- the simulation -------------------------------------------------
    def step(self):
        self._integrate()
        for _ in range(self.iterations):
            self._solve_distance()
            if self.self_collision:
                self._solve_collisions()
            if self.segments:
                self._solve_segments()
            self._solve_bounds()
        self.time += self.dt

    def _integrate(self):
        dt2 = self.dt * self.dt
        keep = 1.0 - self.damping
        ax = self.gx + self.wx
        ay = self.gy + self.wy
        for p in self.particles:
            if p.inv_mass == 0.0:
                continue
            vx = (p.x - p.px) * keep
            vy = (p.y - p.py) * keep
            p.px = p.x
            p.py = p.y
            p.x += vx + ax * dt2
            p.y += vy + ay * dt2

    def _solve_distance(self):
        ps = self.particles
        tearing = self.tearing
        limit_factor = 1.0 + self.tear_strain
        for c in self.constraints:
            if not c.active:
                continue
            a = ps[c.i]; b = ps[c.j]
            dx = b.x - a.x
            dy = b.y - a.y
            dist = math.sqrt(dx * dx + dy * dy)
            if dist == 0.0:
                continue
            if tearing and c.tearable and dist > c.rest * limit_factor:
                c.active = False
                continue
            inv_sum = a.inv_mass + b.inv_mass
            if inv_sum == 0.0:
                continue
            diff = (dist - c.rest) / dist * c.stiffness
            # weight the correction by each particle's share of the inverse mass
            wa = a.inv_mass / inv_sum
            wb = b.inv_mass / inv_sum
            a.x += dx * diff * wa
            a.y += dy * diff * wa
            b.x -= dx * diff * wb
            b.y -= dy * diff * wb

    def _grid_pairs(self):
        """Deterministic broadphase: uniform grid -> (i, j) pairs with j > i.

        Iteration is by ascending particle index and a fixed neighbour order so
        Python and JS produce the identical pair sequence.
        """
        cs = self.cell_size
        ps = self.particles
        grid = {}
        for idx, p in enumerate(ps):
            cx = math.floor(p.x / cs)
            cy = math.floor(p.y / cs)
            grid.setdefault((cx, cy), []).append(idx)
        offsets = ((-1, -1), (0, -1), (1, -1),
                   (-1, 0), (0, 0), (1, 0),
                   (-1, 1), (0, 1), (1, 1))
        for i, p in enumerate(ps):
            cx = math.floor(p.x / cs)
            cy = math.floor(p.y / cs)
            for ox, oy in offsets:
                bucket = grid.get((cx + ox, cy + oy))
                if not bucket:
                    continue
                for j in bucket:
                    if j > i:
                        yield i, j

    def _solve_collisions(self):
        ps = self.particles
        for i, j in self._grid_pairs():
            a = ps[i]; b = ps[j]
            dx = b.x - a.x
            dy = b.y - a.y
            min_d = a.radius + b.radius
            d2 = dx * dx + dy * dy
            if d2 >= min_d * min_d:
                continue
            inv_sum = a.inv_mass + b.inv_mass
            if inv_sum == 0.0:
                continue
            dist = math.sqrt(d2)
            if dist == 0.0:
                # exactly coincident: shove apart along +x deterministically
                dx, dy, dist = 1.0, 0.0, 1.0
            overlap = (min_d - dist) / dist
            wa = a.inv_mass / inv_sum
            wb = b.inv_mass / inv_sum
            a.x -= dx * overlap * wa
            a.y -= dy * overlap * wa
            b.x += dx * overlap * wb
            b.y += dy * overlap * wb

    def _solve_segments(self):
        for p in self.particles:
            if p.inv_mass == 0.0:
                continue
            for s in self.segments:
                abx = s.bx - s.ax
                aby = s.by - s.ay
                ab2 = abx * abx + aby * aby
                if ab2 == 0.0:
                    cx, cy = s.ax, s.ay
                else:
                    t = ((p.x - s.ax) * abx + (p.y - s.ay) * aby) / ab2
                    if t < 0.0:
                        t = 0.0
                    elif t > 1.0:
                        t = 1.0
                    cx = s.ax + abx * t
                    cy = s.ay + aby * t
                dx = p.x - cx
                dy = p.y - cy
                r = p.radius + s.radius
                d2 = dx * dx + dy * dy
                if d2 >= r * r or d2 == 0.0:
                    continue
                dist = math.sqrt(d2)
                push = (r - dist) / dist
                p.x += dx * push
                p.y += dy * push

    def _solve_bounds(self):
        rest = self.restitution
        fric = self.friction
        w = self.width
        h = self.height
        for p in self.particles:
            if p.inv_mass == 0.0:
                continue
            r = p.radius
            # --- x axis ---
            vx = p.x - p.px
            vy = p.y - p.py
            if p.x < r:
                p.x = r
                p.px = p.x + vx * rest
                p.py = p.y - vy * (1.0 - fric)
            elif p.x > w - r:
                p.x = w - r
                p.px = p.x + vx * rest
                p.py = p.y - vy * (1.0 - fric)
            # --- y axis (recompute velocity after possible x edit) ---
            vx = p.x - p.px
            vy = p.y - p.py
            if p.y < r:
                p.y = r
                p.py = p.y + vy * rest
                p.px = p.x - vx * (1.0 - fric)
            elif p.y > h - r:
                p.y = h - r
                p.py = p.y + vy * rest
                p.px = p.x - vx * (1.0 - fric)

    # ---- diagnostics ----------------------------------------------------
    def kinetic_energy(self):
        ke = 0.0
        for p in self.particles:
            if p.inv_mass == 0.0:
                continue
            vx = p.x - p.px
            vy = p.y - p.py
            mass = 1.0 / p.inv_mass
            ke += 0.5 * mass * (vx * vx + vy * vy)
        return ke

    def active_constraints(self):
        return sum(1 for c in self.constraints if c.active)

    def all_finite(self):
        for p in self.particles:
            if not (math.isfinite(p.x) and math.isfinite(p.y)
                    and math.isfinite(p.px) and math.isfinite(p.py)):
                return False
        return True

    def state_hash(self):
        """Stable hash of all particle positions, for determinism tests."""
        import hashlib
        h = hashlib.sha256()
        for p in self.particles:
            h.update(("%.10f,%.10f,%.10f,%.10f;" % (p.x, p.y, p.px, p.py)).encode())
        return h.hexdigest()

    # ---- serialization --------------------------------------------------
    def to_dict(self):
        return {
            "width": self.width, "height": self.height,
            "gravity": [self.gx, self.gy], "dt": self.dt,
            "iterations": self.iterations, "damping": self.damping,
            "restitution": self.restitution, "friction": self.friction,
            "wind": [self.wx, self.wy], "self_collision": self.self_collision,
            "tearing": self.tearing, "tear_strain": self.tear_strain,
            "cell_size": self.cell_size, "time": self.time,
            "particles": [p.to_dict() for p in self.particles],
            "constraints": [c.to_dict() for c in self.constraints],
            "segments": [s.to_dict() for s in self.segments],
        }

    def to_json(self, indent=None):
        return json.dumps(self.to_dict(), indent=indent)

    @classmethod
    def from_dict(cls, d):
        w = cls(
            width=d.get("width", 800.0), height=d.get("height", 600.0),
            gravity=d.get("gravity", [0.0, 980.0]), dt=d.get("dt", 1.0 / 60.0),
            iterations=d.get("iterations", 8), damping=d.get("damping", 0.01),
            restitution=d.get("restitution", 0.3), friction=d.get("friction", 0.05),
            wind=d.get("wind", [0.0, 0.0]),
            self_collision=d.get("self_collision", False),
            tearing=d.get("tearing", False), tear_strain=d.get("tear_strain", 0.6),
            cell_size=d.get("cell_size", 40.0),
        )
        w.time = d.get("time", 0.0)
        w.particles = [Particle.from_dict(p) for p in d.get("particles", [])]
        w.constraints = [DistanceConstraint.from_dict(c) for c in d.get("constraints", [])]
        w.segments = [LineSegment.from_dict(s) for s in d.get("segments", [])]
        return w

    @classmethod
    def from_json(cls, s):
        return cls.from_dict(json.loads(s))
