"""
Gray-Scott reaction-diffusion solver.

   ∂U/∂t = Du·∇²U - U·V² + F·(1-U)
   ∂V/∂t = Dv·∇²V + U·V² - (F+k)·V

Uses numpy if available (fast); falls back to pure-Python (slower but correct).
"""
import math
import random as _random

try:
    import numpy as np
    _HAS_NUMPY = True
except ImportError:
    _HAS_NUMPY = False

# ── parameter presets ─────────────────────────────────────────────────────────

PRESETS = {
    "coral": {
        "Du": 0.16, "Dv": 0.08, "F": 0.060, "k": 0.062,
        "description": "Coral-like branching",
    },
    "mitosis": {
        "Du": 0.19, "Dv": 0.05, "F": 0.060, "k": 0.062,
        "description": "Cell-division / mitosis blobs",
    },
    "worms": {
        "Du": 0.16, "Dv": 0.08, "F": 0.050, "k": 0.065,
        "description": "Worm-like intertwined patterns",
    },
    "maze": {
        "Du": 0.16, "Dv": 0.08, "F": 0.029, "k": 0.057,
        "description": "Labyrinthine maze",
    },
    "spots": {
        "Du": 0.16, "Dv": 0.08, "F": 0.035, "k": 0.065,
        "description": "Leopard-like spots",
    },
    "fingerprint": {
        "Du": 0.19, "Dv": 0.05, "F": 0.060, "k": 0.058,
        "description": "Fingerprint / contour lines",
    },
}

PRESET_NAMES = sorted(PRESETS.keys())


# ── numpy solver ──────────────────────────────────────────────────────────────

def _solve_numpy(U, V, Du, Dv, F, k, steps, dt=1.0):
    """In-place Gray-Scott integration using numpy."""
    for _ in range(steps):
        # Discrete 5-point Laplacian with wrap-around
        laplace_U = (
            np.roll(U, 1, axis=0) + np.roll(U, -1, axis=0) +
            np.roll(U, 1, axis=1) + np.roll(U, -1, axis=1) -
            4 * U
        )
        laplace_V = (
            np.roll(V, 1, axis=0) + np.roll(V, -1, axis=0) +
            np.roll(V, 1, axis=1) + np.roll(V, -1, axis=1) -
            4 * V
        )
        uvv = U * V * V
        U += dt * (Du * laplace_U - uvv + F * (1 - U))
        V += dt * (Dv * laplace_V + uvv - (F + k) * V)
    return U, V


# ── pure-Python solver ────────────────────────────────────────────────────────

def _solve_python(U, V, Du, Dv, F, k, steps, dt=1.0, W=None, H=None):
    """
    Pure-Python fallback — correct but slow for large grids.

    NOTE: This uses Gauss-Seidel style in-place updates (each cell's Laplacian
    reads already-updated neighbours earlier in the row scan). This differs from
    the explicit-Euler numpy path, so the same seed produces slightly different
    patterns. Both converge to valid RD textures.
    """
    rows = H or len(U)
    cols = W or (len(U[0]) if hasattr(U[0], '__len__') else len(U) // rows)
    for _ in range(steps):
        for r in range(rows):
            rp = (r + 1) % rows
            rm = (r - 1) % rows
            for c in range(cols):
                cp = (c + 1) % cols
                cm = (c - 1) % cols
                u = U[r][c]; v = V[r][c]
                lu = U[rp][c] + U[rm][c] + U[r][cp] + U[r][cm] - 4 * u
                lv = V[rp][c] + V[rm][c] + V[r][cp] + V[r][cm] - 4 * v
                uvv = u * v * v
                U[r][c] += dt * (Du * lu - uvv + F * (1 - u))
                V[r][c] += dt * (Dv * lv + uvv - (F + k) * v)
    return U, V


# ── public API ────────────────────────────────────────────────────────────────

def simulate(
    preset_name=None,
    Du=0.16, Dv=0.08, F=0.060, k=0.062,
    width=200, height=200,
    steps=5000,
    seed=None,
    noise_level=0.05,
):
    """
    Run the Gray-Scott simulation.

    Returns (V_field, width, height) where V_field is a flat list of floats
    in [0,1], row-major, representing the V concentration.
    """
    rng = _random.Random(seed)

    if preset_name is not None:
        if preset_name not in PRESETS:
            raise ValueError(f"Unknown preset '{preset_name}'. "
                             f"Available: {PRESET_NAMES}")
        p = PRESETS[preset_name]
        Du, Dv, F, k = p["Du"], p["Dv"], p["F"], p["k"]

    # Build initial noise grid (same RNG draw order for both paths)
    cx, cy = width // 2, height // 2
    patch_r = max(5, min(width, height) // 10)
    noise_u = [[rng.gauss(0, noise_level) for _ in range(width)] for _ in range(height)]
    noise_v = [[rng.gauss(0, noise_level) for _ in range(width)] for _ in range(height)]

    if _HAS_NUMPY:
        U = np.ones((height, width), dtype=np.float64)
        V = np.zeros((height, width), dtype=np.float64)
        # Seed a square patch in the centre
        U[cy - patch_r:cy + patch_r, cx - patch_r:cx + patch_r] = 0.5
        V[cy - patch_r:cy + patch_r, cx - patch_r:cx + patch_r] = 0.25
        # Add noise to all cells (same as pure-Python path)
        U += np.array(noise_u)
        V += np.array(noise_v)
        np.clip(U, 0, 1, out=U)
        np.clip(V, 0, 1, out=V)
        U, V = _solve_numpy(U, V, Du, Dv, F, k, steps)
        flat_v = V.flatten().tolist()
    else:
        # Pure-Python path — same initialisation as numpy path
        U = [[max(0.0, min(1.0, 1.0 + noise_u[row][col])) for col in range(width)]
             for row in range(height)]
        V = [[max(0.0, min(1.0, 0.0 + noise_v[row][col])) for col in range(width)]
             for row in range(height)]
        for row in range(cy - patch_r, cy + patch_r):
            for col in range(cx - patch_r, cx + patch_r):
                if 0 <= row < height and 0 <= col < width:
                    U[row][col] = max(0.0, min(1.0, 0.5 + noise_u[row][col]))
                    V[row][col] = max(0.0, min(1.0, 0.25 + noise_v[row][col]))
                    V[row][col] = max(0.0, min(1.0, V[row][col]))
        U, V = _solve_python(U, V, Du, Dv, F, k, steps, W=width, H=height)
        flat_v = [V[r][c] for r in range(height) for c in range(width)]

    return flat_v, width, height


def field_to_pixels(flat_v, width, height, palette_fn):
    """Convert flat V field to list of (r,g,b) pixels using a palette function."""
    vmin = min(flat_v)
    vmax = max(flat_v)
    span = vmax - vmin or 1.0
    pixels = []
    for v in flat_v:
        t = (v - vmin) / span
        pixels.append(palette_fn(t))
    return pixels
