"""O(N^2) direct-summation gravity. The reference implementation everything
else (Barnes-Hut) is checked against.
"""

from .vector import Vec3
from .body import DEFAULT_G


def compute_accelerations(bodies, G=DEFAULT_G, softening=0.0):
    """Return a list of Vec3 accelerations, one per body, in the same order
    as `bodies`, via direct pairwise summation.

    `softening` (epsilon) prevents the 1/r^2 singularity when two bodies
    get arbitrarily close: force uses (r^2 + eps^2)^1.5 instead of r^3.
    With softening=0 and two bodies at the exact same position, the force
    is defined as zero (rather than raising or returning NaN) since a
    physically meaningless configuration shouldn't crash the integrator;
    real scenarios should set softening > 0 whenever close encounters are
    possible.
    """
    n = len(bodies)
    accel = [Vec3(0.0, 0.0, 0.0) for _ in range(n)]
    eps_sq = softening * softening

    for i in range(n):
        bi = bodies[i]
        if not bi.alive:
            continue
        for j in range(i + 1, n):
            bj = bodies[j]
            if not bj.alive:
                continue
            d = bj.position - bi.position
            dist_sq = d.norm_sq() + eps_sq
            if dist_sq == 0.0:
                continue
            try:
                inv_dist3 = dist_sq ** -1.5
            except OverflowError:
                raise FloatingPointError(
                    f"Gravitational singularity: {bi.name!r} and {bj.name!r} are so close "
                    f"(distance^2={dist_sq:.3e}) that 1/r^3 overflows a float. Use a nonzero "
                    f"`softening` parameter to avoid this."
                ) from None
            # a_i += G * m_j * d / |d|^3   (and equal & opposite on j)
            accel[i] += d * (G * bj.mass * inv_dist3)
            accel[j] += d * (-G * bi.mass * inv_dist3)

    return accel
