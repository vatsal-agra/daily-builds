# Lumen — Physically-Based Path Tracer from Scratch

## Concept

A full path tracer built from first principles: the Monte Carlo algorithm that underlies
every production renderer (Pixar's RenderMan, Disney's Hyperion, Blender Cycles).
Unlike a simple Whitted ray tracer (direct reflections only), path tracing simulates
the full light transport equation — indirect bounces, color bleeding, soft shadows,
caustics, and glossy inter-reflections emerge from a single elegant recursion.

Why interesting: every pixel in a path-traced image is a Monte Carlo estimate of an
integral over all light paths connecting the camera to every light source. The
physics is exact (no hacks or "ambient" terms). Correctness is measurable —
a white room with a white light must average 100% albedo; an energy-conserving
material must never create light. Beautiful images emerge from correct math.

## Architecture

```
lumen.py
├── PNG encoder (stdlib only)
├── Vec3 helpers (numpy arrays, no class wrapper)
├── Ray + HitRecord
├── Textures  (SolidColor, CheckerTexture, PerlinNoise)
├── Materials (Lambertian, Metal, Dielectric, DiffuseLight)
├── AABB (bounding box)
├── Geometry  (Sphere, Quad, Box, Translate, RotateY)
├── BVH       (median-split bounding-volume hierarchy)
├── HittableList
├── Camera    (PerspectiveCamera + ThinLens DoF)
├── Integrator (path_trace — Russian roulette loop)
├── Renderer  (tiled, multiprocessing.Pool)
├── Tone mapping (ACES filmic + gamma)
├── Built-in scenes
├── HTML gallery generator
└── CLI
```

Deps: Python 3.11, numpy (math), stdlib only otherwise (no Pillow).

## Feature List

### Required (4)

1. **Geometry + BVH**  
   Sphere, Quad (arbitrary rectangle), Box (6 quads), Translate + RotateY transforms.  
   Median-split BVH with AABB → O(log N) intersection queries. All objects return
   correct outward normals and UV texture coordinates.

2. **Material system**  
   - *Lambertian*: cosine-weighted hemisphere sampling, any texture as albedo  
   - *Metal*: specular reflection with tunable roughness fuzz  
   - *Dielectric*: Snell's law refraction + Schlick Fresnel, models glass/water  
   - *DiffuseLight*: emissive area light, the only light source type  
   All materials are energy-conserving (no free lunch).

3. **Path tracer with Russian roulette**  
   Unbiased Monte Carlo path tracing. Accumulate `throughput` across bounces.
   Russian roulette after depth 3 terminates paths without bias: if we kill a
   path with probability (1-p), we divide surviving throughput by p.
   Anti-aliasing via stratified jittered sub-pixel sampling.

4. **Scenes + output pipeline**  
   Three fully-specified built-in scenes (Cornell box, metallic spheres, glass caustics).
   JSON scene loader for custom scenes. PNG output via from-scratch encoder.
   Tiled renderer with multiprocessing (one tile per CPU core).
   ACES filmic tone mapping + gamma correction.

### Stretch (2+)

5. **Depth of field**  
   Thin-lens camera model: aperture diameter + focus distance. Rays fan out from
   a disk on the lens, converging at the focal plane. Creates realistic bokeh blur
   on out-of-focus objects.

6. **Procedural textures**  
   - *CheckerTexture*: alternating 3D checker pattern at configurable scale  
   - *PerlinNoise*: gradient (Perlin) noise → marble / turbulence textures  
   Both usable as albedo for any Lambertian surface.

7. **HTML gallery viewer**  
   Generated single-file HTML with embedded base64 PNGs. Displays all rendered
   scenes side by side with render stats (resolution, spp, time, noise estimate).

## Correctness Criteria

- White-room render: average pixel value must converge to ~1.0 with many samples  
- Glass sphere: refracted image should be inverted (correct lens behavior)  
- Metal roughness=0: render should visually match Whitted-style perfect mirror  
- Shadows: direct shadow rays blocked by opaque geometry  
- All renders are PNG-valid (verified by stdlib struct/zlib round-trip)

## Why I Chose This Today

Computer graphics is entirely absent from the LEDGER — no renderer, shader, or
geometry engine has been built. Path tracing is one of the most elegant
algorithms in CS: a 50-line core loop correctly simulates global illumination
with zero domain-specific hacks. The outputs (PNG renders) are immediately
beautiful and verifiable by human inspection, which is a refreshing change
from the text-only outputs of previous builds.

## Where a Human Could Take This

- Spectral rendering (wavelength-dependent IoR → real caustic rainbows)
- Bidirectional path tracing / Metropolis light transport (for hard caustics)
- Disney BSDF (the actual material model used in production)
- GPU acceleration via CuPy or a CUDA kernel
- Volumetric rendering (fog, subsurface scattering, clouds)
- OBJ mesh loading and triangle BVH with SAH splits
