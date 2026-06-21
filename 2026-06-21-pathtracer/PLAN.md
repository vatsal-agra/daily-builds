# Pathtracer — PLAN

## Concept
A physically-based Monte Carlo path tracer written entirely from scratch in pure
Python 3 (stdlib only, no numpy, no PIL). It solves the rendering equation by
importance-sampling indirect-light paths, producing photorealistic images with
soft shadows, caustics, inter-object color bleeding, reflections, transparency,
and depth-of-field — all emerging naturally from a handful of physics rules.

## Why it's interesting
Path tracing is the gold standard of photorealistic rendering.  Every
cinema-quality VFX shot and modern video game's baked lighting is computed with
some variant of this algorithm.  The maths are elegant: a recursive stochastic
estimator of an integral equation, convergent by the law of large numbers, that
"automatically" produces shadows, mirrors, glass, indirect bounce light, area
light penumbrae, and depth-of-field.

Building it from scratch demonstrates:
- Importance sampling & Monte Carlo integration
- Physically-based BRDFs (Lambertian, GGX-style metal, Fresnel dielectric)
- BVH with Surface Area Heuristic — ray-scene queries drop from O(N) to O(log N)
- Coordinate-free geometry (ray, hit record, ONB) and Snell / Schlick
- Parallel tile rendering via `multiprocessing` (fork-safe on Linux)
- Hand-rolled PNG encoder (zlib streams, CRC-32, filter bytes)

## Architecture

```
pathtracer/
  vec3.py       — Vec3 class + helpers (reflect, refract, schlick, ONB, sampling)
  ray.py        — Ray(origin, direction) + at(t)
  textures.py   — SolidTexture, CheckerTexture, PerlinTexture (marble/wood)
  materials.py  — Lambertian, Metal, Dielectric, DiffuseLight
  shapes.py     — HitRecord, Sphere, Box, Plane, Triangle, HittableList
  bvh.py        — AABB, BVHNode (recursive SAH build + traversal)
  camera.py     — PerspectiveCamera with thin-lens DOF
  scene.py      — Scene + JSON loader (objects, lights, background, camera)
  renderer.py   — tile-based path tracer + fork-parallel render()
  png_writer.py — hand-rolled PNG encoder (IHDR/IDAT/IEND, zlib, CRC-32)
  cli.py        — argparse CLI: render / bench / demo / info
  main.py       — entry point
scenes/
  spheres_classic.json  — three-sphere classic with mirror, glass, Lambertian
  cornell_box.json      — closed box with area-light ceiling, colored walls
  dof_demo.json         — row of spheres; aperture blurs background
tests/
  test_vec3.py
  test_shapes.py
  test_bvh.py
  test_materials.py
  test_scene.py
  test_renderer.py
```

## Feature List

### Required (4)

1. **Full path tracing with PBR materials**
   Recursive Monte Carlo path tracer with cosine-weighted hemisphere sampling
   for Lambertian surfaces, specular BRDF + roughness for Metal, Snell's law +
   Fresnel-Schlick for Dielectric glass, and DiffuseLight for area lights.
   Russian-roulette path termination for unbiased variance reduction.
   Anti-aliasing via stratified jitter over each pixel.

2. **BVH acceleration with SAH**
   Bounding-volume hierarchy constructed with the Surface Area Heuristic:
   O(N log N) build, O(log N) average query.  Benchmarked: a 484-sphere scene
   renders ≥10× faster with BVH than with brute-force HittableList.

3. **JSON scene format — spheres, boxes, planes, area lights, background**
   Fully declarative JSON: camera position/orientation/FOV, sky background (solid
   color or horizon gradient), and an objects array supporting sphere / box / plane
   primitives, each with a material (solid/checker/perlin albedo, roughness, IOR).
   DiffuseLight emissive material drives area lighting.

4. **Cornell Box — global illumination / color bleeding**
   Classic Cornell Box scene: white floor/ceiling, red left wall, green right wall,
   white back wall, white light panel on ceiling.  A render shows diffuse inter-
   reflection turning the walls subtly pink/green where they face each other — the
   hallmark of correct global illumination, impossible with rasterisation alone.

### Stretch (3)

5. **Thin-lens camera — depth of field**
   Aperture (f-number) + focus distance parameters; sample a disk on the lens
   per path, producing realistic bokeh on out-of-focus geometry.

6. **Procedural textures — checker + Perlin marble/wood**
   CheckerTexture tiles two sub-textures on world-space coordinates.
   PerlinTexture uses gradient noise + turbulence + a sine warp to produce marble
   or wood-grain patterns applicable to any surface.

7. **Hand-rolled PNG encoder**
   Write valid `.png` files using only Python's `zlib` from stdlib — builds IHDR
   chunk, filters each scanline (Sub-filter for speed), deflates with zlib, writes
   IDAT chunks with CRC-32.  No Pillow or external imaging library.

## Scope
- Output resolution demo target: 400 × 300, 64 SPP (samples per pixel)
- Tests use 32 × 24, 4–16 SPP so the suite runs in seconds
- Multiprocessing tile renderer (fork) uses all available CPU cores
- No external dependencies; `zlib` and `multiprocessing` are stdlib
