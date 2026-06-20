# Lumina — Adversarial Review

## Findings

### CRITICAL

**None** — no correctness-breaking bugs found in the physics or BVH core.

### HIGH

**1. NaN in path tracer causes bright white fireflies (PNG corruption)**
- Python's `min(1.0, nan)` returns `1.0` (not 0 or nan), so NaN radiance values produce
  white pixels instead of black. A degenerate scatter direction could cause a NaN in dot
  products, which then propagates through throughput and appears as a white firefly.
- Expected: NaN → clamped to 0 (black safe pixel).
- Fix: add `math.isfinite` guard in `gamma_correct` and sanitise in `tonemap`.

**2. `if args.width:` silently drops `--width 0` override**
- In `cmd_render`, all `if args.width:` / `if args.height:` guards evaluate to `False`
  for zero values, so `--width 0 --height 0` silently falls back to the scene's default.
  Users expecting an error get a quietly wrong render.
- Fix: change all guards to `if args.width is not None:` etc.

### MEDIUM

**3. `aces_film(nan)` returns 1.0 — same root cause as #1**
- `max(0.0, min(1.0, nan))` = `max(0.0, 1.0)` = `1.0` due to Python NaN comparison rules.
- Fix: explicit `math.isfinite(x)` check at the top of `aces_film`.

**4. `Box` first `self.faces` assignment is dead code**
- `Box.__init__` builds `self.faces` twice — the first assignment (wrong geometry) is
  immediately overwritten. Harmless but confusing; the dead code was never needed.
- Fix: remove the first `self.faces = [...]` block.

**5. `Plane.bounding_box` constructs a thick-slab AABB directly without padding**
- If `abs(n.x) > 0.9` and `abs(n.y) > 0.9` both fail (e.g. for a 45-degree plane),
  the code always falls through to the Z-slab case — the normal direction is not fully
  covered for arbitrary normals.
- Fix: use a general slab along the exact normal direction for arbitrary-normal planes.

**6. `cmd_render` defines `sky_colour_fn` that is never used in Whitted mode**
- A closure `def sky_colour_fn(ray=None): return sky_raw` is defined but not called.
  The `sky_colour=sky_raw` argument is passed directly and correctly.
- Fix: delete the dead closure.

**7. OBJ loader silently accepts 0-indexed faces (Python negative-index wrap-around)**
- `f 0 1 2` in an OBJ file should be invalid (OBJ is 1-indexed), but `0 - 1 = -1` is
  a valid Python list index (last element), producing silently wrong geometry.
- Fix: add a range check in `load_obj`: `if any(i < 0 or i >= len(vertices) ...)`.

### LOW

**8. Scene loader emits raw `KeyError` on missing required camera fields**
- A missing `look_from` key gives `KeyError: 'look_from'` with no context.
- Fix: wrap in a `try/except` with a descriptive message.

**9. `--width 0` / `--height 0` would cause `ZeroDivisionError` if the override
  actually worked (it currently doesn't due to bug #2)**
- Add dimension validation: `if W <= 0 or H <= 0: sys.exit("Error: width/height must be positive")`.

**10. `AABB` constructed directly with zero-thickness (flat) box is not padded**
- `AABB(Vec3(-1,0,-1), Vec3(1,0,1))` has Y-thickness = 0. This works correctly for
  all current uses (the AABB.hit code handles the parallel-to-slab case correctly),
  but SAH surface area = 0 for flat boxes, causing the SAH cost function to return
  infinity and fall back to a 50/50 split. This is a correctness concern only for
  nearly-flat scenes; current scenes are fine.

## Verification Status (post-fix targets)

- [ ] NaN pixels → black (white furnace stays 1.0 with no NaN input)
- [ ] `--width 0` prints error and exits with code 1
- [ ] Dead code in Box and cmd_render removed
- [ ] OBJ index validation
- [ ] All tests still pass

## What Works Correctly

- Physics: Snell's law refraction verified analytically (sin(θ)/1.5 = exact to 10⁻¹⁴)
- Schlick Fresnel: r₀ at cos=1 exactly 0.04, full reflection at cos=0 ✓
- BVH: 500/500 rays agree with brute force on 50 random spheres ✓
- BVH: 2000/2000 rays agree with brute force on 1025-triangle mesh; 70× speedup ✓
- Energy conservation: white furnace test gives r=g=b=1.000 ✓
- PNG encoder: 1×1, 10×10, HDR overflow all produce valid files ✓
- Negative-radius sphere (hollow glass): hits correctly, normal inverts ✓
- Box normals: all 6 faces point outward correctly ✓
- Triangle two-sided: front/back face flags correct ✓
- Quad: parametric UV bounds correct ✓
- DOF focus: all lens-offset rays converge at focal plane (spread < 0.001 units) ✓
- OBJ fan-triangulation of quad faces: 4-vertex face → 2 triangles ✓
- Scene loader: unknown primitive → ValueError, empty objects → OK ✓
