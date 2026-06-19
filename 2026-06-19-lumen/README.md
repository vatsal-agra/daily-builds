# Lumen — Physically-Based Path Tracer

> **Status: Phase 5 complete (all tests green)**

A full Monte Carlo path tracer built from scratch in Python (numpy + stdlib only).
Every pixel is an unbiased estimate of the global illumination integral — indirect
bounces, soft shadows, color bleeding, caustics, and depth of field all fall out of
the same 50-line core loop.

## Quick Start

```bash
# Render all three scenes at demo resolution (~60s on a 4-core machine)
bash demo.sh

# Or render a single scene at higher quality
python3 lumen.py render cornell -W 256 -H 256 --spp 32 --workers 4

# Custom JSON scene
python3 lumen.py render custom --file scenes/simple.json -W 320 -H 180 --spp 16

# Rebuild gallery from existing PNGs
python3 lumen.py gallery
```

## Features

### Required (all implemented)

| Feature | Details |
|---------|---------|
| **Geometry + BVH** | Sphere, Quad, Box, Translate, RotateY transforms. Median-split BVH with AABB. |
| **Material system** | Lambertian (cosine hemisphere), Metal (roughness fuzz), Dielectric (Snell + Schlick), DiffuseLight (area light). |
| **Path tracer** | Unbiased Monte Carlo with NEE for diffuse surfaces, Russian roulette after depth 3. Anti-aliasing via sub-pixel jitter. |
| **Scenes + output** | Cornell box, metallic spheres, glass caustics. JSON scene loader. From-scratch PNG encoder. Tiled multiprocessor renderer. ACES filmic tone mapping. |

### Stretch (all implemented)

| Feature | Details |
|---------|---------|
| **Depth of Field** | Thin-lens camera: aperture + focus distance. Enabled in the spheres scene. |
| **Procedural textures** | CheckerTexture (3D sine-based checker), PerlinTexture (gradient Perlin noise → marble/turbulence). |
| **HTML gallery** | Single-file HTML with embedded base64 PNGs, render stats, and a dark-mode card layout. |

## Scenes

**Cornell box** — classic closed room with area light, two rotated boxes, and a glass sphere.
Demonstrates: Lambertian diffuse, glass refraction, NEE direct lighting, box transforms.

**Metallic spheres** — checker ground plane, glass + marble + gold spheres, depth-of-field bokeh.
Demonstrates: DoF aperture blur, Perlin marble texture, checker ground, sky background.

**Glass caustics** — glass sphere on checker floor with area light above.
Demonstrates: caustic ring formation from glass refraction, NEE + sky separation.

## Architecture

```
lumen.py  (~1200 lines, no external deps beyond numpy)
├── encode_png()          — PNG writer: stdlib struct + zlib only
├── v3 / normalize / …    — Vec3 math (numpy arrays)
├── Ray, Hit, ONB         — Ray + intersection record + orthonormal basis
├── SolidColor, CheckerTexture, PerlinTexture
├── Lambertian, Metal, Dielectric, DiffuseLight
├── AABB, Sphere, Quad, Box, Translate, RotateY
├── BVH                   — median-split bounding-volume hierarchy
├── World, Camera         — scene container + thin-lens camera
├── path_trace()          — Russian roulette loop + NEE
├── aces_tonemap()        — ACES filmic curve + gamma 2.2
├── render()              — tiled multiprocessing.Pool renderer
├── make_gallery()        — embedded-PNG HTML report
└── main()                — CLI: render / demo / gallery
```

## Performance

Python with numpy vec3 ops runs at ~430 rays/sec per core (4 cores → ~1700 rays/sec).
Demo renders use 96×96 @ 8 spp (Cornell) and 128×72 @ 8 spp (others) to finish in ~60s.

For production-quality renders (512×512 @ 128 spp), expect:
- Cornell: ~90 minutes (pure Python)
- Would need Numba JIT or a CUDA kernel for interactive use

## Testing

```bash
pip install pytest
python3 -m pytest tests/test_lumen.py -v
```

56 tests covering: vec3 math, ONB orthonormality, AABB hit/miss, sphere/quad/box
intersection, BVH correctness, all material scatter paths, camera ray generation,
DoF offset, PNG encoder round-trip, tone mapping, energy conservation, and
end-to-end renders of all three scenes with color correctness checks.

## JSON Scene Format

```json
{
  "background": "sky",
  "camera": { "from": [0,2,-6], "to": [0,0,0], "up": [0,1,0],
              "vfov": 30, "aspect": 1.777, "aperture": 0.1, "focus_dist": 6.0 },
  "materials": {
    "red":   {"type": "lambertian", "albedo": [0.8, 0.1, 0.1]},
    "glass": {"type": "dielectric", "ior": 1.5},
    "light": {"type": "light", "color": [1,1,1], "intensity": 5.0}
  },
  "objects": [
    {"type": "sphere", "center": [0,0,0], "radius": 1.0, "material": "red"},
    {"type": "quad",   "q": [0,0,0], "u": [1,0,0], "v": [0,1,0], "material": "light"},
    {"type": "box",    "a": [0,0,0], "b": [1,1,1], "material": "red"}
  ]
}
```

## References

- [_Ray Tracing in One Weekend_](https://raytracing.github.io/) — architecture basis
- [Physically Based Rendering (PBRT)](https://pbrt.org/) — NEE, Russian roulette theory
- [ACES filmic](https://knarkowicz.wordpress.com/2016/01/06/aces-filmic-tone-mapping-curve/) — tone mapping
