"""Perfectly inelastic, momentum-conserving mergers.

When two bodies overlap (distance between centers < sum of radii), the
less massive one is absorbed into the more massive one: mass adds, the
survivor's position/velocity become the mass-weighted (center-of-mass)
average of the two, and its radius grows as if the combined mass kept the
same constant density (volumes add: r_new = (r1^3 + r2^3)^(1/3)). The
absorbed body is marked dead rather than removed from the list, so array
indices stay stable across a simulation run (trajectory recording,
checkpoints, etc. don't need to special-case a shrinking body count).
"""


def resolve_collisions(bodies, log=None, t=None):
    """Scan for overlapping bodies and merge them, repeating until no pair
    in this step is still colliding (handles chain merges: A absorbs B,
    and the grown A now also overlaps C). Bounded to len(bodies)+1 passes
    so a pathological configuration can't loop forever.

    Returns True if at least one merge happened.
    """
    any_merge = False
    passes = 0
    max_passes = len(bodies) + 1

    while passes < max_passes:
        passes += 1
        alive = [b for b in bodies if b.alive]
        merged_this_pass = False

        for i in range(len(alive)):
            bi = alive[i]
            if not bi.alive:
                continue
            for j in range(i + 1, len(alive)):
                bj = alive[j]
                if not bj.alive:
                    continue
                dist = (bj.position - bi.position).norm()
                if dist < bi.radius + bj.radius:
                    survivor, absorbed = (bi, bj) if bi.mass >= bj.mass else (bj, bi)
                    _merge_into(survivor, absorbed)
                    absorbed.alive = False
                    any_merge = True
                    merged_this_pass = True
                    if log is not None:
                        log.append({
                            "t": t,
                            "survivor": survivor.name,
                            "absorbed": absorbed.name,
                            "new_mass": survivor.mass,
                        })

        if not merged_this_pass:
            break

    return any_merge


def _merge_into(survivor, absorbed):
    m1, m2 = survivor.mass, absorbed.mass
    total = m1 + m2
    survivor.position = (survivor.position * m1 + absorbed.position * m2) / total
    survivor.velocity = (survivor.velocity * m1 + absorbed.velocity * m2) / total
    survivor.radius = (survivor.radius ** 3 + absorbed.radius ** 3) ** (1.0 / 3.0)
    survivor.mass = total
    survivor.absorbed_count += 1 + absorbed.absorbed_count
