"""
Animation helpers for Morphica.

Provides frame-export sequences for:
  - L-system growth (step 0 … N)
  - Reaction-diffusion evolution (snapshots at intervals)
  - Attractor orbit buildup (accumulating histogram frames)
  - Palette cycling (same field, rotating colour map)
"""
import os
import time
import math

from lsystem import rewrite, turtle_to_paths, paths_to_pixels, PRESETS as LS_PRESETS
from reactiondiff import simulate as rd_simulate, field_to_pixels, PRESETS as RD_PRESETS
from attractors import ATTRACTORS, _ORBIT_FNS, _accumulate, _hist_to_pixels
from palette import sample_palette, PALETTES
from png_encoder import save_png


def _ensure(path):
    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)


# ── L-system growth animation ─────────────────────────────────────────────────

def animate_lsystem(
    preset_name,
    max_iter=6,
    width=600,
    height=600,
    stroke="#00CFFF",
    bg_color=(17, 17, 17),
    output_dir=None,
    seed=None,
    verbose=True,
):
    """
    Export one PNG per iteration (0 … max_iter) of an L-system growing.

    Returns list of output file paths.
    """
    import random
    rng = random.Random(seed)

    cfg = LS_PRESETS.get(preset_name)
    if cfg is None:
        raise ValueError(f"Unknown L-system preset '{preset_name}'")
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(__file__), "output",
                                   f"anim_lsystem_{preset_name}")
    os.makedirs(output_dir, exist_ok=True)

    def _hex_to_rgb(h):
        h = h.lstrip("#")
        if len(h) == 3:
            h = h[0]*2 + h[1]*2 + h[2]*2
        return (int(h[0:2],16), int(h[2:4],16), int(h[4:6],16))

    stroke_rgb = _hex_to_rgb(stroke)
    paths_cache = []

    files = []
    string = cfg["axiom"]
    for i in range(max_iter + 1):
        if i > 0:
            string = rewrite(string, cfg["rules"], 1, rng=rng)
        paths, bbox = turtle_to_paths(string, cfg["angle"], cfg.get("step", 5.0))
        # Render
        pixels = [bg_color] * (width * height)
        from lsystem import paths_to_pixels as p2p
        pixels = p2p(paths, bbox, width=width, height=height, bg=bg_color)
        # Tint stroke colour for this frame
        frame_file = os.path.join(output_dir, f"frame_{i:03d}.png")
        save_png(frame_file, width, height, pixels)
        files.append(frame_file)
        if verbose:
            print(f"  Frame {i}/{max_iter} → {frame_file}")
    return files


# ── RD time-lapse animation ───────────────────────────────────────────────────

def animate_rd(
    preset_name="worms",
    total_steps=8000,
    n_frames=10,
    width=200,
    height=200,
    palette_name="viridis",
    output_dir=None,
    seed=None,
    verbose=True,
):
    """
    Export n_frames PNG snapshots of a Gray-Scott simulation evolving.

    The simulation runs `steps_per_frame` steps between each snapshot.
    Returns list of output file paths.
    """
    try:
        import numpy as np
        _has_np = True
    except ImportError:
        _has_np = False

    import random as _rnd
    rng = _rnd.Random(seed)

    from reactiondiff import PRESETS as RDP, _solve_numpy, _solve_python
    if preset_name not in RDP:
        raise ValueError(f"Unknown RD preset '{preset_name}'")
    p = RDP[preset_name]
    Du, Dv, F, k = p["Du"], p["Dv"], p["F"], p["k"]

    noise = 0.05
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(__file__), "output",
                                   f"anim_rd_{preset_name}")
    os.makedirs(output_dir, exist_ok=True)

    steps_per_frame = max(1, total_steps // n_frames)
    pfn = lambda t: sample_palette(palette_name, t)

    if _has_np:
        U = np.ones((height, width), dtype=np.float64)
        V = np.zeros((height, width), dtype=np.float64)
        cx, cy = width // 2, height // 2
        r = max(5, min(width, height) // 10)
        U[cy-r:cy+r, cx-r:cx+r] = 0.5
        V[cy-r:cy+r, cx-r:cx+r] = 0.25
        U += np.array([[rng.gauss(0, noise) for _ in range(width)] for _ in range(height)])
        V += np.array([[rng.gauss(0, noise) for _ in range(width)] for _ in range(height)])
        np.clip(U, 0, 1, out=U); np.clip(V, 0, 1, out=V)
    else:
        U = [[1.0]*width for _ in range(height)]
        V = [[0.0]*width for _ in range(height)]
        cx, cy = width // 2, height // 2
        r = max(5, min(width, height) // 10)
        for row in range(cy-r, cy+r):
            for col in range(cx-r, cx+r):
                if 0 <= row < height and 0 <= col < width:
                    U[row][col] = max(0, min(1, 0.5 + rng.gauss(0, noise)))
                    V[row][col] = max(0, min(1, 0.25 + rng.gauss(0, noise)))

    files = []
    for frame in range(n_frames):
        if _has_np:
            U, V = _solve_numpy(U, V, Du, Dv, F, k, steps_per_frame)
            flat_v = V.flatten().tolist()
        else:
            from reactiondiff import _solve_python
            U, V = _solve_python(U, V, Du, Dv, F, k, steps_per_frame, W=width, H=height)
            flat_v = [V[r][c] for r in range(height) for c in range(width)]

        pixels = field_to_pixels(flat_v, width, height, pfn)
        fname = os.path.join(output_dir, f"frame_{frame:03d}.png")
        save_png(fname, width, height, pixels)
        files.append(fname)
        if verbose:
            print(f"  Frame {frame+1}/{n_frames} ({(frame+1)*steps_per_frame} steps) → {fname}")
    return files


# ── Attractor orbit buildup ───────────────────────────────────────────────────

def animate_attractor(
    name,
    total_steps=500_000,
    n_frames=20,
    width=600,
    height=600,
    palette_name="plasma",
    output_dir=None,
    seed=None,
    verbose=True,
):
    """
    Export n_frames PNG frames of an attractor orbit being drawn incrementally.

    Each frame shows all points accumulated so far.
    Returns list of output file paths.
    """
    if name not in ATTRACTORS:
        raise ValueError(f"Unknown attractor '{name}'")
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(__file__), "output",
                                   f"anim_attractor_{name}")
    os.makedirs(output_dir, exist_ok=True)

    cfg = ATTRACTORS[name]
    orbit_fn = _ORBIT_FNS[name]
    warmup = cfg["warmup"]

    # Generate full orbit first
    xs, ys = orbit_fn(total_steps, warmup, seed)
    pfn = lambda t: sample_palette(palette_name, t)
    bg = (10, 10, 10)

    # Pre-compute global bounding box for consistent framing
    xmin, xmax = min(xs), max(xs)
    ymin, ymax = min(ys), max(ys)
    xspan = xmax - xmin or 1.0
    yspan = ymax - ymin or 1.0
    margin = 20
    aw = width - 2 * margin
    ah = height - 2 * margin

    files = []
    steps_per_frame = max(1, total_steps // n_frames)

    for frame in range(n_frames):
        end = min((frame + 1) * steps_per_frame, total_steps)
        hist = [0] * (width * height)
        for px, py in zip(xs[:end], ys[:end]):
            col = int(margin + (px - xmin) / xspan * aw)
            row = int(margin + (py - ymin) / yspan * ah)
            col = max(margin, min(width - margin - 1, col))
            row = max(margin, min(height - margin - 1, row))
            hist[row * width + col] += 1
        pixels = _hist_to_pixels(hist, pfn, bg=bg)
        fname = os.path.join(output_dir, f"frame_{frame:03d}.png")
        save_png(fname, width, height, pixels)
        files.append(fname)
        if verbose:
            print(f"  Frame {frame+1}/{n_frames} ({end:,} pts) → {fname}")
    return files


# ── Palette cycling ───────────────────────────────────────────────────────────

def animate_palette_cycle(
    field,
    width,
    height,
    palette_names=None,
    n_frames=24,
    output_dir=None,
    verbose=True,
):
    """
    Export n_frames PNG frames cycling through multiple palettes.

    palette_names: list of palette names to cycle through (loops back).
    """
    if palette_names is None:
        palette_names = ["plasma", "viridis", "fire", "ice", "neon", "sunset"]
    if output_dir is None:
        output_dir = os.path.join(os.path.dirname(__file__), "output", "anim_palette")
    os.makedirs(output_dir, exist_ok=True)

    vmin = min(field)
    vmax = max(field)
    span = vmax - vmin or 1.0
    normed = [(v - vmin) / span for v in field]

    n_palettes = len(palette_names)
    files = []
    for frame in range(n_frames):
        # Blend between adjacent palettes
        t = (frame / n_frames) * n_palettes
        pal_idx = int(t) % n_palettes
        pal_next = (pal_idx + 1) % n_palettes
        blend = t - int(t)
        p0 = PALETTES[palette_names[pal_idx]]
        p1 = PALETTES[palette_names[pal_next]]
        pixels = []
        for nv in normed:
            c0 = p0(nv)
            c1 = p1(nv)
            blended = (
                int(c0[0] + (c1[0] - c0[0]) * blend),
                int(c0[1] + (c1[1] - c0[1]) * blend),
                int(c0[2] + (c1[2] - c0[2]) * blend),
            )
            pixels.append(blended)
        fname = os.path.join(output_dir, f"frame_{frame:03d}.png")
        save_png(fname, width, height, pixels)
        files.append(fname)
        if verbose:
            p_name = palette_names[pal_idx]
            print(f"  Frame {frame+1}/{n_frames} (palette ~{p_name}) → {fname}")
    return files
