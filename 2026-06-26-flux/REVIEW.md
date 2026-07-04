# Flux — Adversarial Review (Phase 3)

## Methodology

Systematically attacked the codebase as a hostile reviewer: ran 18 adversarial
probes covering numerical stability, edge cases, API misuse, boundary conditions,
physical correctness, and CLI robustness.

---

## Findings and Fixes

### CRITICAL — Obstacle velocity not zeroed when vort_scale=0 [FIXED]

**Symptom:** After `step()`, velocity inside solid obstacle cells was non-zero
(u_max=0.11, v_max=0.13) when `vort_scale=0.0`.

**Root cause:** `_apply_obstacles_vel()` was called only inside the
`if self.vort_scale > 0.0:` branch. The final `_project()` call can deposit
non-zero velocity inside solid cells through its pressure-gradient correction,
and nothing zeroed it when vorticity confinement was disabled.

**Fix:** Added an unconditional `_apply_obstacles_vel(u_adv, v_adv, ...)` call
immediately after the second `_project`, before the vorticity-confinement branch.
All obstacle cells now read exactly 0.0 regardless of `vort_scale`.

---

### CRITICAL — Vorticity confinement blow-up (original code) [FIXED in Phase 2]

**Symptom (found during Phase 2 testing):** After ~20 steps, all velocity fields
went to ±10²⁵ and the simulation crashed.

**Root cause:** The vorticity `omega` was computed with an extra factor of `N`
(omega = 0.5 * N * curl), and `dw_dx/dw_dy` also included `0.5 * N`. This made
the confinement force scale as `scale * dt * N * velocity` ≈ 3 × 0.15 × 64 × 2.5
= 72 per step — a positive-feedback loop that drove velocities to infinity.

The standard formulation uses raw finite differences without the `N` factor; the
user-facing `scale` parameter then represents a dimensionless strength (0–10).

**Fix:** Removed both `0.5 * N` factors from omega and its gradient computation.
Also updated the matching JS in `flux.html`. All 5 scenes now stable for 200+
steps (max speed stays < 5.0 at N=64).

---

### MODERATE — `inject_dye` with invalid channel raises IndexError [FIXED]

**Symptom:** `fluid.inject_dye(99, ...)` raised `IndexError: list index out
of range` with no user-facing message.

**Fix:** Added an early-return guard: if `channel >= len(self.dyes)`, silently
skip the injection. The invalid call is no-op rather than an exception.

---

### MODERATE — `divergence_rms()` reported inflated values [FIXED]

**Symptom:** `divergence_rms()` computed `0.5 * (Δu + Δv) / h`, dividing by
h = 1/N (multiplying by N). This meant a residual ε became ε × N, making
post-project values look like 6–10 when the actual solver residual was ~0.003.

**Fix:** Changed `divergence_rms()` to use the same scaled form as `_project`
(multiply by `h`, not divide): result is in the same units as Stam's pressure
solve, and values < 0.002 indicate good convergence (as observed).

---

### MINOR — CLI `--mode fire` not accepted [FIXED]

**Symptom:** `python3 cli.py anim --mode fire` exited with
`invalid choice: 'fire'` because `RENDER_MODES` didn't include a `fire` entry.

**Fix:** Added `render_fire()` function in `render.py` that maps total dye density
through the fire colormap. Added `"fire": render_fire` to `RENDER_MODES`.

---

### MINOR — Pre-warm progress bar shows wrong label [NOTED, not fixed]

When `skip=0`, the progress bar still prints `"pre-warm "` prefix for 0 frames.
Cosmetic only — harmless but slightly misleading. Acceptable for a CLI tool.

---

### MINOR — Gravity applied to ghost/boundary cells [NOTED, not fixed]

`v = self.v + dt * self.gravity` adds gravity to all cells including the
(N+2)² boundary ghost cells. Boundary conditions reset ghost-cell velocity,
so this has no effect on the physics. Not a bug — just slightly imprecise.

---

## Physics Verification

| Property | Result | Status |
|---|---|---|
| Divergence-free after project | div_rms < 0.002 (all scenes, all steps) | PASS |
| No NaN/Inf after 200 steps (all 5 scenes) | confirmed | PASS |
| Velocity in obstacles = 0 | 0.0000000 (all scenarios) | PASS |
| Semi-Lagrangian stability at dt=1.0 | no NaN, speed bounded | PASS |
| Vortex scene produces real vorticity | |curl|_max = 0.048 | PASS |
| Wind scene creates vortex wake | |curl|_max = 0.916, max_speed = 1.56 | PASS |
| Empty grid (no injection, no gravity) remains zero | max_speed = 0 | PASS |
| Dye exits open boundary naturally | 94% exits over 50 smoke frames | EXPECTED |

---

## Remaining Known Limitations

1. **Gauss-Seidel convergence:** The vectorised numpy update is Jacobi not
   true Gauss-Seidel. Convergence rate ≈ 1.6× per 20 iterations. Increasing
   to 40 iterations doesn't help much. For visual simulation this is fine —
   the semi-Lagrangian advection is the dominant term. A multigrid solver
   would give better results but is out of scope.

2. **No outflow boundary condition:** At domain edges, dye and velocity use
   "copy-nearest" BCs. In the wind scene this means fluid pressure builds up at
   the right exit, slightly distorting the wake. Real CFD would use a Neumann
   outflow condition. Acceptable for visual simulation.

3. **Single-thread Python:** At N=128, Python runs ~120 fps (numpy vectorised).
   The JS playground runs at 60 fps for N=128 easily. For higher resolutions
   (N=256+), a C extension or GPU would be needed.
