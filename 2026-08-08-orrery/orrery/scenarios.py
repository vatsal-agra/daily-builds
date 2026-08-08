"""Preset scenes.

Units convention for anything solar-system-scale: AU for distance, solar
masses for mass, years for time. In that unit system Newton's constant is
not 1 -- it's G = 4*pi^2 (AU^3 / (Msun * yr^2)), which is exactly what
makes a 1 AU circular orbit around a 1-solar-mass star have a 1-year
period and a 2*pi AU/yr speed, both directly checkable against the real
solar system.

The figure-eight three-body choreography instead uses the "G=1, all
masses=1" unit system its published initial conditions were derived in;
mixing that with the astro unit convention would just relabel the same
physics with less recognizable numbers, so it gets its own G.
"""

import math
import random

from .vector import Vec3
from .body import Body
from .kepler import elements_to_state

G_ASTRO = 4.0 * math.pi ** 2  # AU^3 / (Msun * yr^2)


class Scenario:
    def __init__(self, name, bodies, G, recommended_dt, softening, description):
        self.name = name
        self.bodies = bodies
        self.G = G
        self.recommended_dt = recommended_dt
        self.softening = softening
        self.description = description


def _deg(x):
    return math.radians(x)


# (name, a[AU], e, i[deg], Omega[deg], omega[deg], M0[deg], mass[Msun], color)
_PLANETS = [
    ("Mercury", 0.38710, 0.20563, 7.005, 48.331, 29.124, 174.8, 1.6601e-7, "#9c9188"),
    ("Venus", 0.72333, 0.00677, 3.395, 76.680, 54.884, 50.4, 2.4478e-6, "#d8b876"),
    ("Earth", 1.00000, 0.01671, 0.000, 0.000, 114.208, 358.6, 3.0035e-6, "#4a90d9"),
    ("Mars", 1.52368, 0.09339, 1.850, 49.558, 286.502, 19.4, 3.2137e-7, "#c1440e"),
    ("Jupiter", 5.20260, 0.04849, 1.303, 100.464, 273.867, 20.0, 9.5458e-4, "#d8a56c"),
    ("Saturn", 9.55491, 0.05551, 2.485, 113.665, 339.392, 317.0, 2.8588e-4, "#e3c88a"),
    ("Uranus", 19.21845, 0.04630, 0.773, 74.006, 96.998, 142.2, 4.3662e-5, "#93c7d8"),
    ("Neptune", 30.11039, 0.00899, 1.770, 131.784, 272.856, 256.2, 5.1514e-5, "#4166f5"),
]


def solar_system():
    """The Sun + 8 planets, on real (approximate J2000-epoch) elliptical
    orbital elements. The Sun is given a small velocity so total system
    momentum is exactly zero -- otherwise the whole system slowly drifts
    off in whatever direction the planets' net momentum points, which
    looks like a bug even though it isn't one.
    """
    sun_mass = 1.0
    mu_sun = G_ASTRO * sun_mass  # planet masses are negligible next to the Sun's

    bodies = []
    sun = Body("Sun", sun_mass, Vec3(0, 0, 0), Vec3(0, 0, 0), radius=0.06, color="#ffd24a")
    bodies.append(sun)

    for name, a, e, i, Omega, omega, M0, mass, color in _PLANETS:
        mu = G_ASTRO * (sun_mass + mass)
        pos, vel = elements_to_state(a, e, _deg(i), _deg(Omega), _deg(omega), _deg(M0), t=0.0, mu=mu)
        bodies.append(Body(name, mass, pos, vel, radius=0.015 + 0.01 * math.log10(mass / 1e-7 + 1), color=color))

    total_p = Vec3(0, 0, 0)
    for b in bodies[1:]:
        total_p += b.momentum()
    sun.velocity = total_p * (-1.0 / sun_mass)

    return Scenario(
        "solar_system", bodies, G_ASTRO, recommended_dt=1.0 / 365.25, softening=1e-4,
        description="Sun + 8 planets on real approximate elliptical elements (AU / Msun / yr).",
    )


def binary_star():
    """Two stars orbiting their common barycenter on an eccentric orbit."""
    m1, m2 = 1.0, 0.8
    a, e = 2.0, 0.35
    mu = G_ASTRO * (m1 + m2)
    rel_pos, rel_vel = elements_to_state(a, e, 0.0, 0.0, 0.0, 0.0, t=0.0, mu=mu)

    p1 = rel_pos * (-m2 / (m1 + m2))
    v1 = rel_vel * (-m2 / (m1 + m2))
    p2 = rel_pos * (m1 / (m1 + m2))
    v2 = rel_vel * (m1 / (m1 + m2))

    bodies = [
        Body("Alpha", m1, p1, v1, radius=0.05, color="#ffd24a"),
        Body("Beta", m2, p2, v2, radius=0.045, color="#ff9a5a"),
    ]
    return Scenario(
        "binary_star", bodies, G_ASTRO, recommended_dt=1.0 / 365.25, softening=1e-4,
        description="Two stars (1.0 and 0.8 solar masses) on a shared eccentric orbit around their barycenter.",
    )


def figure_eight():
    """The Moore/Chenciner-Montgomery figure-eight three-body choreography:
    three equal masses chase each other around a stable figure-eight path.
    Uses the G=1, m=1 unit system these published initial conditions were
    derived in (period T ~= 6.32591398)."""
    x1, y1 = 0.97000436, -0.24308753
    vx3, vy3 = -0.93240737, -0.86473146
    vx1, vy1 = -vx3 / 2.0, -vy3 / 2.0

    bodies = [
        Body("A", 1.0, Vec3(x1, y1, 0), Vec3(vx1, vy1, 0), radius=0.03, color="#4a90d9"),
        Body("B", 1.0, Vec3(-x1, -y1, 0), Vec3(vx1, vy1, 0), radius=0.03, color="#c1440e"),
        Body("C", 1.0, Vec3(0, 0, 0), Vec3(vx3, vy3, 0), radius=0.03, color="#ffd24a"),
    ]
    return Scenario(
        "figure_eight", bodies, G=1.0, recommended_dt=6.32591398 / 4000.0, softening=0.0,
        description="The Moore/Chenciner-Montgomery figure-eight three-body choreography (G=1, m=1 units).",
    )


def _sample_plummer(n, total_mass, scale_radius, G, rng, center=Vec3(0, 0, 0), bulk_velocity=Vec3(0, 0, 0)):
    """Sample n bodies from a Plummer sphere in (approximate) virial
    equilibrium, via the standard Aarseth/Henon/Wielen rejection-sampling
    method. Returns a list of Body.
    """
    if n < 1:
        raise ValueError(f"_sample_plummer: n must be >= 1, got {n}")
    m_each = total_mass / n
    bodies = []
    for k in range(n):
        # --- position: inverse-CDF sample of the Plummer density profile.
        # random() can (rarely) return exactly 0.0, which would raise a
        # ZeroDivisionError in x1**(-2/3); clamp away from it.
        x1 = max(rng.random(), 1e-12)
        r = scale_radius / math.sqrt(x1 ** (-2.0 / 3.0) - 1.0)
        x2, x3 = rng.random(), rng.random()
        z = (1.0 - 2.0 * x2) * r
        rxy = math.sqrt(max(r * r - z * z, 0.0))
        phi = 2.0 * math.pi * x3
        pos = Vec3(rxy * math.cos(phi), rxy * math.sin(phi), z)

        # --- velocity: rejection sample q = v/v_esc from g(q) = q^2 (1-q^2)^3.5
        v_esc = math.sqrt(2.0 * G * total_mass / math.sqrt(r * r + scale_radius * scale_radius))
        g_max = 0.1  # max of q^2(1-q^2)^3.5 on [0,1] is ~0.092 at q^2=2/9
        while True:
            q = rng.random()
            g = (q * q) * (1.0 - q * q) ** 3.5
            if rng.random() * g_max <= g:
                break
        speed = q * v_esc

        x2v, x3v = rng.random(), rng.random()
        zv = (1.0 - 2.0 * x2v) * speed
        rxyv = math.sqrt(max(speed * speed - zv * zv, 0.0))
        phiv = 2.0 * math.pi * x3v
        vel = Vec3(rxyv * math.cos(phiv), rxyv * math.sin(phiv), zv)

        bodies.append(Body(
            f"star{k}", m_each, pos + center, vel + bulk_velocity,
            radius=0.01, color="#cfd8ff",
        ))
    return bodies


def plummer_cluster(n=60, total_mass=50.0, scale_radius=1.0, seed=42):
    """A self-gravitating star cluster sampled from a Plummer density
    profile, starting near virial equilibrium -- it should hold together
    and slowly relax rather than immediately fly apart or collapse.
    Deterministic for a given seed (default 42) so demo/tests are
    reproducible.
    """
    if n < 1:
        raise ValueError(f"plummer_cluster: n must be a positive integer, got {n}")
    rng = random.Random(seed)
    G = 1.0
    bodies = _sample_plummer(n, total_mass, scale_radius, G, rng)
    # Recenter on the cluster's own center of mass / momentum so it doesn't
    # drift off-screen (finite-N sampling doesn't exactly zero these out).
    _recenter(bodies)
    return Scenario(
        "plummer_cluster", bodies, G, recommended_dt=1e-3, softening=0.05,
        description=f"A {n}-star Plummer-sphere cluster (G=1 units) sampled near virial equilibrium.",
    )


def galaxy_collision(n_per_galaxy=40, seed=7):
    """Two Plummer clusters ('galaxies') on an intercept course."""
    if n_per_galaxy < 1:
        raise ValueError(f"galaxy_collision: n_per_galaxy must be a positive integer, got {n_per_galaxy}")
    rng = random.Random(seed)
    G = 1.0
    total_mass = 30.0
    scale_radius = 0.8

    g1 = _sample_plummer(
        n_per_galaxy, total_mass, scale_radius, G, rng,
        center=Vec3(-4.0, 0.0, 0.0), bulk_velocity=Vec3(0.6, 0.05, 0.0),
    )
    for b in g1:
        b.name = "A_" + b.name
        b.color = "#4a90d9"

    g2 = _sample_plummer(
        n_per_galaxy, total_mass, scale_radius, G, rng,
        center=Vec3(4.0, 0.5, 0.0), bulk_velocity=Vec3(-0.6, -0.05, 0.0),
    )
    for b in g2:
        b.name = "B_" + b.name
        b.color = "#ff9a5a"

    bodies = g1 + g2
    return Scenario(
        "galaxy_collision", bodies, G, recommended_dt=2e-3, softening=0.08,
        description=f"Two {n_per_galaxy}-star Plummer 'galaxies' on a collision course (G=1 units).",
    )


def _recenter(bodies):
    total_mass = sum(b.mass for b in bodies)
    com = Vec3(0, 0, 0)
    p = Vec3(0, 0, 0)
    for b in bodies:
        com += b.position * b.mass
        p += b.momentum()
    com = com / total_mass
    v_com = p / total_mass
    for b in bodies:
        b.position = b.position - com
        b.velocity = b.velocity - v_com


REGISTRY = {
    "solar_system": solar_system,
    "binary_star": binary_star,
    "figure_eight": figure_eight,
    "plummer_cluster": plummer_cluster,
    "galaxy_collision": galaxy_collision,
}


def build(name, **kwargs):
    if name not in REGISTRY:
        raise ValueError(f"Unknown scenario {name!r}. Known: {sorted(REGISTRY)}")
    return REGISTRY[name](**kwargs)
