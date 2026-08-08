"""Time integrators, and the energy/momentum diagnostics used to tell a
correct one from a broken one.

Two integrators are provided on purpose, not just one:

- `euler_step` is plain explicit (forward) Euler: advance position using
  the *old* velocity, then advance velocity using the *old* acceleration.
  It is not symplectic. On an orbit it visibly gains energy every step —
  the orbit spirals outward and eventually flies apart, no matter how
  small dt gets (only the rate of drift changes, not its existence).

- `leapfrog_step` is kick-drift-kick velocity Verlet, a symplectic
  integrator: it conserves a shadow Hamiltonian close to the true energy,
  so energy oscillates but does not systematically drift. Closed orbits
  stay closed over arbitrarily many periods.

Building both, side by side, on the same scenario is the point: it turns
"symplectic integrators matter" from an assertion into something the demo
report measures.
"""

from .vector import Vec3
from .body import DEFAULT_G


def euler_step(bodies, dt, accel_fn):
    """Explicit Euler. Returns the acceleration used, for API symmetry
    with leapfrog_step (not reusable as `prev_accel` — Euler doesn't have
    the same structure)."""
    accel = accel_fn(bodies)
    for b, a in zip(bodies, accel):
        if not b.alive:
            continue
        b.position = b.position + b.velocity * dt
        b.velocity = b.velocity + a * dt
    return accel


def leapfrog_step(bodies, dt, accel_fn, prev_accel=None):
    """Kick-drift-kick velocity Verlet. If `prev_accel` (the acceleration
    computed at the end of the previous step) is supplied, this only needs
    one fresh force evaluation instead of two -- the "kick" at the start
    of this step reuses the "kick" at the end of the last one. Returns the
    newly computed acceleration, meant to be threaded into the next call.
    """
    accel_old = prev_accel if prev_accel is not None else accel_fn(bodies)

    for b, a in zip(bodies, accel_old):
        if not b.alive:
            continue
        b.velocity = b.velocity + a * (dt * 0.5)

    for b in bodies:
        if not b.alive:
            continue
        b.position = b.position + b.velocity * dt

    accel_new = accel_fn(bodies)

    for b, a in zip(bodies, accel_new):
        if not b.alive:
            continue
        b.velocity = b.velocity + a * (dt * 0.5)

    return accel_new


METHODS = {"euler": euler_step, "leapfrog": leapfrog_step}


# --- Diagnostics ------------------------------------------------------

def total_kinetic_energy(bodies):
    return sum(b.kinetic_energy() for b in bodies if b.alive)


def total_potential_energy(bodies, G=DEFAULT_G, softening=0.0):
    eps_sq = softening * softening
    alive = [b for b in bodies if b.alive]
    pe = 0.0
    for i in range(len(alive)):
        for j in range(i + 1, len(alive)):
            d = alive[j].position - alive[i].position
            dist = (d.norm_sq() + eps_sq) ** 0.5
            if dist == 0.0:
                continue
            pe += -G * alive[i].mass * alive[j].mass / dist
    return pe


def total_energy(bodies, G=DEFAULT_G, softening=0.0):
    return total_kinetic_energy(bodies) + total_potential_energy(bodies, G, softening)


def total_momentum(bodies):
    p = Vec3(0.0, 0.0, 0.0)
    for b in bodies:
        if b.alive:
            p += b.momentum()
    return p


def total_angular_momentum(bodies, origin=None):
    origin = origin or Vec3(0.0, 0.0, 0.0)
    L = Vec3(0.0, 0.0, 0.0)
    for b in bodies:
        if b.alive:
            r = b.position - origin
            L += r.cross(b.momentum())
    return L
