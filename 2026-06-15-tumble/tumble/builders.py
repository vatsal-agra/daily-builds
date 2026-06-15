"""Composite-body builders: rope, cloth, rigid box, soft blob.

Each builder appends particles + constraints to a World and returns the list of
particle indices it created (so scenes can pin/inspect them).
"""
import math

from .engine import Particle


def rope(world, x0, y0, x1, y1, segments=12, pin_start=True, pin_end=False,
         radius=5.0, stiffness=1.0, mass=1.0, tearable=True):
    """A chain of particles linked end-to-end."""
    inv = 0.0 if mass == 0.0 else 1.0 / mass
    idxs = []
    for k in range(segments + 1):
        t = k / segments
        x = x0 + (x1 - x0) * t
        y = y0 + (y1 - y0) * t
        im = inv
        if (k == 0 and pin_start) or (k == segments and pin_end):
            im = 0.0
        idxs.append(world.add_particle(Particle(x, y, im, radius)))
    for k in range(segments):
        world.connect(idxs[k], idxs[k + 1], stiffness=stiffness, tearable=tearable)
    return idxs


def cloth(world, x0, y0, cols, rows, spacing=22.0, pin_top=True,
          pin_corners_only=False, radius=4.0, stiffness=0.9, mass=1.0,
          bend=True, tearable=True):
    """A grid of particles with structural, shear and (optional) bend links."""
    inv = 0.0 if mass == 0.0 else 1.0 / mass
    grid = [[None] * cols for _ in range(rows)]
    for r in range(rows):
        for c in range(cols):
            x = x0 + c * spacing
            y = y0 + r * spacing
            im = inv
            if r == 0 and pin_top:
                if pin_corners_only:
                    if c == 0 or c == cols - 1:
                        im = 0.0
                else:
                    im = 0.0
            grid[r][c] = world.add_particle(Particle(x, y, im, radius))
    # structural (horizontal + vertical)
    for r in range(rows):
        for c in range(cols):
            if c + 1 < cols:
                world.connect(grid[r][c], grid[r][c + 1], stiffness=stiffness,
                              tearable=tearable)
            if r + 1 < rows:
                world.connect(grid[r][c], grid[r + 1][c], stiffness=stiffness,
                              tearable=tearable)
    # shear (diagonals) — weaker so cloth can drape
    sh = stiffness * 0.6
    for r in range(rows - 1):
        for c in range(cols - 1):
            world.connect(grid[r][c], grid[r + 1][c + 1], stiffness=sh,
                          tearable=tearable)
            world.connect(grid[r + 1][c], grid[r][c + 1], stiffness=sh,
                          tearable=tearable)
    # bend (skip-one) — resists folding, never tears
    if bend:
        bd = stiffness * 0.3
        for r in range(rows):
            for c in range(cols):
                if c + 2 < cols:
                    world.connect(grid[r][c], grid[r][c + 2], stiffness=bd,
                                  tearable=False)
                if r + 2 < rows:
                    world.connect(grid[r][c], grid[r + 2][c], stiffness=bd,
                                  tearable=False)
    return grid


def box(world, cx, cy, w, h, radius=6.0, stiffness=1.0, mass=1.0,
        vx=0.0, vy=0.0):
    """A rigid rectangle: 4 corners with edges + both diagonals at full stiffness."""
    inv = 0.0 if mass == 0.0 else 1.0 / mass
    hw, hh = w / 2.0, h / 2.0
    corners = [(-hw, -hh), (hw, -hh), (hw, hh), (-hw, hh)]
    idxs = []
    for dx, dy in corners:
        idxs.append(world.add_particle(
            Particle(cx + dx, cy + dy, inv, radius, vx, vy)))
    edges = [(0, 1), (1, 2), (2, 3), (3, 0), (0, 2), (1, 3)]
    for i, j in edges:
        world.connect(idxs[i], idxs[j], stiffness=stiffness, tearable=False)
    return idxs


def blob(world, cx, cy, r, n=14, radius=6.0, stiffness=0.6, mass=1.0,
         vx=0.0, vy=0.0):
    """A soft body: a ring of particles + a hub, all spoked together."""
    inv = 0.0 if mass == 0.0 else 1.0 / mass
    hub = world.add_particle(Particle(cx, cy, inv, radius, vx, vy))
    ring = []
    for k in range(n):
        ang = 2.0 * math.pi * k / n
        x = cx + math.cos(ang) * r
        y = cy + math.sin(ang) * r
        ring.append(world.add_particle(Particle(x, y, inv, radius, vx, vy)))
    for k in range(n):
        world.connect(ring[k], ring[(k + 1) % n], stiffness=stiffness,
                      tearable=False)
        world.connect(hub, ring[k], stiffness=stiffness * 0.8, tearable=False)
        # skip-one ring links keep the blob from collapsing
        world.connect(ring[k], ring[(k + 2) % n], stiffness=stiffness * 0.5,
                      tearable=False)
    return [hub] + ring
