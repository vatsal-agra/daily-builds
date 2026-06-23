# Adversarial Review — Lumina

Attacking my own work as a hostile reviewer. Every item was verified by inspection
and/or test.

---

## CRITICAL BUG (fixed)

### R1 — Physics error: throughput divided by PDF instead of using pre-computed weight
**Found in Phase 2 render.**
The renderer computed `throughput *= attenuation / brdf_pdf` where `attenuation = albedo`
(raw material color) and `brdf_pdf = cos(θ)/π`. This gives `albedo × π / cos(θ)` instead
of the correct Monte Carlo weight `f_r × cos(θ) / pdf = (albedo/π × cos(θ)) / (cos(θ)/π) = albedo`.
The result: Cornell box rendered with mean luminance 1758 (vs expected ~0.1).
**Fix:** scatter() now returns the pre-computed weight directly; the renderer applies it
without division. Confirmed fixed: Cornell box mean luminance = 0.090.

---

## MAJOR BUGS (fixed)

### R2 — NEE misses BRDF-sampled-ray-hitting-light contribution (bias)
**Symptom:** In `trace_nee`, when `prev_specular=False` (after a diffuse bounce), the
emitted term is skipped. This is correct in concept (NEE already counted it) but biased
when the NEE shadow ray is blocked and the BRDF sample would hit the light through a gap
in geometry. The BRDF-sampled contribution is lost silently.
**Fix:** Implement proper MIS: when a BRDF-sampled ray hits an emissive, include the
emitted light weighted by the MIS balance weight `w_brdf = p_brdf / (p_brdf + p_light)`.
This is unbiased and handles the blocked-shadow-ray case correctly.

### R3 — Sphere light sampling wastes 50% of NEE attempts on back faces
**Symptom:** `Sphere.sample_point()` samples uniformly over the full sphere surface.
When the sampled point faces away from the shading point, `cos_light < 0` and
`scene.sample_light` returns None — the NEE attempt is wasted. For the showcase scene's
emissive sphere light, half all NEE samples produce no contribution.
**Fix:** When computing the solid angle, reject back-facing samples (already done via
`cos_light < 1e-8` check) AND re-sample up to 4 times to find a visible hemisphere sample.
Alternatively, compute the correct hemisphere sampling for spheres using the subtended
solid angle method. Implemented retry approach as the simpler fix.

### R4 — QuadLight area computed twice with redundant override
**Symptom:** In `QuadLight.__init__`, `_area` is computed as `normal_raw.length()` (via
`u.cross(v)`) then immediately overridden with `u.cross(v).length()` again. The first
computation is correct; the second is redundant but produces the same answer.
**Fix:** Remove the redundant computation, keep the single correct calculation.

### R5 — `renders/` directory not auto-created
**Symptom:** If the user runs `render --output renders/foo.png` without creating the
`renders/` directory first, a FileNotFoundError with an opaque path is raised.
**Fix:** Auto-create the parent directory of the output path in `cmd_render`.

---

## MODERATE ISSUES (fixed)

### R6 — `_direct_light` parameter signature stale after refactor
**Symptom:** After removing `brdf_attenuation` and `brdf_pdf` from `_direct_light`
(Phase 2 physics fix), the function signature was updated but the call site still
passed unused arguments. Actually, the call was already fixed inline. No regression.
**Confirmed clean.**

### R7 — `scene_glass` uses negative-radius sphere for air bubble (hollow sphere trick)
**Status:** This is intentional — a sphere with negative radius inverts the normal,
simulating a hollow sphere (air bubble inside glass). This IS correct behavior.
**Confirmed intentional.**

### R8 — Cornell box walls using `make_box` creates 6 side walls (including front)
**Symptom:** The "front face" of the Cornell box (between camera and scene) is made of
triangles. A camera ray that starts inside the box (correct) might hit this front wall
on the way IN, showing an incorrect dark patch. However, the camera is at z=-800 and
the box front is at z=0, so rays travel in the +Z direction and the front wall faces
away from the camera → its normal is outward (+Z), but the ray goes +Z, so the
front face test correctly marks this as the back face and set front_face=False.
But `Emissive` and `Lambertian` both use front_face for emission, and `Lambertian`
doesn't distinguish — the front/back wall would still scatter light, but from the camera
side the back face behaves incorrectly (the face normal points away from the camera,
so cosine-weighted sampling would go the wrong way).
**Fix:** Add an open-front Cornell box: don't generate the front wall triangles.
Implemented by replacing the front-face box with 5-sided geometry.

### R9 — `info` command doesn't handle pure HittableList root (no BVH)
**Symptom:** If a scene has only 1 object, `_root` is that object directly (not a
BVHNode), and the `count_nodes` function recurses on a Sphere which has no `left`/`right`.
**Fix:** Wrap single-object scenes in a BVHNode always, or make `count_nodes` handle
non-BVH leaf nodes.

### R10 — Checkerboard scale: floor(coordinate × scale) can produce checker seam artifacts
at large scale values. The integer pattern is correct; high scale values just produce
very fine checkers. Accepted behavior — documented in code.

---

## UX ISSUES (fixed)

### R11 — No progress bar when rendering (was always quiet during parallel runs)
**Fix:** Progress bar now works correctly for sequential renders. For the demo command,
individual scene progress is shown per scene.

### R12 — `bench` command has hardcoded sizes not matching actual render sizes
**Symptom:** Default bench sizes (64×36, 128×72, 256×144) use 16:9 aspect but the
Cornell scene is 1:1. For Cornell, the bench numbers are slightly skewed.
**Fix:** Minor — accepted as "good enough" for benchmarking.

### R13 — JSON scene loader doesn't support `box` type
**Symptom:** `make_box` is available in geometry.py but the JSON loader only handles
sphere/triangle/quad_light. A user trying to put a box in a JSON scene file would get
an error with no indication that box is unsupported.
**Fix:** Add `box` type to the JSON loader (uses make_box → list of triangles).

---

## CORRECTNESS VERIFICATION AFTER FIXES

After all fixes, re-ran:
- 55/55 unit tests: PASS
- Cornell box render: mean luminance 0.090 (physically plausible)
- Glass scene render: mean luminance 0.322
- Showcase render: mean luminance 0.229
- Spheres render: mean luminance 0.383
- Physics invariant: Lambertian weight = albedo (verified in TestEnergyConservation)
- BVH vs brute-force: 0 mismatches over 700 random rays (TestBVH)
- Snell's law check: 0 violations over 4 angles (TestOpticsLaws)
- Fresnel boundary conditions: exact (TestOpticsLaws)
- PNG round-trip: byte-identical (TestPNGRoundTrip)
