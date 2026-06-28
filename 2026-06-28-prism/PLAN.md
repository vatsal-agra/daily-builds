# Prism — Software 3D Rasterizer: Plan

## Concept

Prism is a from-scratch software 3D rasterizer written in pure Python — the
algorithm that drives all real-time graphics hardware. While the previous daily
builds include three separate path tracers (ray-based), **rasterization is a
fundamentally different approach**: instead of casting rays through pixels, you
project each triangle onto the screen and fill the pixels it covers. This is how
GPUs work, and why modern games render millions of triangles per second.

Prism implements the full GPU pipeline in software:
- Vertex processing (matrix transforms, lighting in camera space)
- Primitive assembly + back-face culling
- Clipping & perspective divide (NDC)
- Viewport transform (screen space)
- Triangle rasterization (edge functions, sub-pixel fill rule)
- Fragment processing (Blinn-Phong shading, texture sampling)
- Output merging (z-buffer depth test, write to framebuffer)

## Why Interesting

1. **Pedagogically revealing** — exposes the exact pipeline abstracted by OpenGL/Vulkan
2. **Algorithmically distinct** from path tracing — no ray-scene queries, no Monte Carlo
3. **Depth buffer magic** — z-fighting, overdraw, painter's-algorithm failure modes
4. **Shadow mapping** — an elegant two-pass technique with genuine tricky bits (bias, PCF)
5. **Perspective correction** — why naive UV interpolation produces the "screen door" effect,
   and how a 1/w division fixes it

## Architecture

```
prism.py                  CLI entry point
src/
  math3d.py               Vec3, Vec4, Mat4 (4×4 column-major, like GLSL)
  geometry.py             Triangle, Mesh, OBJ+MTL loader, procedural models
  camera.py               Camera (view + projection matrices, viewport)
  framebuffer.py          Color buffer + depth buffer; MSAA resolve
  rasterizer.py           Core triangle scan: edge functions, barycentric coords,
                          z-test, fragment shading
  shader.py               Blinn-Phong BRDF, texture lookup, shadow map sample
  texture.py              Framebuffer-as-texture, procedural textures,
                          bilinear filtering
  shadow.py               Shadow map pass (depth-only render from light POV)
  png_encoder.py          From-scratch PNG encoder (IHDR/IDAT/IEND, zlib Sub filter)
  html_viewer.py          Generate animated HTML flipbook (base64 frames)
scenes/
  scene_torus.py          Torus (procedural) + 2 point lights
  scene_cornell.py        Cornell box variant — colored walls + sphere
  scene_shadow.py         Spotlight shadow demo — 3 objects casting shadows
  scene_texture.py        UV sphere with checkerboard + Earth-like procedural texture
tests/
  test_prism.py           Unit + integration test suite
PLAN.md
REVIEW.md
README.md
demo.sh
```

## Feature List

### Required (4)

**R1 — Triangle Rasterizer with Depth Buffer**
Scanline fill via edge functions (sub-pixel-correct top-left fill rule, same rule
GPUs use). Perspective-correct barycentric coordinates. Depth buffer with 32-bit
float per pixel; z-test (discard or write). Backface culling in NDC space.
Outputs color + depth framebuffers.

**R2 — 3D Transform Pipeline**
Full MVP matrix stack: Model (translate/rotate/scale) → View (look-at) → Projection
(perspective frustum, arbitrary FOV + aspect + near/far). Perspective divide to NDC,
viewport transform to window coordinates. Handles degenerate triangles (zero area,
behind camera). Clipping: triangles fully behind near plane discarded; triangles
partially behind clipped to up to 2 output triangles.

**R3 — OBJ + MTL Loader**
Loads Wavefront OBJ files: `v` (positions), `vn` (normals), `vt` (texture coords),
`f` (faces, arbitrary polygon → triangle fan), `usemtl` (material groups), `mtllib`
(material library). Loads MTL: `Ka`/`Kd`/`Ks`/`Ns`/`d`, `map_Kd` (diffuse texture).
Face normals computed if absent. Smooth vs flat shading controlled per object.

**R4 — Blinn-Phong Per-Fragment Shading**
Per-fragment lighting in camera space. Supports up to 8 point lights + 1 directional
light + ambient. Blinn-Phong BRDF (ambient + Nₐ·L diffuse + H·N specular with
shininess exponent). Vertex normals interpolated across triangle (Gouraud available
as fast path). Attenuation (constant + linear + quadratic). Material properties
from MTL or per-mesh defaults.

### Stretch (2+)

**S1 — Perspective-Correct Texture Mapping**
Naive (affine) UV interpolation produces a screen-door warping artifact on large
triangles. Correct approach: interpolate u/w and v/w (affine in clip space), then
divide by 1/w at the fragment. Bilinear filtering: 4-sample weighted average at
sub-texel positions. Procedural texture generator (checkerboard, gradient, marble
noise, UV debug grid) — no external image files required.

**S2 — Shadow Mapping with PCF**
Two-pass rendering:
  Pass 1: render scene from light's POV into a depth texture.
  Pass 2: for each fragment, transform world position to light-clip space, compare
  depth against shadow map. Percentage-Closer Filtering (PCF): 3×3 kernel of
  depth comparisons, average = shadow factor. Bias (constant + slope-scaled) to
  eliminate self-shadowing acne. Directional + spot light shadow casters.

**S3 — MSAA Anti-Aliasing + Animated HTML Viewer**
Multi-Sample Anti-Aliasing at 2×2 super-samples: rasterize at 2× resolution,
resolve (box filter) to output. Gamma correction (sRGB, γ=2.2) on output.
HTML flipbook viewer: renders N animation frames (rotating model), encodes each
as base64 PNG, builds a self-contained HTML with JavaScript that steps frames
at 30 fps — no external dependencies.

## Rendering Pipeline Flow

```
Scene (meshes, lights, camera)
        │
        ▼
[Vertex stage]
  For each mesh: apply Model matrix → View matrix → Projection matrix
  Clip space → perspective divide → NDC → viewport → screen space

[Optional: Shadow pass]
  Render depth-only from light POV → shadow texture

[Rasterization stage]
  For each triangle (front-facing):
    Compute edge functions e0, e1, e2
    Bounding box clamp to viewport
    For each pixel in bbox:
      test e0·p ≥ 0 AND e1·p ≥ 0 AND e2·p ≥ 0
      compute barycentric (λ0, λ1, λ2)
      interpolate 1/w (perspective)
      depth test (z-buffer)
      → if passes: run fragment shader

[Fragment shader]
  Interpolate (u,v) corrected for perspective
  Sample texture (bilinear)
  Interpolate normal (in view space)
  Blinn-Phong: ambient + Σ lights (diffuse + specular)
  Sample shadow map → shadow factor
  Output: RGB color

[Output merge]
  Write to color framebuffer
  Write depth to depth buffer

[Post-process]
  MSAA resolve (if enabled)
  Gamma correction
  → PNG encode
```

## Timeline

- Phase 1: PLAN (this document)
- Phase 2: Core — math3d, framebuffer, rasterizer, pipeline, OBJ loader, Phong
- Phase 3: Adversarial review → fixes
- Phase 4: Stretch — textures (S1) + shadow maps (S2), HTML viewer (S3)
- Phase 5: Tests + demo.sh
- Phase 6: README + LEDGER
