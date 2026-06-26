"""
Flux core: 2D Navier-Stokes fluid simulator (Stam's Stable Fluids, 1999).

Grid layout: (N+2) × (N+2) arrays where indices 0 and N+1 are ghost/boundary
cells. Interior: [1..N, 1..N].  First axis = x (horizontal), second = y (vertical).
"""

import numpy as np
from dataclasses import dataclass, field
from typing import List, Optional, Tuple


# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

@dataclass
class DyeChannel:
    """One scalar advected dye field with an associated display colour."""
    color: Tuple[float, float, float]   # RGB in [0, 1]
    density: np.ndarray                  # (N+2, N+2) current density
    source: np.ndarray                   # (N+2, N+2) per-frame injection

    @staticmethod
    def make(N: int, color: Tuple[float, float, float]) -> "DyeChannel":
        sz = (N + 2, N + 2)
        return DyeChannel(color=color,
                          density=np.zeros(sz),
                          source=np.zeros(sz))


class FluidGrid:
    """
    Full state of a 2D incompressible fluid on an N×N grid.

    Parameters
    ----------
    N        : grid resolution (interior cells per side)
    dt       : timestep (seconds)
    visc     : kinematic viscosity (0 = inviscid)
    diff     : dye diffusion coefficient (0 = no diffusion)
    vort_scale: vorticity confinement strength (0 = disabled)
    gravity  : downward body force (applied to y-velocity)
    iters    : Gauss-Seidel iterations for diffuse + project
    """

    def __init__(self, N: int = 128, dt: float = 0.15,
                 visc: float = 0.0, diff: float = 0.0,
                 vort_scale: float = 0.0, gravity: float = 0.0,
                 iters: int = 20):
        self.N = N
        self.dt = dt
        self.visc = visc
        self.diff = diff
        self.vort_scale = vort_scale
        self.gravity = gravity
        self.iters = iters

        sz = (N + 2, N + 2)
        self.u = np.zeros(sz)           # x-velocity
        self.v = np.zeros(sz)           # y-velocity
        self.u_force = np.zeros(sz)     # accumulated x-force (cleared each step)
        self.v_force = np.zeros(sz)     # accumulated y-force (cleared each step)

        self.obstacles: np.ndarray = np.zeros(sz, dtype=bool)  # True = solid

        self.dyes: List[DyeChannel] = []
        self.frame: int = 0

    def add_dye(self, color: Tuple[float, float, float]) -> DyeChannel:
        ch = DyeChannel.make(self.N, color)
        self.dyes.append(ch)
        return ch

    # ------------------------------------------------------------------
    # Injection helpers (call before step())
    # ------------------------------------------------------------------

    def inject_velocity(self, cx: float, cy: float, radius: float,
                        vx: float, vy: float) -> None:
        """Add (vx, vy) impulse in a circular region centred at (cx, cy) in [0,1]."""
        N = self.N
        i0, j0 = int(cx * N) + 1, int(cy * N) + 1
        r = max(1, int(radius * N))
        I = np.arange(max(1, i0 - r), min(N, i0 + r + 1))
        J = np.arange(max(1, j0 - r), min(N, j0 + r + 1))
        II, JJ = np.meshgrid(I, J, indexing='ij')
        dist2 = (II - i0) ** 2 + (JJ - j0) ** 2
        mask = dist2 <= r * r
        self.u_force[II[mask], JJ[mask]] += vx
        self.v_force[II[mask], JJ[mask]] += vy

    def inject_dye(self, channel: int, cx: float, cy: float, radius: float,
                   amount: float = 1.0) -> None:
        N = self.N
        i0, j0 = int(cx * N) + 1, int(cy * N) + 1
        r = max(1, int(radius * N))
        I = np.arange(max(1, i0 - r), min(N, i0 + r + 1))
        J = np.arange(max(1, j0 - r), min(N, j0 + r + 1))
        II, JJ = np.meshgrid(I, J, indexing='ij')
        dist2 = (II - i0) ** 2 + (JJ - j0) ** 2
        mask = dist2 <= r * r
        self.dyes[channel].source[II[mask], JJ[mask]] += amount

    def add_obstacle_rect(self, x0: float, y0: float,
                          x1: float, y1: float) -> None:
        """Mark rectangle [x0,x1]×[y0,y1] (in [0,1]) as solid."""
        N = self.N
        i0, i1 = int(x0 * N) + 1, int(x1 * N) + 2
        j0, j1 = int(y0 * N) + 1, int(y1 * N) + 2
        self.obstacles[i0:i1, j0:j1] = True

    def add_obstacle_circle(self, cx: float, cy: float, r: float) -> None:
        N = self.N
        I = np.arange(N + 2)
        J = np.arange(N + 2)
        II, JJ = np.meshgrid(I, J, indexing='ij')
        ic, jc = cx * N + 1, cy * N + 1
        self.obstacles[((II - ic) ** 2 + (JJ - jc) ** 2) <= (r * N) ** 2] = True

    # ------------------------------------------------------------------
    # Main step
    # ------------------------------------------------------------------

    def step(self) -> None:
        N, dt = self.N, self.dt

        # --- velocity step ---
        u = self.u + dt * self.u_force
        v = self.v + dt * self.v_force + dt * self.gravity  # gravity acts downward (−y)

        # Apply body force sign: gravity > 0 pulls in −y direction
        # We'll add −gravity to v (positive gravity = downward in screen coords)

        if self.visc > 0.0:
            u = _diffuse(N, u, self.visc, dt, 1, self.iters)
            v = _diffuse(N, v, self.visc, dt, 2, self.iters)
            _apply_obstacles_vel(u, v, self.obstacles)

        u, v = _project(N, u, v, self.iters)

        u_adv = _advect(N, u, u, v, dt, 1)
        v_adv = _advect(N, v, u, v, dt, 2)
        _apply_obstacles_vel(u_adv, v_adv, self.obstacles)

        u_adv, v_adv = _project(N, u_adv, v_adv, self.iters)

        if self.vort_scale > 0.0:
            u_adv, v_adv = _vorticity_confinement(N, u_adv, v_adv, dt, self.vort_scale)
            _apply_obstacles_vel(u_adv, v_adv, self.obstacles)

        self.u[:] = u_adv
        self.v[:] = v_adv
        self.u_force[:] = 0.0
        self.v_force[:] = 0.0

        # --- dye step ---
        for dye in self.dyes:
            d = dye.density + dt * dye.source
            dye.source[:] = 0.0
            if self.diff > 0.0:
                d = _diffuse(N, d, self.diff, dt, 0, self.iters)
            d = _advect(N, d, self.u, self.v, dt, 0)
            d[self.obstacles] = 0.0
            dye.density[:] = np.maximum(0.0, d)

        self.frame += 1

    # ------------------------------------------------------------------
    # Diagnostics
    # ------------------------------------------------------------------

    def divergence_rms(self) -> float:
        """
        RMS of the raw discrete divergence sum that _project drives to zero.
        Value is in grid units: (u[i+1]-u[i-1] + v[j+1]-v[j-1]) * 0.5 * h,
        which should be <<1 after projection (typically 1e-3 to 1e-5).
        """
        N, h = self.N, 1.0 / self.N
        div = -0.5 * h * (
            self.u[2:, 1:-1] - self.u[:-2, 1:-1] +
            self.v[1:-1, 2:] - self.v[1:-1, :-2]
        )
        return float(np.sqrt(np.mean(div ** 2)))

    def dye_mass(self) -> List[float]:
        return [float(d.density[1:-1, 1:-1].sum()) for d in self.dyes]

    def velocity_stats(self) -> dict:
        speed = np.sqrt(self.u[1:-1, 1:-1] ** 2 + self.v[1:-1, 1:-1] ** 2)
        return {"max": float(speed.max()), "mean": float(speed.mean()),
                "divergence_rms": self.divergence_rms()}

    def vorticity(self) -> np.ndarray:
        """Scalar vorticity field (curl z-component), raw finite differences."""
        N = self.N
        omega = np.zeros((N + 2, N + 2))
        omega[1:-1, 1:-1] = 0.5 * (
            self.v[2:, 1:-1] - self.v[:-2, 1:-1] -
            self.u[1:-1, 2:] + self.u[1:-1, :-2]
        )
        return omega

    def reset(self) -> None:
        sz = (self.N + 2, self.N + 2)
        self.u[:] = 0.0
        self.v[:] = 0.0
        self.u_force[:] = 0.0
        self.v_force[:] = 0.0
        for dye in self.dyes:
            dye.density[:] = 0.0
            dye.source[:] = 0.0
        self.frame = 0


# ---------------------------------------------------------------------------
# Core solver functions (module-level, vectorised numpy)
# ---------------------------------------------------------------------------

def _set_bnd(N: int, b: int, x: np.ndarray) -> None:
    """Enforce boundary conditions on array x.
    b=0: scalar, b=1: x-velocity, b=2: y-velocity.
    """
    # Edges
    if b == 1:
        x[0, 1:-1]  = -x[1, 1:-1]
        x[-1, 1:-1] = -x[-2, 1:-1]
        x[1:-1, 0]  =  x[1:-1, 1]
        x[1:-1, -1] =  x[1:-1, -2]
    elif b == 2:
        x[0, 1:-1]  =  x[1, 1:-1]
        x[-1, 1:-1] =  x[-2, 1:-1]
        x[1:-1, 0]  = -x[1:-1, 1]
        x[1:-1, -1] = -x[1:-1, -2]
    else:
        x[0, 1:-1]  =  x[1, 1:-1]
        x[-1, 1:-1] =  x[-2, 1:-1]
        x[1:-1, 0]  =  x[1:-1, 1]
        x[1:-1, -1] =  x[1:-1, -2]
    # Corners
    x[0,  0]  = 0.5 * (x[1, 0]  + x[0,  1])
    x[0, -1]  = 0.5 * (x[1, -1] + x[0, -2])
    x[-1,  0] = 0.5 * (x[-2, 0] + x[-1,  1])
    x[-1, -1] = 0.5 * (x[-2, -1]+ x[-1, -2])


def _diffuse(N: int, x_prev: np.ndarray, diff: float, dt: float,
             b: int, iters: int) -> np.ndarray:
    """Implicit diffusion via Gauss-Seidel iteration."""
    a = dt * diff * N * N
    x = x_prev.copy()
    for _ in range(iters):
        x[1:-1, 1:-1] = (
            x_prev[1:-1, 1:-1] + a * (
                x[:-2, 1:-1] + x[2:, 1:-1] +
                x[1:-1, :-2] + x[1:-1, 2:]
            )
        ) / (1.0 + 4.0 * a)
        _set_bnd(N, b, x)
    return x


def _project(N: int, u: np.ndarray, v: np.ndarray,
             iters: int) -> Tuple[np.ndarray, np.ndarray]:
    """Remove divergence from (u, v) using a pressure correction."""
    h = 1.0 / N
    div = np.zeros_like(u)
    p = np.zeros_like(u)

    # Divergence of velocity
    div[1:-1, 1:-1] = -0.5 * h * (
        u[2:, 1:-1] - u[:-2, 1:-1] +
        v[1:-1, 2:] - v[1:-1, :-2]
    )
    _set_bnd(N, 0, div)

    # Solve ∇²p = div (Gauss-Seidel)
    for _ in range(iters):
        p[1:-1, 1:-1] = (
            div[1:-1, 1:-1] +
            p[:-2, 1:-1] + p[2:, 1:-1] +
            p[1:-1, :-2] + p[1:-1, 2:]
        ) / 4.0
        _set_bnd(N, 0, p)

    # Subtract gradient
    u_new = u.copy()
    v_new = v.copy()
    u_new[1:-1, 1:-1] -= 0.5 * (p[2:, 1:-1] - p[:-2, 1:-1]) / h
    v_new[1:-1, 1:-1] -= 0.5 * (p[1:-1, 2:] - p[1:-1, :-2]) / h
    _set_bnd(N, 1, u_new)
    _set_bnd(N, 2, v_new)
    return u_new, v_new


def _advect(N: int, d: np.ndarray, u: np.ndarray, v: np.ndarray,
            dt: float, b: int) -> np.ndarray:
    """Semi-Lagrangian advection: trace backwards along velocity."""
    dt0 = dt * N
    I = np.arange(1, N + 1)
    J = np.arange(1, N + 1)
    II, JJ = np.meshgrid(I, J, indexing='ij')

    # Trace back
    x = II - dt0 * u[1:-1, 1:-1]
    y = JJ - dt0 * v[1:-1, 1:-1]

    # Clamp to interior
    x = np.clip(x, 0.5, N + 0.5)
    y = np.clip(y, 0.5, N + 0.5)

    # Floor indices
    i0 = x.astype(np.int32)
    j0 = y.astype(np.int32)
    i1 = i0 + 1
    j1 = j0 + 1

    # Fractional weights
    s1 = x - i0
    s0 = 1.0 - s1
    t1 = y - j0
    t0 = 1.0 - t1

    # Bilinear interpolation
    d_new = np.zeros_like(d)
    d_new[1:-1, 1:-1] = (
        s0 * (t0 * d[i0, j0] + t1 * d[i0, j1]) +
        s1 * (t0 * d[i1, j0] + t1 * d[i1, j1])
    )
    _set_bnd(N, b, d_new)
    return d_new


def _vorticity_confinement(N: int, u: np.ndarray, v: np.ndarray,
                           dt: float, scale: float) -> Tuple[np.ndarray, np.ndarray]:
    """
    Fedkiw et al. vorticity confinement: restores dissipated turbulence.

    Uses raw (un-scaled) finite differences for curl and its gradient so that
    `scale` is a dimensionless confinement strength in [0, 10].  Values ≥ 10
    will add vortex-ring-like structures; values 1–5 are typical.
    """
    # Curl (z-component) — raw central differences, no N factor
    omega = np.zeros((N + 2, N + 2))
    omega[1:-1, 1:-1] = 0.5 * (
        v[2:, 1:-1] - v[:-2, 1:-1] -
        u[1:-1, 2:] + u[1:-1, :-2]
    )

    # Gradient of |omega| — raw central differences
    mag = np.abs(omega)
    dw_dx = np.zeros_like(u)
    dw_dy = np.zeros_like(v)
    dw_dx[1:-1, 1:-1] = 0.5 * (mag[2:, 1:-1] - mag[:-2, 1:-1])
    dw_dy[1:-1, 1:-1] = 0.5 * (mag[1:-1, 2:] - mag[1:-1, :-2])

    # Normalised eta vector (points from low to high vorticity)
    norm = np.sqrt(dw_dx ** 2 + dw_dy ** 2) + 1e-5
    nx = dw_dx / norm
    ny = dw_dy / norm

    # Confinement force: f = scale × (eta × omega)
    # In 2D: f_x = +ny × omega, f_y = −nx × omega
    u_new = u.copy()
    v_new = v.copy()
    u_new[1:-1, 1:-1] += scale * dt * ny[1:-1, 1:-1] * omega[1:-1, 1:-1]
    v_new[1:-1, 1:-1] -= scale * dt * nx[1:-1, 1:-1] * omega[1:-1, 1:-1]
    _set_bnd(N, 1, u_new)
    _set_bnd(N, 2, v_new)
    return u_new, v_new


def _apply_obstacles_vel(u: np.ndarray, v: np.ndarray,
                         obstacles: np.ndarray) -> None:
    """Zero velocity inside solid cells (no-slip boundary)."""
    u[obstacles] = 0.0
    v[obstacles] = 0.0
