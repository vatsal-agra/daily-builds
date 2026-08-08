"""Analytic two-body (Keplerian) orbital mechanics.

This is the ground truth the N-body simulator gets checked against: given
classical orbital elements, `elements_to_state` returns the exact position
and velocity at any time t by solving Kepler's equation, with no numerical
integration involved. Used two ways:

  1. To *seed* N-body scenarios (put a planet on a real elliptical orbit
     instead of guessing plausible-looking numbers).
  2. As an *oracle*: run the seeded two-body system through the leapfrog
     integrator, and at every step compare the simulated position to
     `elements_to_state` at the same t. If they match to numerical
     tolerance over many orbital periods, the integrator is doing real
     physics.

Scope: bound (elliptical) orbits only, 0 <= e < 1. Parabolic/hyperbolic
trajectories are out of scope for this build (every scenario in
scenarios.py uses bound orbits).
"""

import math

from .vector import Vec3


def solve_kepler_equation(M, e, tol=1e-12, max_iter=100):
    """Solve M = E - e*sin(E) for the eccentric anomaly E, given mean
    anomaly M (radians) and eccentricity e, via Newton-Raphson."""
    if not (0.0 <= e < 1.0):
        raise ValueError(f"solve_kepler_equation: e must be in [0, 1), got {e}")

    M = _wrap_angle(M)
    E = M if e < 0.8 else math.pi  # standard starting-guess heuristic

    for _ in range(max_iter):
        f = E - e * math.sin(E) - M
        fprime = 1.0 - e * math.cos(E)
        dE = f / fprime
        E -= dE
        if abs(dE) < tol:
            return E
    # Should be unreachable for 0 <= e < 1 (Newton-Raphson converges
    # quadratically here); if it ever fires, that's a real bug to surface
    # rather than silently return a half-converged answer.
    raise ArithmeticError(f"Kepler's equation failed to converge: M={M}, e={e}, last dE={dE}")


def _wrap_angle(theta):
    """Wrap to (-pi, pi]."""
    return (theta + math.pi) % (2.0 * math.pi) - math.pi


def elements_to_state(a, e, i, omega_node, omega_peri, M0, t, mu, t0=0.0):
    """Convert classical orbital elements to an inertial-frame (position,
    velocity) pair at time t.

    a          semi-major axis
    e          eccentricity, 0 <= e < 1
    i          inclination (radians)
    omega_node longitude of the ascending node, "big Omega" (radians)
    omega_peri argument of periapsis, "small omega" (radians)
    M0         mean anomaly at epoch t0 (radians)
    t          time at which to evaluate
    mu         standard gravitational parameter, G * (M_central + m_body)
    t0         epoch at which M0 is defined (default 0)
    """
    if a <= 0.0:
        raise ValueError(f"elements_to_state: a must be positive, got {a}")
    if mu <= 0.0:
        raise ValueError(f"elements_to_state: mu must be positive, got {mu}")

    n = math.sqrt(mu / a ** 3)  # mean motion
    M = M0 + n * (t - t0)
    E = solve_kepler_equation(M, e)

    cosE, sinE = math.cos(E), math.sin(E)
    r = a * (1.0 - e * cosE)
    sqrt1me2 = math.sqrt(1.0 - e * e)

    # Perifocal frame (orbital plane, x toward periapsis).
    x_pf = a * (cosE - e)
    y_pf = a * sqrt1me2 * sinE
    speed_factor = math.sqrt(mu * a) / r
    vx_pf = -speed_factor * sinE
    vy_pf = speed_factor * sqrt1me2 * cosE

    # Perifocal -> inertial rotation: Rz(omega_node) * Rx(i) * Rz(omega_peri).
    cO, sO = math.cos(omega_node), math.sin(omega_node)
    ci, si = math.cos(i), math.sin(i)
    co, so = math.cos(omega_peri), math.sin(omega_peri)

    r11 = cO * co - sO * so * ci
    r12 = -cO * so - sO * co * ci
    r21 = sO * co + cO * so * ci
    r22 = -sO * so + cO * co * ci
    r31 = so * si
    r32 = co * si

    position = Vec3(
        r11 * x_pf + r12 * y_pf,
        r21 * x_pf + r22 * y_pf,
        r31 * x_pf + r32 * y_pf,
    )
    velocity = Vec3(
        r11 * vx_pf + r12 * vy_pf,
        r21 * vx_pf + r22 * vy_pf,
        r31 * vx_pf + r32 * vy_pf,
    )
    return position, velocity


def orbital_period(a, mu):
    """Kepler's third law: T = 2*pi*sqrt(a^3 / mu)."""
    if a <= 0.0 or mu <= 0.0:
        raise ValueError("orbital_period: a and mu must be positive")
    return 2.0 * math.pi * math.sqrt(a ** 3 / mu)


def vis_viva_speed(r, a, mu):
    """The vis-viva equation: v^2 = mu*(2/r - 1/a). Independent check on
    speed at a given distance, used in tests."""
    if r <= 0.0 or a <= 0.0 or mu <= 0.0:
        raise ValueError("vis_viva_speed: r, a, mu must be positive")
    return math.sqrt(mu * (2.0 / r - 1.0 / a))
