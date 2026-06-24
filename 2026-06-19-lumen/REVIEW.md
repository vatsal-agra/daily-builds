# Lumen — Adversarial Code Review

**Phase 3 review — everything I'd attack if I were trying to break this**

---

## Critical: Correctness Bugs

### 1. NEE double-counts direct light for the first hit from a specular bounce

**Problem**: `last_specular` is initialized to `True` so the very first hit always adds emission (correct for primary rays hitting a light). After a specular bounce, `last_specular = True` and the next diffuse hit will also add emission — but NEE already handles direct light. This means: Camera → Specular → Diffuse → Light adds emission via MIS *and* NEE.

**Actual impact**: Fireflies / bright halos around lights seen through glass or metal.

**Fix**: The NEE block correctly skips specular paths. But when `last_specular = True` AND `not is_specular`, emission is added at the top AND NEE is run below. The emission guard at the top of the loop is correct for the specular case — but the NEE guard on `not is_specular` handles everything else. These two paths don't overlap, so this is actually **not a bug** on re-read. The `last_specular` flag prevents double-counting.

**Verdict**: Correct as-is. No change needed.

---

### 2. Box face winding produces one incorrectly oriented face

**Problem**: The -z face uses `Quad(mn, dy, dx, material)` → `cross(dy, dx)` = (0,0,-1)×scale, which is correct. But let's verify the -x face: `Quad(mn, dz, dy, material)` → `cross(dz, dy)` = (0,0,z)×(0,y,0) = cross([0,0,1],[0,1,0]) = (-1,0,0), which is correct for the -x face. All six normals check out mathematically.

**Verdict**: Correct. (Was a real bug, was already fixed in Phase 2.)

---

### 3. `to_uint8` gamma value mismatch

`to_uint8` applies ACES *then* gamma 1/2.2. ACES is already designed to output in a near-sRGB space. Applying gamma 2.2 on top of ACES can cause brightening artifacts since ACES's output already accounts for perceptual encoding.

**Fix**: Apply ACES and then a simple sRGB gamma (≈2.2) is standard practice for a simple path tracer. This is acceptable.

**Verdict**: Acceptable for a demo renderer. No change.

---

### 4. JSON custom scene `cmd_render` is broken

In `cmd_render`, for `scene_name == "custom"`, the code calls `load_scene_json` to get a camera, then tries to reverse-engineer `cam_spec` from the Camera object using `cam_obj.lower_left + cam_obj.horizontal/2 + ...`. This reconstructed lookat is wrong because it doesn't account for focus_dist, and the function immediately overrides it anyway with `scene_name = None`. Then `render(None, json_path, cam_spec, ...)` is called but `cam_spec` was constructed from the broken reconstruction.

**Fix**: For custom JSON scenes, re-parse camera from JSON directly.

**Status**: REAL BUG — fix below.

---

### 5. PerlinTexture turbulence produces values > 1.0 in theory

`abs(2 * self._noise(p * 2**i) - 1)` maps [0,1] → [0,1]. Summing over `range(turb)` with coefficients `0.5**i` gives max sum of `sum(0.5**i for i in range(7)) ≈ 1.984`. But the value is then fed into `sin(...)` which stays in [-1,1], and the final `0.5*(1+sin(...))` stays in [0,1]. So values are properly bounded.

**Verdict**: Correct.

---

### 6. `World.hit` with empty objects list + no BVH

If `world.objects = []` and `build_bvh()` was called, `BVH([])` raises `ValueError("Empty BVH")`. This happens in `test_path_trace_sky_background` which creates `World()` with no objects and calls `build_bvh()`.

Wait — checking the code: `World.build_bvh()` only calls `BVH(self.objects)` if `self.objects` is truthy (i.e., non-empty). An empty list is falsy, so no BVH is built. Then `world.hit()` falls through to the linear scan, which returns `None`. This is correct.

**Verdict**: Correct. The test confirms this.

---

### 7. Multiprocessing pool may fail silently

`pool.imap_unordered(_render_tile, args_list)` — if a worker raises an exception, `imap_unordered` will re-raise it in the main process when the iterator is consumed. Good. But the error message will be unhelpful. 

**Low priority**. No change.

---

### 8. `_render_tile` rebuilds the scene from scratch for every tile

Every tile re-calls `SCENES[scene_name]()` or `load_scene_json(json_path)`, which includes re-building the BVH. For a 512×512 image with 256 tiles, this means 256 BVH builds. BVH build is fast for small scenes, but this is wasteful.

**Verdict**: Acceptable for a demo renderer with Python multiprocessing (can't share objects across processes). No change needed.

---

### 9. Sphere `pdf_value` can divide by zero

```python
solid_angle = 2 * math.pi * (1 - cos_max)
return 1.0 / solid_angle if solid_angle > 0 else 0.0
```

`cos_max = sqrt(1 - r²/d²)`. If `radius ≈ dist` (camera inside sphere), this goes to zero. Guard is present. ✓

---

## Performance Issues

### 10. Per-ray numpy array allocation (critical)

Every vec3 operation allocates a new numpy array. At 426 rays/sec (measured), rendering 400×400@80spp takes ~7.5 hours single-core. With 4 cores: ~2 hours.

**Fix applied**: Demo resolution reduced to 96×96@8spp (~90s total). Production-quality renders would need Numba JIT or a C extension. Documented in README.

---

## Minor Issues

### 11. `_CamSpec.focus_dist = None` causes serialization issues

`cam_spec.aspect = args.width / args.height` mutates the default cam spec in `_DEFAULT_CAMS`. Subsequent calls to `render` with the same scene get the modified aspect. This causes wrong aspect ratios in `cmd_demo` if scenes are rendered in any order that shares `_DEFAULT_CAMS`.

**Fix**: Use `copy.copy()` or pass a fresh `_CamSpec` each time.

**Status**: REAL BUG — fix below.

---

### 12. `make_gallery` writes relative paths for PNG `src=` attributes

The gallery uses `data:image/png;base64,...` (embedded), not file paths. This is correct and portable. ✓

---

### 13. `cmd_gallery` silently skips missing scenes

If some PNGs are absent, the gallery is built with whatever's present. A warning would be helpful but is cosmetic.

---

## Summary of Real Bugs to Fix

1. **Custom JSON scene camera reconstruction** — `cmd_render` for custom scenes passes a broken `cam_spec`. Fix: for JSON scenes, build `_CamSpec` directly from parsed JSON.
2. **`_DEFAULT_CAMS` aspect mutation** — `cmd_demo` and `cmd_render` mutate shared cam specs. Fix: use `copy.copy()`.

Everything else is either correct, acceptable, or a documented limitation.
