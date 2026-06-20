# Lumina — Ray Tracer / Path Tracer

## Concept

A from-scratch physically-based renderer in pure Python: recursive ray tracing for
deterministic Whitted-style renders (reflections, refractions, sharp shadows) and a
unidirectional path tracer for Monte Carlo global illumination (soft shadows, color
bleeding, ambient occlusion as a free side-effect). Scenes are described in a simple
JSON format and render to self-contained PNG files via a hand-rolled PNG encoder (no
Pillow, no deps). An interactive single-file HTML playground lets you edit the scene
JSON live, fire the tracer via a JS worker, and see the result update in real time.

## Why It's Interesting

Ray tracing sits at the intersection of geometry, physics, probability theory, and
computer graphics. It is one of the few algorithms where the "correct" result is a
Monte Carlo integral over light paths — more samples means more truth. The same code
that renders a mirror ball also handles global illumination: the principle is identical,
only the sampling strategy changes. Building both in ~2 kloc of pure Python forces
every piece to be understood rather than borrowed.

## Architecture

```
lumina/
  core/
    vec3.py        — 3-element vector (all math inlined, no numpy)
    ray.py         — Ray(origin, direction)
    aabb.py        — Axis-Aligned Bounding Box + slab intersection
    bvh.py         — Surface Area Heuristic BVH builder + traversal
    materials.py   — Lambertian, Metal, Dielectric, Phong, Emissive
    primitives.py  — Sphere, Plane, Triangle, Mesh (list of triangles)
    scene.py       — Scene (light list, primitive list, BVH root, camera)
    camera.py      — Pinhole camera, defocus blur (depth-of-field)
    whitted.py     — Classic Whitted ray tracer (recursive, exact shadows)
    pathtracer.py  — Unidirectional path tracer (cosine-hemisphere sampling)
    png.py         — Tonemap (gamma + ACES) + hand-rolled PNG encoder
    scene_loader.py — JSON → Scene
  lumina.py        — CLI entry point
  scenes/          — Bundled example JSON scenes
  viz/
    editor.py      — Generates a self-contained HTML scene editor
  tests/
    test_lumina.py — Full test suite
  demo.sh          — Runs all CLI commands and verifies output
  PLAN.md
  REVIEW.md
  README.md
```

## Feature List

### Required (4)

1. **Whitted ray tracer** — Phong shading (ambient + diffuse + specular + shininess),
   point/directional lights, hard shadows via shadow rays, configurable bounce depth.
   Spheres, planes, and triangles as primitive types.

2. **Reflections + Refractions** — Mirror-like `Metal` material (with fuzz for glossy
   surfaces), `Dielectric` material implementing Snell's law refraction + Schlick
   Fresnel mixing between reflection and transmission. Cornell-box scene with both.

3. **Path Tracer with global illumination** — Monte Carlo path tracer with
   cosine-hemisphere importance sampling (Lambertian BRDF), Russian Roulette path
   termination, accumulation buffer for multi-sample averaging, and emissive surfaces
   as area lights. Produces soft shadows and colour bleeding.

4. **BVH acceleration structure** — Surface Area Heuristic (SAH) split BVH built over
   arbitrary primitive lists. All ray intersection queries walk the BVH. Benchmark:
   BVH vs brute-force on a 500-triangle scene, demonstrate speedup.

### Stretch (3)

5. **Interactive HTML scene editor** — Self-contained single-file HTML playground: a
   JSON textarea, a canvas to display the rendered PNG, a "Render" button that sends
   the JSON to a Python HTTP server and shows the result, plus a JS-only preview mode
   that renders a fast sphere-only approximation in <50 ms.

6. **Depth-of-field camera** — Thin-lens defocus blur: jitter ray origins over a disc
   at the lens aperture, focus rays through the focal point. Configurable aperture and
   focal distance in the scene JSON.

7. **OBJ file loader + mesh rendering** — Parse a minimal .obj file (v/f/vn), build
   a Triangle mesh, wrap it in a BVH. Render Stanford Bunny (or a small demo mesh).

## Example Scenes

- `spheres.json` — Classic ray-tracer showcase: 3 spheres (Lambertian, Metal, Dielectric)
- `cornell.json` — Cornell box (emissive area light, diffuse walls, reflective sphere)
- `dof.json`     — Depth-of-field demo: row of spheres, shallow depth-of-field
- `mesh.json`    — An OBJ mesh wrapped in BVH

## Output Formats

- `.png` — primary output, self-contained, via hand-rolled PNG encoder
- `.ppm` — fast debug output (no encoding overhead)
- Metadata printed to stdout: samples, rays/s, render time

## CLI

```
python lumina.py render   <scene.json> [options]   # render scene
python lumina.py bench    <scene.json>              # BVH vs brute-force timing
python lumina.py viz                                 # launch HTML editor server
python lumina.py demo                               # render all example scenes
```
