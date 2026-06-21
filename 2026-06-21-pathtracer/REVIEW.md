# Adversarial Review — Pathtracer

## Issues Found

### ISSUE 1 — shapes.py:Sphere.hit — CRITICAL: Negative-radius sphere inverts normal
`outward_normal = (p - center) / self.radius` — when radius is negative (hollow-glass
trick from spheres_classic.json), the normal points INWARD.  HitRecord then computes
`front_face` relative to this flipped normal, which swaps the IOR ratio in Dielectric.
The hollow sphere refracts with 1/1.5 in both directions instead of entering and exiting.
**Fix:** always divide by `abs(self.radius)`.

### ISSUE 2 — renderer.py + scene.py — MAJOR: spp=0 causes ZeroDivisionError
`color = color / spp` crashes if the JSON sets `"spp": 0`.
**Fix:** clamp spp ≥ 1 in `load_scene()`.

### ISSUE 3 — shapes.py:Box.hit — MAJOR: Ray starting inside box returns None
When `hit_axis` is never set (all entry-slab t0 values are behind the ray origin),
the function erroneously returns None, missing the exit hit. Affects glass boxes,
Cornell-box corners, and any scene where a scattered ray starts just inside a box.
**Fix:** track exit axis separately; if `hit_axis_enter < 0` fall through to the
exit hit case.

### ISSUE 4 — vec3.py:schlick — MINOR: No floor clamp on cosine
`schlick(cosine, ...)` where `cosine` was already clamped by the caller at
the call sites but not inside the function itself. A cosine of, say, −1e-9 from
floating-point error makes `(1 − cosine)^5 > 1`.  **Fix:** clamp inside schlick.

### ISSUE 5 — materials.py:Metal.scatter — MINOR: Unnormalized scattered direction
`reflected + fuzz` is not normalized; while it doesn't affect intersection
correctness (t values scale proportionally), the direction stored in the Ray is
cleaner when normalised.  **Fix:** normalize before constructing the Ray.

### ISSUE 6 — bvh.py:_sah_split — MINOR: All-equal-centroid fallback silent
When all centroids are equal on every axis the function returns `(0, 0.0)`;
`_partition_at` returns 0, triggering the median fallback.  This is correct, but
the code comment is absent and the path is subtle.  **No fix required** (correct
behavior), but document it.

## What the reviewer called issues but were NOT
- **Russian roulette** (ISSUE 4 from reviewer): This is textbook unbiased MC
  path termination — not a bug.
- **Camera degenerate look_from==look_at**: Already handled by normalize() returning
  (0,0,1) fallback.
- **Empty scene**: `HittableList([])` is valid and renders the background.

## Fixes Applied
All five real issues above are fixed in the next commit.  After fixes, a fresh
run-through catches: hollow glass sphere correctly refracts, spp=0 raises a clear
ValueError, inside-box rays find the exit face, schlick is bounded, metal
directions are normalized.
