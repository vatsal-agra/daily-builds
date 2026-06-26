# Flux — 2D Fluid Simulation

## Concept

A real-time 2D fluid simulation implementing Jos Stam's Stable Fluids algorithm
(1999) — the same core technique used in game engines, visual effects, and
weather modeling. Stam's key insight is to solve the Navier-Stokes equations
*unconditionally stably* by treating advection semi-Lagrangian (trace backwards
along the velocity field) and solving diffusion implicitly. The result stays
stable at any timestep, unlike explicit methods that blow up unless dt is tiny.

The simulation runs on an N×N grid where each cell carries a 2D velocity vector
and any number of dye (color) scalars. Every frame:
1. **Diffuse** velocity (viscosity), solve implicitly via Gauss-Seidel
2. **Project** to enforce incompressibility (pressure correction via Poisson solve)
3. **Advect** velocity semi-Lagrangian (each cell looks backwards along flow)
4. **Project** again to kill any advection-induced divergence
5. **Advect** dye fields along the now-clean velocity

The HTML playground runs the same algorithm in 60 fps JavaScript; the Python
backend batch-renders to PNG frames and HTML animation galleries.

## Why it's interesting

- It's physically plausible: buoyancy, vortices, diffusion, pressure waves all
  emerge naturally from a ~200-line solver
- The projection step (pressure solve) is the same Poisson equation that
  appears in electrostatics, heat flow, and gravitational potential
- The vorticity confinement trick (Fedkiw 2001) shows how numerical diffusion
  destroys real turbulence, and how a simple correction term restores it
- Solid obstacles require only boundary-condition changes — the same solver
  handles arbitrary geometry

## Architecture

```
2026-06-26-flux/
├── fluid.py        # FluidGrid class: NS solver (numpy, vectorized)
├── render.py       # colormap + PNG encoder (stdlib only, no Pillow)
├── scenes.py       # 5 predefined demo scenes with injection schedules
├── cli.py          # argparse CLI: render / anim / demo / info
├── tests.py        # 8 test groups covering physics + CLI
├── demo.sh         # one-shot end-to-end verification script
└── flux.html       # self-contained 60fps JS playground + UI
```

### Data model

`FluidGrid(N, dt, visc, diff, vort_scale, gravity)`
- `u`, `v`: velocity arrays, shape (N+2, N+2), first index = x, second = y
- `dyes`: list of `DyeChannel(color_rgb, density)`
- `obstacles`: boolean mask (N+2, N+2), True = solid cell

### Core operations (all vectorized numpy)

| Operation | Formula | Purpose |
|-----------|---------|---------|
| `diffuse` | `(I - a∇²)x = x_prev` solved by Gauss-Seidel | viscosity / molecular diffusion |
| `project` | `∇²p = ∇·u`, then `u -= ∇p` | enforce incompressibility |
| `advect`  | `d_new[i,j] = d_prev[x(t-dt)]` bilinear | semi-Lagrangian transport |
| `vort_conf` | `f = ε(N×ω)/|N×ω| · |ω|` | restore turbulence |

### Boundary conditions

`set_bnd(b, x)`:
- **b=1** (x-velocity): reflect at x-walls, copy at y-walls
- **b=2** (y-velocity): copy at x-walls, reflect at y-walls
- **b=0** (scalar): copy nearest interior cell at all walls

Obstacles: additional reflection/zeroing inside solid cells after each operation.

### HTML/JS playground

Single self-contained HTML file (~600 lines) with:
- Flat `Float32Array` grid (same indexing as Python)
- `requestAnimationFrame` loop: simulate N substeps → render ImageData
- Mouse down+drag: inject velocity (tangent to motion) + dye
- Color: cycling HSV hue per stroke, blended on density canvas
- Colormaps: Dye, Speed, Vorticity, Fire (selectable)
- Presets dropdown: Smoke, Ink, Wind, Vortex, Fire
- Controls: viscosity, diffusion, vortex confinement, gravity sliders
- Reset, Pause, Screenshot buttons

## Feature List

### Required (4)

1. **Stable NS Solver** — semi-Lagrangian advection + implicit diffusion +
   iterative pressure projection (Gauss-Seidel, 20 iters). Velocity field
   remains divergence-free to machine precision after each project step.

2. **Multi-channel Dye Advection** — up to 3 independent RGB dye channels,
   each advected by the shared velocity field. Channels blend additively for
   color mixing. Density is conserved by advection (mass checked in tests).

3. **Interactive HTML Playground** — self-contained single file, 60 FPS Canvas
   rendering, mouse injection, colormap switching, preset scenes, parameter
   sliders, no external dependencies.

4. **Python CLI Batch Renderer** — `flux render`, `flux anim`, `flux demo`:
   renders PNG frames or an HTML animation gallery for any scene. Five built-in
   scenes with parameterized injection schedules.

### Stretch (3)

5. **Vorticity Confinement** — Fedkiw's correction force that computes the
   gradient of |curl(u)| and applies a restoring force to amplify vortical
   structures. Controllable scale; can be toggled on/off.

6. **Solid Obstacles** — Boolean obstacle mask. The solver enforces zero normal
   velocity at obstacle boundaries and zero dye density inside obstacles.
   Fluid flows around shapes naturally from pressure alone.

7. **JSON Scene Format** — `flux render --scene my_scene.json` loads a custom
   scene: grid size, parameters, obstacle list, and a timed injection schedule.
   `flux info --scene my_scene.json` describes the scene without rendering.

## Implementation Notes

- Grid size N=128 is default for interactive HTML; N=64 for fast CLI demos
- All numpy operations are vectorized; no Python loops over grid cells
- PNG encoder is hand-rolled (zlib + raw filter bytes); no Pillow dependency
- The JS solver uses the exact same algorithm with Float32Arrays and manual IX()
- Gauss-Seidel iters: 20 for diffuse, 20 for project (standard Stam values)
- dt=0.15 by default — large enough for visible motion, small enough for stability
