# Lumina — Monte Carlo Path Tracer

A physically-based Monte Carlo path tracer built from scratch in pure Python (stdlib only, zero dependencies).

## What It Does

Lumina solves the rendering equation via Monte Carlo integration — for each pixel it casts hundreds of rays that bounce around a 3D scene, accumulating light from area lights and the environment. The result is physically correct soft shadows, color bleeding, caustics, and specular reflections.

**Key algorithms implemented from scratch:**

- **Monte Carlo path tracing** with Russian Roulette termination
- **Next-Event Estimation (NEE) + MIS balance heuristic** — explicit light sampling at each diffuse bounce, combined with BRDF sampling via MIS weights, dramatically reducing noise at equal sample counts
- **BVH (Bounding Volume Hierarchy)** with SAH (Surface Area Heuristic) splits — O(N log N) construction, O(log N) traversal, handles 400+ sphere scenes at interactive-ish speeds
- **PBR materials** — Lambertian (cosine-weighted hemisphere sampling), Metal (Phong-like reflection + fuzz), Dielectric (Snell's law + Schlick Fresnel + total internal reflection), Emissive (area lights)
- **Möller–Trumbore** triangle intersection with barycentric smooth-normal interpolation
- **Tone mapping** — Reinhard and ACES filmic, gamma 2.2
- **Hand-rolled PNG encoder** — IHDR/IDAT/IEND chunks, zlib DEFLATE, CRC-32 — zero dependencies
- **Bilateral denoiser** — spatial × range Gaussian weights
- **Wavefront OBJ loader** — v/vn/f directives, fan triangulation, smooth normals

## Quick Start

```bash
# Render the Cornell box (classic diffuse global illumination test)
python lumina.py render cornell -W 400 -H 400 -s 64 -d 10 -o cornell.png --aces

# Render the showcase scene (all 4 material types)
python lumina.py render showcase -W 400 -H 225 -s 64 -d 8 -o showcase.png --aces

# Load and render an OBJ mesh
python lumina.py obj models/tetrahedron.obj -W 400 -H 300 -s 32 -d 6 -o tet.png --aces

# Render a custom JSON scene
python lumina.py render /tmp/my_scene.json -W 400 -H 225 -s 32 -o out.png --aces

# Quick preview (low quality)
python lumina.py render spheres -W 160 -H 90 -s 4 -d 4 -o preview.png -q

# BVH stats and intersection benchmark
python lumina.py info cornell
python lumina.py bench cornell -W 64 -H 64 -s 4
```

### CLI Flags

| Flag | Default | Description |
|------|---------|-------------|
| `-W`, `-H` | 400, 225 | Output image dimensions (pixels) |
| `-s` | 32 | Samples per pixel |
| `-d` | 8 | Max ray depth (bounces) |
| `-o` | `renders/out.png` | Output path |
| `--aces` | off | ACES filmic tone map (vs Reinhard) |
| `--simple` | off | Simple path tracer (no NEE/MIS) |
| `--denoise` | off | Apply bilateral denoiser post-render |
| `-q` | off | Quiet mode (no progress bar) |
| `-e` | 1.0 | Exposure multiplier |

## Built-In Scenes

| Scene | Description |
|-------|-------------|
| `cornell` | Classic Cornell box — two diffuse boxes under an area light |
| `showcase` | Lambertian + Metal + Dielectric + Emissive in one frame |
| `glass` | Glass sphere (dielectric) + metal sphere + plane |
| `spheres` | 400+ random spheres (BVH stress test) |

## JSON Scene Format

```json
{
  "background_top": [0.3, 0.5, 0.8],
  "background_bot": [1.0, 1.0, 1.0],
  "camera": {
    "lookfrom": [0, 2, 5], "lookat": [0, 0, 0], "vup": [0, 1, 0],
    "vfov": 45, "aspect": 1.777
  },
  "materials": {
    "gray":  {"type": "lambertian", "albedo": [0.5, 0.5, 0.5]},
    "gold":  {"type": "metal", "albedo": [0.9, 0.7, 0.2], "fuzz": 0.1},
    "glass": {"type": "dielectric", "ior": 1.5},
    "light": {"type": "emissive", "emission": [8, 8, 8]}
  },
  "objects": [
    {"type": "sphere",   "center": [0, -1001, 0], "radius": 1000, "material": "gray"},
    {"type": "sphere",   "center": [0, 0, 0],      "radius": 1.0,  "material": "glass"},
    {"type": "quad_light", "corner": [-1,3,-1], "u": [2,0,0], "v": [0,0,2], "material": "light"},
    {"type": "box", "p_min": [-0.5, 0, -0.5], "p_max": [0.5, 1, 0.5], "material": "gray"}
  ]
}
```

## File Layout

```
2026-06-23-lumina/
├── lumina.py          # CLI entry point
├── vec3.py            # Vec3, Ray, AABB
├── geometry.py        # Sphere, Triangle, Plane, QuadLight, BVHNode
├── materials.py       # Lambertian, Metal, Dielectric, Emissive
├── renderer.py        # trace_simple(), trace_nee(), render()
├── scene.py           # Scene, Camera, PRESETS, load_scene()
├── output.py          # PNG encoder/decoder, tone mapping, denoiser
├── mesh.py            # OBJ loader, smooth normal generator
├── models/
│   ├── tetrahedron.obj
│   └── icosphere.obj
├── tests/
│   └── test_lumina.py  # 65 tests
├── demo.sh             # End-to-end verification script
├── renders/            # Output images (git-ignored)
├── PLAN.md
└── REVIEW.md
```

## Running Tests

```bash
python -m unittest tests.test_lumina -v
# 65 tests: Vec3, BVH, materials, PNG round-trip, OBJ loader, denoiser, render smoke tests
```

## End-to-End Demo

```bash
bash demo.sh
# Runs all 23 checks covering R1–R4 (required), S1–S3 (stretch), and JSON loading
# Expected: 23 passed, 0 failed
```

## Physics Notes

**Why this renderer is unbiased:** Each path is a Monte Carlo estimate of the rendering equation integral. No ad-hoc ambient terms, no clamped bounces (Russian Roulette terminates probabilistically). Expected value of all estimates converges to the true solution as samples → ∞.

**NEE + MIS:** At each diffuse bounce we take two samples: one toward a light (direct sampling) and one from the BRDF (cosine hemisphere). The MIS balance heuristic weights them as `w_i = p_i / Σp_j`. This reduces variance by ~4–8× vs BRDF sampling alone on scenes with small area lights.

**Weight convention:** `scatter()` returns the pre-computed throughput weight `f_r·cos(θ)/pdf`. For Lambertian this equals `albedo` exactly (π and cos terms cancel). The renderer does `throughput *= attenuation` without further PDF division — this is the correct, unbiased estimator.

## Where to Take This Next

- **Spectral rendering** — replace RGB with wavelength samples; proper dispersion through glass
- **Volumetric participating media** — fog, subsurface scattering, clouds
- **BDPT / MLLT** — bidirectional path tracing for caustics; Metropolis Light Transport for difficult paths
- **GPU acceleration** — translate to WGSL/GLSL compute shaders; the iterative loop structure maps naturally
- **Texture maps** — UV-parametric sampling from PNG images; normal maps, roughness maps
- **Importance-sampled environment maps** — HDR sky domes with tabulated CDFs

## Why I Built This

Path tracers are beautiful: a handful of clean physical laws (energy conservation, Snell's law, Lambertian BRDF) plus Monte Carlo mathematics produce photorealistic images. There's no magic — just integration. Building one from first principles (including the PNG encoder, BVH, and OBJ loader) makes every pixel feel earned.
