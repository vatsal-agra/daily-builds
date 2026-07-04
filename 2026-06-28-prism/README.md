# Prism — Software 3D Rasterizer

> **Status: Phase 4 complete — stretch features + polish**

A from-scratch software 3D rasterizer written in pure Python with **zero external
dependencies** (no numpy, no PIL). Implements the full GPU rasterization pipeline from
scratch, including shadow mapping, MSAA, procedural textures, and OBJ loading.

---

## Why This Project?

Rasterization is how every GPU on the planet renders in real-time — yet most people
only learn ray tracing. Prism implements the exact algorithms that GPUs execute in
hardware: MVP matrix pipeline, edge functions, perspective-correct interpolation,
z-buffering, backface culling, and Blinn-Phong shading. Reading the source explains
in executable detail what your GPU does dozens of times per second.

---

## Quick Start

```bash
# Info about the pipeline and built-in scenes
python prism.py info

# Render a gold torus to PNG
python prism.py render torus

# Render Cornell box with shadow mapping
python prism.py render cornell --shadow

# View normals as RGB (visualize interpolated per-fragment normals)
python prism.py render sphere --mode normals

# Rotate animation → self-contained HTML flipbook
python prism.py animate torus --frames 24 --fps 20

# Shadow mapping: before/after comparison HTML
python prism.py shadows

# Side-by-side render comparison (wireframe / Phong / textured / normals / MSAA)
python prism.py compare showcase

# Load your own OBJ file
python prism.py obj --file model.obj --animate

# Full demo (all scenes + animations + normal viz → output/)
python prism.py demo
```

Output goes to `output/`. All PNGs and HTML files are self-contained.

---

## Features

### Required (R-tier)

| Feature | Implementation |
|---|---|
| MVP matrix pipeline | `src/math3d.py` — column-major Mat4, look_at, perspective, ortho |
| Triangle rasterization | `src/rasterizer.py` — edge functions, top-left fill rule, z-buffer |
| Blinn-Phong shading | `src/shader.py` — ambient + diffuse (NdotL) + specular (NdotH^shininess) |
| Multiple lights | Point lights with attenuation + directional + ambient |

### Stretch (S-tier, all implemented)

| Feature | Detail |
|---|---|
| Perspective-correct texturing | UV/w per vertex, bilinear filtering, wrapping |
| PCF Shadow Mapping | Depth pass from light + 3×3 kernel soft shadows |
| MSAA 2× | 4-sample super-sampling with box resolve |
| HTML Flipbook Viewer | Self-contained base64-PNG animation player |
| OBJ/MTL Loader | Full Wavefront OBJ with fan triangulation, materials |
| Normal Visualization | `--mode normals` — view-space normals as RGB for debugging |
| Near-Plane Clipping | Sutherland-Hodgman w-clip prevents near-plane artifacts |

### Procedural Textures

`src/texture.py` — checkerboard, marble (turbulence + sine), earth-like, UV grid, gradient.
All textures use bilinear filtering with UV wrapping.

### PNG Output

From-scratch PNG encoder (`src/png_encoder.py`) using Sub filter + zlib — no Pillow needed.

---

## Architecture

```
prism.py (CLI)
  ├── src/math3d.py       — Vec3, Vec4, Mat4 (column-major, like GLSL)
  ├── src/framebuffer.py  — float RGB + float depth, MSAA resolve, Reinhard tonemap
  ├── src/camera.py       — Camera (perspective), LightCamera (ortho for shadow)
  ├── src/geometry.py     — Material, Vertex, Triangle, Mesh, OBJ loader, 5 primitives
  ├── src/rasterizer.py   — render_mesh (full pipeline), render_depth (shadow pass)
  ├── src/shader.py       — Blinn-Phong BRDF, PCF shadow sampler
  ├── src/texture.py      — Texture class + procedural generators
  ├── src/png_encoder.py  — from-scratch PNG (IHDR/IDAT/IEND, Sub filter, zlib)
  └── src/html_viewer.py  — self-contained HTML flipbook + comparison grid
```

### Rasterization Pipeline (per triangle)

```
World → [Model Matrix] → World Space
World → [View Matrix]  → View (Camera) Space    ← Blinn-Phong shading here
View  → [Proj Matrix]  → Clip Space             ← near-plane clipping here
Clip  → [÷ w]          → NDC [-1,1]³
NDC   → [viewport]     → Screen Pixels
Screen → edge fn test  → fragment covered?      ← backface cull: area ≤ 0 → skip
fragment → [z-test]    → depth buffer
fragment → [interp]    → perspective-correct UV/pos/normal
fragment → [shader]    → Blinn-Phong / normal viz
```

---

## Built-in Scenes

| Scene | Objects | Lights |
|---|---|---|
| `torus` | Gold torus (3200 triangles) | 3-point lighting |
| `sphere` | Red sphere with checker texture | 3-point lighting |
| `cornell` | Room + 2 boxes + sphere | Ceiling light + fill |
| `shadow_demo` | Sphere + torus + box on checkerboard | Point light → PCF shadows |
| `showcase` | Torus + earth sphere + marble cylinder + box | 2 colored point lights |

---

## Tests

```bash
python -m unittest tests.test_prism -v
```

67 tests covering: Vec3/Mat4 math, framebuffer operations, texture sampling,
geometry generation, camera matrices, Blinn-Phong shader, PCF shadow sampler,
rasterizer (culling, z-occlusion, wireframe, normals mode, depth pass),
PNG encoder, and full per-scene pipeline smoke tests.

---

## Lessons Learned

- **Perspective-correct interpolation** is non-trivial: you must divide attributes by
  clip-space w per vertex, interpolate with screen-space barycentrics, then multiply
  by the fragment's interpolated 1/w. Skipping this causes visible texture warping.
- **Shadow maps** need a bias (even small) to avoid shadow acne — comparing stored
  depth against the fragment's light-space depth without bias fails for nearly-flat surfaces.
- **Normal matrix** must be `(MV⁻¹)ᵀ` — not just MV — or normals distort under
  non-uniform scaling.
- **NDC z interpolation** is actually linear in screen space (unlike UVs), because
  the screen-space barycentric weighting exactly cancels the perspective warp.
- Performance: moving per-triangle constant work (world-space vertex transforms for
  shadows) outside the per-pixel loop gives orders-of-magnitude speedup.
