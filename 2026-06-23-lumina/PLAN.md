# Lumina — Monte Carlo Path Tracer

## Concept

A physically-based renderer built from scratch in pure Python. Lumina implements
the real math behind modern rendering: unbiased Monte Carlo integration of the
Light Transport Equation, BVH acceleration, and physically-based materials.

The output is photorealistic PNG images showing global illumination —
soft shadows, color bleeding, caustics from glass, and mirror reflections —
produced by simulating how light actually bounces in a scene.

## Why it's interesting

Path tracing is the algorithm behind every modern film VFX renderer (Arnold,
RenderMan, Cycles). The math is beautiful: rendering is an integral over all
paths light can take, Monte Carlo gives you an unbiased estimator, and the
variance reduction tricks (importance sampling, MIS, Russian roulette) are
elegantly derived from probability theory. BVH trees give O(log N) ray
intersection over millions of triangles using a surface-area heuristic that
minimizes expected traversal cost.

## Architecture

```
lumina.py          CLI: render / preview / demo / info / bench
vec3.py            Vec3 (dot, cross, normalize, reflect, refract), Ray, AABB
materials.py       Lambertian, Metal, Dielectric, Emissive — scatter() + pdf()
geometry.py        Sphere (analytic), Triangle (Möller-Trumbore), Plane, Mesh
bvh.py             SAH-split BVH, iterative AABB-ray traversal
scene.py           JSON scene loader, Camera (perspective + DOF), preset scenes
renderer.py        Path tracing integrator: Li() recursion, MIS, NEE
output.py          Reinhard/ACES tone mapping, gamma, hand-rolled PNG encoder
tests/
  test_lumina.py   Unit + integration + correctness tests
```

## Feature List

### Required (4)

**R1 — Scene system + ray-primitive intersection**
JSON scene description format with camera, materials, and objects. Spheres
(analytic quadratic intersection), triangles (Möller-Trumbore), infinite planes.
Affine transforms (translate/scale/rotate) on any object. AABB construction.
Multiple preset scenes loaded from Python dicts (Cornell box, glass balls, etc.).

**R2 — BVH acceleration structure**
Surface Area Heuristic (SAH) BVH construction: recursively partition objects
by the axis and split point that minimizes (surface_area_left × n_left +
surface_area_right × n_right). Iterative traversal with an explicit stack.
Tested: BVH must agree with brute-force linear scan on all hit/miss/t values.

**R3 — Path tracing core**
Unbiased Monte Carlo path integrator: at each surface hit, sample a new
direction from the material's PDF, accumulate the BRDF/PDF weight, recurse.
Russian Roulette termination (survival probability = max channel of throughput)
after depth 3. Configurable max depth (default 8). Anti-aliasing via jittered
supersampling. Pinhole + thin-lens camera with adjustable FOV and aperture.

**R4 — Physically-based materials**
- Lambertian: cosine-weighted hemisphere sampling (importance-sampled PDF)
- Metal: mirror reflection with configurable fuzz/roughness
- Dielectric: Snell's law refraction + Schlick Fresnel, handles total internal
  reflection, both transmission and reflection weighted by Fresnel term
- Emissive: area light source with configurable emission color/intensity

### Stretch (2+)

**S1 — Tone mapping + PNG output (IMPLEMENTED)**
Reinhard global tone mapping, ACES filmic tone mapping, gamma correction (γ=2.2).
Hand-rolled PNG encoder: zlib DEFLATE compression (via stdlib zlib), IHDR/IDAT/
IEND chunks, CRC-32 checksums. Save render metadata (spp, time, scene) as JSON
sidecar. Render progress bar to stderr.

**S2 — Next-Event Estimation / Direct Light Sampling (IMPLEMENTED)**
At each bounce, explicitly sample a point on each emissive object and test
visibility. Combine with BRDF sampling using the MIS balance heuristic:
  w_light = p_light / (p_light + p_brdf)
  w_brdf  = p_brdf  / (p_light + p_brdf)
This dramatically reduces variance on scenes with small bright light sources
(the Cornell box becomes clean at 64 spp instead of requiring 1000+).

**S3 — OBJ mesh loading (BONUS if time permits)**
Wavefront OBJ parser, triangle mesh construction, per-face normals or smooth
shading with interpolated vertex normals, automatic BVH over mesh triangles.

## Preset Scenes

1. **cornell** — Classic Cornell box: white room, red/green walls, white box, 
   tall box, area light on ceiling, two diffuse boxes
2. **spheres** — Metal + glass + diffuse spheres on a checkered ground plane
3. **glass** — Glass sphere (full internal refraction), mirror sphere, soft light
4. **showcase** — Every material type, demonstrates all PBR features

## Verification Strategy

- Vec3 ops: algebraic identities (dot, cross, normalize)
- Ray-sphere: compare analytic t against numerical root-finding (Newton)
- Ray-triangle: compare Möller-Trumbore vs barycentric subdivision oracle
- BVH: every hit must agree with brute-force linear scan
- Snell's law: transmitted direction angle satisfies n1 sin θ1 = n2 sin θ2
- Fresnel: at grazing angle → 1.0, at normal incidence → ((n-1)/(n+1))²
- Energy conservation: Lambertian cos-weighted sampling gives π * PDF integral
- Pixel values converge: running mean stabilises as 1/√N (verified statistically)
- Round-trip PNG: encode then decode via stdlib and compare byte-for-byte
