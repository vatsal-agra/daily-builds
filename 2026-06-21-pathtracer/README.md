# Pathtracer — Daily Build 2026-06-21

> Status: **Phase 4 — Stretch + Polish complete**

A Monte Carlo path tracer written from scratch in **pure Python 3** (stdlib only — no NumPy, no Pillow).

## Features

### Core (Phase 2)
- **Recursive Monte Carlo path tracing** with configurable max depth and Russian roulette termination
- **Three PBR materials**: Lambertian (cosine-weighted hemisphere), Metal (mirror + roughness), Dielectric (Snell's law + Fresnel-Schlick)
- **Area lights** via DiffuseLight material — produces soft shadows and color bleeding
- **BVH acceleration** with SAH (Surface Area Heuristic) construction — 6–7× faster than brute-force on 100+ sphere scenes
- **Thin-lens camera** with aperture and focus distance for depth-of-field blur
- **Three textures**: solid color, checkerboard, Perlin gradient noise (marble/wood patterns)
- **Fork-based parallel rendering** via `multiprocessing.Pool` — tiles distributed across CPU cores
- **Hand-rolled PNG encoder** using stdlib `zlib` (Sub filter, CRC-32, IHDR/IDAT/IEND)
- **Four built-in scenes**: classic spheres, Cornell box (with color bleeding), DoF demo, 100-sphere random field

### Stretch (Phase 4)
- **Progressive browser viewer** — live tile-by-tile preview via Server-Sent Events (SSE) on `<canvas>`
- **Complete CLI**: `render`, `demo`, `bench`, `info`, `view` subcommands
- **Benchmark mode** — compares BVH vs brute-force and reports speedup
- **Random-sphere scene generator** (`gen_random_spheres.py`) producing scenes with hundreds of spheres

## Quick Start

```bash
cd 2026-06-21-pathtracer
pip install -e .          # or: python3 -m pathtracer <subcommand>

# Render the classic three-sphere scene
python3 -m pathtracer render scenes/spheres_classic.json -o out.png

# Render all built-in scenes at small size
python3 -m pathtracer demo --outdir renders/

# Run the BVH vs brute-force benchmark
python3 -m pathtracer bench --count 200

# Print scene metadata
python3 -m pathtracer info scenes/cornell_box.json

# Progressive live preview in browser (navigate to http://127.0.0.1:8080/)
python3 -m pathtracer view scenes/dof_demo.json --spp 64 --port 8080
```

## Architecture

```
pathtracer/
  vec3.py        — Vec3, reflect/refract/schlick, cosine hemisphere sampling
  ray.py         — Ray(origin, direction)
  textures.py    — SolidTexture, CheckerTexture, PerlinTexture
  materials.py   — Lambertian, Metal, Dielectric, DiffuseLight
  shapes.py      — Sphere, Box, Plane, Triangle, HittableList, AABB
  bvh.py         — BVHNode with SAH construction
  camera.py      — thin-lens Camera
  scene.py       — JSON scene loader
  renderer.py    — tile-parallel renderer with Russian roulette
  png_writer.py  — hand-rolled PNG + PPM output
  cli.py         — argparse CLI (render/demo/bench/info/view)
  viewer.py      — SSE progressive browser viewer

scenes/
  spheres_classic.json   — 3 spheres, checker ground
  cornell_box.json       — Cornell box with color bleeding
  dof_demo.json          — depth-of-field demo
  random_spheres.json    — 100 random spheres
  gen_random_spheres.py  — generator for N-sphere scenes
```

## Scene JSON Format

```json
{
  "width": 400, "height": 225, "spp": 64, "max_depth": 10,
  "camera": {
    "look_from": [13, 2, 3], "look_at": [0, 0, 0], "up": [0, 1, 0],
    "vfov": 20, "aperture": 0.1, "focus_dist": 10.0
  },
  "background": {"type": "gradient", "top": [0.5, 0.7, 1.0], "bottom": [1.0, 1.0, 1.0]},
  "objects": [
    {
      "type": "sphere", "center": [0, 0, -1], "radius": 0.5,
      "material": {"type": "lambertian", "albedo": {"type": "solid", "color": [0.1, 0.2, 0.5]}}
    }
  ]
}
```

**Object types**: `sphere`, `box`, `plane`, `triangle`  
**Material types**: `lambertian`, `metal`, `dielectric`, `diffuse_light`  
**Texture types**: `solid`, `checker`, `perlin`  
**Background types**: `gradient`, `solid`, `black`

## Phase Log

| Phase | Status | Description |
|-------|--------|-------------|
| 1 — PLAN | ✓ | Architecture, feature list, scope |
| 2 — CORE BUILD | ✓ | Full path tracer, BVH, 4 scenes rendering |
| 3 — ADVERSARIAL REVIEW | ✓ | 5 bugs found & fixed |
| 4 — STRETCH + POLISH | ✓ | Progressive viewer, CLI polish, bench, random scene gen |
| 5 — VERIFICATION | ✓ | 113/113 tests green; demo.sh exercises all CLI subcommands |
| 6 — SHIP | ✓ | Final README + LEDGER entry |

## Bugs Fixed in Review (Phase 3)

1. **Hollow glass sphere** — negative-radius normals were inverted, causing incorrect IOR direction
2. **spp=0 crash** — division by zero on degenerate scene JSON; clamped to ≥1
3. **Box inside-box miss** — Box.hit() returned None for ray origins inside the box; fixed with exit-face fallback
4. **schlick() unbounded** — cosine could exceed 1.0 on grazing angles; added `max(0, min(1, cosine))`
5. **Metal scatter unnormalized** — `(reflected + fuzz)` not normalized, leading to direction drift

## Why This?

Monte Carlo path tracing is one of those algorithms that produces stunning results from a small number of physical principles. The implementation in pure Python is deliberately a learning artifact — every line is readable and traceable without a graphics library abstracting away the math. The BVH + parallel tile renderer pushes it into "renders a useful image in a few seconds" territory despite Python's speed.

## Where to Take It Next

- Port the inner loop to Cython, C extension, or PyPy for 10–100× speedup
- Add a GLTF/OBJ mesh loader and triangle-mesh BVH
- Implement MIS (multiple importance sampling) for next-event estimation
- Add volumetric scattering (participating media / fog)
- Add spectral rendering (wavelength-based dispersion)
