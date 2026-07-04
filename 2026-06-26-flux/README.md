# Flux — 2D Navier-Stokes Fluid Simulation

Real-time 2D fluid simulation implementing Stam's Stable Fluids (1999).
Three ways to run it: interactive browser playground, Python batch renderer, or command-line tool.

## What it does

- **Incompressible Navier-Stokes** via semi-Lagrangian advection + implicit diffusion + pressure projection — unconditionally stable at any timestep
- **Vorticity confinement** (Fedkiw 2001) — restores small-scale swirls that numerical diffusion would otherwise damp
- **Solid obstacles** — rectangular and circular, enforced every step
- **Multiple dye channels** — each with its own colour, advected independently
- **Gravity / buoyancy** — signed body force on the y-velocity
- **Five built-in scenes**: smoke plumes, ink drops, Kármán vortex street, vortex pair, fire
- **JSON scene format** — define custom obstacles, timed injections, and parameters without touching Python
- **Interactive HTML playground** (`flux.html`) — runs entirely in the browser, no server needed
- **Python CLI** — batch render to PNG frames or self-contained HTML animations

## Quick start

### Interactive browser

Open `flux.html` in any modern browser. Pick a scene from the dropdown, drag to inject dye and velocity, right-click to draw obstacles, adjust vorticity/gravity sliders.

### Run the demo

```bash
bash demo.sh          # tests + renders all scenes → demo_output/index.html
```

### CLI usage

```bash
# Render scene to PNG frames
python3 cli.py render --scene smoke --N 64 --frames 100 --mode composite --output frames/

# Render to a self-contained HTML animation
python3 cli.py anim   --scene wind  --N 128 --frames 200 --output wind.html

# Render all built-in scenes to an HTML gallery
python3 cli.py demo   --N 64 --frames 60 --output gallery/

# Print scene parameters
python3 cli.py info   --scene fire

# Load a custom JSON scene
python3 cli.py anim   --scene example_scene.json --frames 100
```

### CLI options

| Flag | Default | Description |
|------|---------|-------------|
| `--scene` | `smoke` | Built-in name or path to `.json` |
| `--N` | 64 | Grid resolution (N×N interior cells) |
| `--frames` | scene default | Number of frames to render |
| `--skip` | 0 | Pre-warm frames (run but don't save) |
| `--mode` | `composite` | Render mode: `dye` `speed` `vorticity` `composite` `fire` |
| `--scale` | 4 | Pixel scale factor |

## JSON scene format

```json
{
  "name": "my_scene",
  "N": 64,
  "dt": 0.15,
  "visc": 0.0,
  "diff": 0.0,
  "vort_scale": 3.0,
  "gravity": -0.08,
  "dyes": [
    {"color": [0.3, 0.7, 1.0]},
    {"color": [1.0, 0.4, 0.1]}
  ],
  "obstacles": [
    {"type": "rect",   "x0": 0.3, "y0": 0.4, "x1": 0.7, "y1": 0.6},
    {"type": "circle", "cx": 0.5, "cy": 0.5, "r": 0.1}
  ],
  "injections": [
    {
      "frames": [0, 200],
      "dye": 0,
      "cx": 0.05, "cy": 0.5, "radius": 0.06, "amount": 1.5,
      "vx": 2.5, "vy": 0.0
    }
  ],
  "frames": 150,
  "description": "Custom scene"
}
```

Coordinates are normalised to [0, 1]. `cx`/`cy` use the same convention as the display: x=0 is left, y=0 is top, y=1 is bottom. Gravity `< 0` is buoyancy (upward). See `example_scene.json` for a channel-flow example.

## Algorithm

```
step():
  1. Add body forces (gravity → v, user impulses → u_force/v_force)
  2. Optional viscous diffusion (implicit Gauss-Seidel)
  3. Pressure projection → divergence-free velocity
  4. Semi-Lagrangian self-advection of velocity
  5. Zero velocity in obstacles
  6. Second pressure projection
  7. Optional vorticity confinement (Fedkiw 2001)
  8. Advect dye channels
```

The solver uses a vectorised Jacobi iteration (20 iterations by default) for both diffusion and the pressure Poisson solve. div_rms stays below 0.002 after projection. All scenes run stably for 200+ steps at N=64 with no NaN or overflow.

## Performance

| Resolution | Python (numpy) |
|------------|---------------|
| N=32       | ~350 fps       |
| N=64       | ~160 fps       |
| N=128      | ~50 fps        |

The browser (`flux.html`) runs at 60 fps for N=128 on a modern laptop.

## File layout

```
flux.html              Interactive browser playground (self-contained)
fluid.py               Core Navier-Stokes solver
render.py              PNG encoder + colourmap renderers
scenes.py              Five built-in scenes + JSON loader
cli.py                 Command-line interface
tests.py               Test suite (47 checks)
demo.sh                Runs tests + renders all scenes
example_scene.json     Channel-flow JSON scene
PLAN.md                Architecture notes
REVIEW.md              Adversarial review findings (5 bugs found & fixed)
```

## Known limitations

1. **Jacobi not Gauss-Seidel** — the vectorised pressure solve is technically Jacobi. Convergence rate ~1.6× per 20 iters. A multigrid solver would converge faster but is out of scope for visual simulation.
2. **Copy-nearest boundary** — domain edges use "copy-nearest" BCs, not outflow Neumann. Causes slight back-pressure at outflow boundaries (most visible in the wind scene).
3. **Single-threaded** — at N=256+ Python becomes the bottleneck. A C extension or GPU port would be needed for high-resolution real-time use.

## Why

This is a daily build project demonstrating that a numerically correct, physically meaningful fluid simulation can be written from scratch in ~600 lines of Python + 300 lines of vanilla JS with no external dependencies beyond numpy.
