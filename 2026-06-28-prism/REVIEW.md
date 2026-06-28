# Adversarial Code Review — Prism Software Rasterizer

## Method

Read every source file (`math3d.py`, `framebuffer.py`, `rasterizer.py`, `shader.py`,
`geometry.py`, `camera.py`, `texture.py`, `png_encoder.py`, `html_viewer.py`, `prism.py`)
looking for correctness bugs, crashes, silent data-loss, and performance hazards.

---

## Bug 1 — Shadow world-positions recomputed per pixel (performance × correctness)

**File:** `src/rasterizer.py`, lines 257-262 (inside the `for py ... for px` loop)

```python
# BUG: inside the pixel loop — repeated for every pixel
wp0 = model_matrix.transform_point(ov0.pos)
wp1 = model_matrix.transform_point(ov1.pos)
wp2 = model_matrix.transform_point(ov2.pos)
```

`wp0/wp1/wp2` depend only on the triangle vertices and `model_matrix`, both of which are
constant for the whole triangle. Recomputing three 4×4 matrix multiplications per pixel means
a 1000-pixel shadow-mapped triangle wastes **3000 matrix multiplies** that should be **3**.
For a full scene this degrades shadow-pass performance by 3–4 orders of magnitude.

**Fix:** Hoist the three `transform_point` calls and the `iw`-scaled shadow-attribute
pre-mults to just before the bounding-box loop, inside the `if ctx.shadow_map` guard.

---

## Bug 2 — `is_top_left` closure created inside the innermost pixel loop

**File:** `src/rasterizer.py`, lines 209-210

```python
for py in range(min_y, max_y+1):
    for px in range(min_x, max_x+1):
        ...
        def is_top_left(ax,ay,bx,by):   # <-- function defined per pixel
            return (ay==by and ax>bx) or (by<ay)
```

Python creates a new function object (and closure frame) every pixel iteration.
For a 320×320 image with thousands of triangles this is millions of unnecessary allocations.
The function body is pure arithmetic with no captures; it should be a module-level function.

**Fix:** Move `is_top_left` to module scope (outside `render_mesh`).

---

## Bug 3 — `cmd_demo` saves a blank framebuffer then immediately overwrites it

**File:** `prism.py`, lines 387-388

```python
# BUG: Framebuffer(w,h) is brand-new and has never been rendered into
save_png(os.path.join(out, "torus.png"), w, h,
         Framebuffer(w,h).resolve_to_rgb_bytes())
# Lines 390-391 then render and overwrite the same path:
fb0, _ = _render_scene("torus", w, h, ...)
save_png(os.path.join(out, "torus.png"), ...)
```

The first `save_png` writes a solid-color placeholder image that is immediately replaced.
It wastes I/O and transiently leaves a corrupt output file visible to concurrent readers.

**Fix:** Delete lines 387-388.

---

## Bug 4 — Dead attribute access in `cmd_render` output line

**File:** `prism.py`, line 185

```python
print(f"  → {path}  ({elapsed:.2f}s, "
      f"{len(fb.triangles_rendered) if hasattr(fb,'triangles_rendered') else '—'} triangles)")
```

`Framebuffer` has no `triangles_rendered` attribute and never will; the `hasattr` guard
always takes the `else` branch, printing `—`. The dead branch is confusing dead code.

**Fix:** Remove the conditional; print `—` (or remove the count entirely from the message).

---

## Verification

After applying all fixes: `python -m unittest tests.test_prism -v` must still show 66/66 OK.
