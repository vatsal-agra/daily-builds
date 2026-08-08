"""A gravitating point mass."""

from .vector import Vec3

# Gravitational constant. Simulations use "sim units" throughout (see
# scenarios.py for the AU / solar-mass / year convention used there) rather
# than SI, so this is a parameter of the Simulation, not a hardcoded global
# — but Body itself is unit-agnostic.
DEFAULT_G = 1.0


class Body:
    """A point mass with position, velocity, and (for rendering/collisions)
    a radius derived from mass assuming constant density.
    """

    def __init__(self, name, mass, position, velocity, radius=None, color="#e8e8e8"):
        if mass <= 0:
            raise ValueError(f"Body {name!r}: mass must be positive, got {mass}")
        if not isinstance(position, Vec3) or not isinstance(velocity, Vec3):
            raise TypeError("position and velocity must be Vec3")
        if not position.is_finite() or not velocity.is_finite():
            raise ValueError(f"Body {name!r}: non-finite position or velocity")

        self.name = name
        self.mass = float(mass)
        self.position = position.copy()
        self.velocity = velocity.copy()
        # Constant-density radius: mass = (4/3) pi r^3 rho, rho fixed at 1
        # so radius scales sensibly (bigger mass -> bigger radius) without
        # needing a real density number the caller has to guess.
        self.radius = float(radius) if radius is not None else _radius_from_mass(self.mass)
        self.color = color
        self.alive = True  # set False when merged away by a collision
        self.absorbed_count = 0  # how many other bodies this one has merged with

    def momentum(self):
        return self.velocity * self.mass

    def kinetic_energy(self):
        return 0.5 * self.mass * self.velocity.norm_sq()

    def copy(self):
        b = Body(self.name, self.mass, self.position, self.velocity, self.radius, self.color)
        b.alive = self.alive
        b.absorbed_count = self.absorbed_count
        return b

    def to_dict(self):
        return {
            "name": self.name,
            "mass": self.mass,
            "position": self.position.to_tuple(),
            "velocity": self.velocity.to_tuple(),
            "radius": self.radius,
            "color": self.color,
            "alive": self.alive,
            "absorbed_count": self.absorbed_count,
        }

    @staticmethod
    def from_dict(d):
        b = Body(
            d["name"], d["mass"],
            Vec3.from_tuple(d["position"]), Vec3.from_tuple(d["velocity"]),
            radius=d.get("radius"), color=d.get("color", "#e8e8e8"),
        )
        b.alive = d.get("alive", True)
        b.absorbed_count = d.get("absorbed_count", 0)
        return b


def _radius_from_mass(mass, rho=1.0):
    return ((3.0 * mass) / (4.0 * 3.141592653589793 * rho)) ** (1.0 / 3.0)
