"""
Flux built-in scenes.

Each scene is a function that returns (fluid, injection_fn, metadata).
injection_fn(frame) mutates fluid for that frame (add forces/dye).
"""

import math
import numpy as np
from fluid import FluidGrid


def scene_smoke(N: int = 64) -> tuple:
    """
    Upward smoke plume from two sources near the bottom, with turbulence.
    """
    fluid = FluidGrid(N, dt=0.15, visc=0.0, diff=0.0,
                      vort_scale=3.0, gravity=-0.08)
    grey = (0.9, 0.9, 0.9)
    warm = (1.0, 0.7, 0.3)
    ch0 = fluid.add_dye(grey)
    ch1 = fluid.add_dye(warm)

    def inject(frame: int) -> None:
        t = frame * 0.05
        # Two alternating smoke columns
        ox = 0.1 * math.sin(t)
        fluid.inject_dye(0, 0.35 + ox, 0.95, 0.04, amount=1.5)
        fluid.inject_velocity(0.35 + ox, 0.95, 0.04, 0.0, -2.5)

        fluid.inject_dye(1, 0.65 - ox, 0.95, 0.04, amount=1.5)
        fluid.inject_velocity(0.65 - ox, 0.95, 0.04, 0.0, -2.5)

    return fluid, inject, {
        "name": "smoke",
        "description": "Rising smoke plumes with vorticity",
        "frames": 200,
    }


def scene_ink(N: int = 64) -> tuple:
    """
    Coloured ink drops falling in still water — three sources, gravity down.
    """
    fluid = FluidGrid(N, dt=0.1, visc=0.0, diff=0.0,
                      vort_scale=1.5, gravity=0.12)
    colors = [(1.0, 0.15, 0.15), (0.15, 0.6, 1.0), (0.15, 0.95, 0.4)]
    for c in colors:
        fluid.add_dye(c)

    def inject(frame: int) -> None:
        t = frame * 0.04
        # Drop injection at top, slightly wandering
        for i, (cx, cy) in enumerate([(0.3, 0.05), (0.5, 0.05), (0.7, 0.05)]):
            cx2 = cx + 0.04 * math.sin(t + i * 2.1)
            fluid.inject_dye(i, cx2, cy, 0.035, amount=1.2)
            fluid.inject_velocity(cx2, cy, 0.035, 0.0, 1.5)

    return fluid, inject, {
        "name": "ink",
        "description": "Ink drops falling in water",
        "frames": 180,
    }


def scene_wind(N: int = 64) -> tuple:
    """
    Steady horizontal airflow past a circular obstacle. Classic Kármán vortex street.
    """
    fluid = FluidGrid(N, dt=0.15, visc=0.0, diff=0.0,
                      vort_scale=4.0, gravity=0.0)
    fluid.add_obstacle_circle(0.4, 0.5, 0.09)
    ch = fluid.add_dye((0.3, 0.7, 1.0))

    # Prime the flow with a uniform rightward velocity
    fluid.u[:] = 1.5
    _set_bnd_init(fluid)

    def inject(frame: int) -> None:
        # Constant inflow from left edge
        fluid.u[0, 1:-1] = 1.5
        fluid.u[1, 1:-1] = 1.5
        fluid.inject_dye(0, 0.05, 0.5, 0.08, amount=2.0)
        fluid.inject_velocity(0.05, 0.5, 0.08, 2.0, 0.0)
        # Small perturbation to trigger vortex shedding
        if frame == 5:
            fluid.inject_velocity(0.4, 0.52, 0.03, 0.0, 0.5)

    return fluid, inject, {
        "name": "wind",
        "description": "Karman vortex street past a cylinder",
        "frames": 300,
    }


def _set_bnd_init(fluid: FluidGrid) -> None:
    """Zero velocity inside any obstacles after initialisation."""
    fluid.u[fluid.obstacles] = 0.0
    fluid.v[fluid.obstacles] = 0.0


def scene_vortex(N: int = 64) -> tuple:
    """
    Counter-rotating vortex pair: two opposite spin vortices that orbit each other.
    """
    fluid = FluidGrid(N, dt=0.15, visc=0.0, diff=0.0,
                      vort_scale=0.0, gravity=0.0)
    col_a = (1.0, 0.4, 0.1)
    col_b = (0.1, 0.5, 1.0)
    fluid.add_dye(col_a)
    fluid.add_dye(col_b)

    # Seed velocity with two Rankine vortices
    N2 = fluid.N
    I = np.arange(N2 + 2)
    J = np.arange(N2 + 2)
    II, JJ = np.meshgrid(I, J, indexing='ij')
    cx1, cy1 = 0.35 * N2, 0.5 * N2
    cx2, cy2 = 0.65 * N2, 0.5 * N2
    strength = 3.0

    for cx, cy, sign in [(cx1, cy1, 1.0), (cx2, cy2, -1.0)]:
        dx = (II - cx).astype(float)
        dy = (JJ - cy).astype(float)
        r2 = dx ** 2 + dy ** 2 + 0.01
        fluid.u -= sign * strength * dy / r2
        fluid.v += sign * strength * dx / r2

    # Cap to reasonable magnitude
    spd = np.sqrt(fluid.u ** 2 + fluid.v ** 2)
    cap = 5.0
    mask = spd > cap
    fluid.u[mask] = fluid.u[mask] / spd[mask] * cap
    fluid.v[mask] = fluid.v[mask] / spd[mask] * cap

    def inject(frame: int) -> None:
        t = frame * 0.04
        # Continuous dye injection near vortex cores
        fluid.inject_dye(0, 0.35 + 0.01 * math.sin(t * 5), 0.5, 0.06, amount=0.8)
        fluid.inject_dye(1, 0.65 + 0.01 * math.sin(t * 5 + 1), 0.5, 0.06, amount=0.8)

    return fluid, inject, {
        "name": "vortex",
        "description": "Counter-rotating vortex pair",
        "frames": 250,
    }


def scene_fire(N: int = 64) -> tuple:
    """
    Fire simulation: hot gas rises, cools, and curls due to vorticity.
    """
    fluid = FluidGrid(N, dt=0.12, visc=0.0, diff=0.0,
                      vort_scale=5.0, gravity=-0.15)
    # Heat channel (yellow/orange) + smoke (grey)
    fluid.add_dye((1.0, 0.5, 0.05))   # hot orange
    fluid.add_dye((0.9, 0.9, 0.9))    # cool smoke

    def inject(frame: int) -> None:
        t = frame * 0.07
        # Flickering burner at bottom centre
        w = 0.06 + 0.02 * math.sin(t * 3.7)
        cx = 0.5 + 0.03 * math.sin(t * 2.1)
        # Hot fast gas
        fluid.inject_dye(0, cx, 0.95, w, amount=2.0)
        fluid.inject_velocity(cx, 0.95, w, 0.0, -4.0)
        # Cooler trailing smoke
        fluid.inject_dye(1, cx, 0.92, w * 0.6, amount=0.5)
        # Slight horizontal turbulence
        fluid.inject_velocity(cx, 0.95, w * 0.5,
                               0.8 * math.sin(t * 7.3), 0.0)

    return fluid, inject, {
        "name": "fire",
        "description": "Fire plume with vorticity confinement",
        "frames": 200,
    }


SCENES = {
    "smoke": scene_smoke,
    "ink":   scene_ink,
    "wind":  scene_wind,
    "vortex": scene_vortex,
    "fire":  scene_fire,
}


def load_json_scene(path: str) -> tuple:
    """
    Load a scene from a JSON file.

    JSON schema:
    {
      "name": "my_scene",
      "N": 64,
      "dt": 0.15,
      "visc": 0.0,
      "diff": 0.0,
      "vort_scale": 3.0,
      "gravity": 0.0,
      "dyes": [{"color": [r, g, b]}, ...],
      "obstacles": [
        {"type": "rect",   "x0": 0.3, "y0": 0.3, "x1": 0.7, "y1": 0.4},
        {"type": "circle", "cx": 0.5, "cy": 0.5, "r": 0.1}
      ],
      "injections": [
        {
          "frames": [0, 200],
          "dye": 0, "cx": 0.5, "cy": 0.1, "radius": 0.04, "amount": 1.0,
          "vx": 0.0, "vy": 2.0
        }
      ],
      "frames": 150,
      "description": "Custom scene"
    }
    """
    import json
    with open(path) as f:
        cfg = json.load(f)

    fluid = FluidGrid(
        N=cfg.get("N", 64),
        dt=cfg.get("dt", 0.15),
        visc=cfg.get("visc", 0.0),
        diff=cfg.get("diff", 0.0),
        vort_scale=cfg.get("vort_scale", 0.0),
        gravity=cfg.get("gravity", 0.0),
    )

    for dye_cfg in cfg.get("dyes", [{"color": [1.0, 1.0, 1.0]}]):
        fluid.add_dye(tuple(dye_cfg["color"]))

    for obs in cfg.get("obstacles", []):
        if obs["type"] == "rect":
            fluid.add_obstacle_rect(obs["x0"], obs["y0"], obs["x1"], obs["y1"])
        elif obs["type"] == "circle":
            fluid.add_obstacle_circle(obs["cx"], obs["cy"], obs["r"])

    injections = cfg.get("injections", [])
    total_frames = cfg.get("frames", 150)

    def inject(frame: int) -> None:
        for inj in injections:
            f0, f1 = inj.get("frames", [0, total_frames])
            if f0 <= frame < f1:
                ch = inj.get("dye", 0)
                if ch < len(fluid.dyes):
                    fluid.inject_dye(ch, inj["cx"], inj["cy"],
                                     inj.get("radius", 0.04),
                                     inj.get("amount", 1.0))
                vx = inj.get("vx", 0.0)
                vy = inj.get("vy", 0.0)
                if vx != 0.0 or vy != 0.0:
                    fluid.inject_velocity(inj["cx"], inj["cy"],
                                          inj.get("radius", 0.04), vx, vy)

    meta = {
        "name": cfg.get("name", path),
        "description": cfg.get("description", "Custom scene"),
        "frames": total_frames,
    }
    return fluid, inject, meta
