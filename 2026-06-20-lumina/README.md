# Lumina — From-Scratch Ray Tracer / Path Tracer

A complete ray-tracing and path-tracing renderer built from scratch in pure Python, with no dependencies beyond the standard library.

## Features

### Core rendering
- **Unidirectional Monte Carlo path tracer** — global illumination, indirect lighting, colour bleeding, soft shadows, caustics through emissive surfaces
- **Whitted recursive ray tracer** — deterministic Phong shading, hard/soft shadows, mirror reflections, refractions
- **Russian Roulette path termination** — energy-conservative (throughput × attenuation before computing survive probability)
- **Multiprocessing** — parallel row-batch rendering via `fork` context pool; falls back to single-threaded on failure

### Materials
- **Lambertian** — cosine-weighted hemisphere sampling via ONB (orthonormal basis)
- **Metal** — specular mirror with fuzz (brushed metal)
- **Dielectric** — Snell's law refraction + Schlick Fresnel approximation (glass, water)
- **Phong** — ambient + diffuse + Blinn-Phong specular with shininess; used by Whitted tracer
- **Emissive** — area light surfaces for path tracer

### Geometry
- **Sphere**, **Plane** (infinite), **Triangle** (Möller-Trumbore, one/two-sided), **Quad**, **Box** (6 quads)
- **BVH** — Surface Area Heuristic (SAH) BVH tree for O(log n) intersection; ~70× speedup on mesh scenes
- **OBJ mesh loader** — parses `.obj` files (v/f lines, fan-triangulation of polygons, strict index validation)

### Camera
- **Thin-lens depth of field** — aperture + focus distance; all rays from a pixel converge at the focal plane
- Standard pinhole (aperture=0)

### Image output
- **From-scratch PNG encoder** — pure Python, zlib from stdlib, no Pillow
- **Tonemapping** — ACES filmic, Reinhard, clamp, gamma-only
- NaN/Inf-safe tone operators (explicit guards; Python's `min(1.0, NaN)` returns 1.0)
- PPM output for debugging

### Lighting
- **PointLight**, **DirectionalLight**, **AreaLight** (stratified n×n grid sampling for soft shadows)
- JSON scene format — camera, objects, lights, render settings, sky colour

### Interactive editor
- `lumina.py viz` — HTML scene editor served from stdlib `http.server`
- Browser JS preview (~50 ms, sphere-only) + POST /render → renders full image in-process

## Quick Start

```bash
# Render a scene to PNG
python lumina.py render scenes/showcase.json

# Render with custom settings
python lumina.py render scenes/cornell.json --width 400 --height 400 --samples 128 --mode path

# Whitted ray tracer
python lumina.py render scenes/whitted_demo.json --mode whitted --samples 4

# BVH vs brute-force benchmark
python lumina.py bench scenes/mesh.json

# Render all example scenes
python lumina.py demo

# Interactive HTML editor
python lumina.py viz

# Run tests
python tests/test_lumina.py

# Full demo (all scenes + benchmark + tests)
bash demo.sh
```

## Scenes

| File | Mode | What |
|------|------|------|
| `spheres.json` | path | Classic 4-sphere scene — diffuse, metal, glass |
| `cornell.json` | path | Cornell box with emissive ceiling light |
| `showcase.json` | path | 5 spheres, emissive area light, brushed metal ground |
| `dof.json` | path | Depth-of-field row of spheres |
| `whitted_demo.json` | whitted | Phong spheres, point + area lights, soft shadows |
| `mesh.json` | path | OBJ tetrahedron + 1024-tri sphere mesh (BVH benchmark) |

## Architecture

```
lumina/
  core/
    vec3.py         — Vec3 math (dot, cross, reflect, refract, ONB, random sampling)
    ray.py          — Ray(origin, direction)
    aabb.py         — AABB slab-method intersection + surrounding/from_points
    bvh.py          — SAH BVH builder
    materials.py    — HitRecord, ScatterRecord, all material classes
    primitives.py   — Sphere, Plane, Triangle, Quad, Box, PrimitiveList
    camera.py       — Thin-lens camera
    lights.py       — PointLight, DirectionalLight, AreaLight
    pathtracer.py   — Monte Carlo path tracer + Whitted full-image render
    whitted.py      — Recursive Whitted tracer
    png.py          — PNG encoder + tonemapping
    obj_loader.py   — .obj mesh parser
    scene_loader.py — JSON scene loader
  viz/
    editor.py       — Interactive HTML scene editor server
tests/
  test_lumina.py    — 41 unit + integration tests
scenes/             — JSON scenes + OBJ meshes
lumina.py           — CLI entry point
```

## Design notes

**Energy conservation** — the white furnace test (Lambertian albedo=1, uniform white sky) returns mean≈1.0 across 500 samples. Russian Roulette applies the compensation factor `1/survive` *after* accumulating attenuation, so `survive` is always ≤ the maximum throughput component, preventing energy gain.

**BVH SAH** — splits each axis at the bin boundary that minimises `SA(left)×N(left) + SA(right)×N(right)`; prefix/suffix surface-area arrays computed in O(N) per axis. Falls back to median split when SAH can't improve.

**NaN safety** — `aces_film`, `reinhard`, and `gamma_correct` all have explicit `math.isnan` / `math.isinf` guards. Python's `min(1.0, float('nan'))` evaluates to `1.0` (NaN comparison returns False for all ordered predicates), which would silently render NaN pixels as white without this guard.

**Dielectric hollow sphere** — negative radius in a sphere's JSON creates a hollow glass bubble (inner surface normals flip inward); the glass sphere at `showcase.json` centre demonstrates this.
