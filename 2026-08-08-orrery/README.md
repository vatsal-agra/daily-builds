# Orrery

**Status: Phase 4 complete — stretch + polish.** All 4 required features
plus both planned stretch features are implemented and working
end-to-end. See `PLAN.md` for the concept/feature list and `REVIEW.md`
for the adversarial review.

A from-scratch gravitational N-body simulator: Barnes-Hut octree force
approximation, a symplectic leapfrog integrator (measured against naive
Euler), a Kepler two-body analytic oracle for validation, and an
interactive HTML/Canvas trajectory visualizer. Pure Python 3 stdlib, no
dependencies.

## Try it now

```
cd 2026-08-08-orrery
python3 -m orrery.cli demo --outdir demo_output
```

This runs a self-checking walkthrough (Barnes-Hut vs. brute force,
leapfrog vs. Euler energy conservation, the Kepler oracle, the
figure-eight three-body choreography, collisions, and full scenario
runs), printing PASS/FAIL for each check, and writes interactive HTML
reports to `demo_output/`.

```
python3 -m orrery.cli info                                   # list scenarios
python3 -m orrery.cli run --scenario solar_system --steps 2000 --report out.html
python3 -m orrery.cli bench --out benchmark.html              # Barnes-Hut vs brute force
```

## What's implemented so far (Phase 2)

1. **Barnes-Hut octree** (`orrery/octree.py`) — O(N log N) gravity via
   center-of-mass approximation, verified to match brute force at
   theta=0 to floating-point precision.
2. **Symplectic leapfrog integrator** (`orrery/integrator.py`) —
   measured energy drift near machine precision over multiple orbits,
   vs. explicit Euler's real, visible energy leak on the same orbit.
3. **Kepler analytic oracle** (`orrery/kepler.py`) — orbital elements to
   state vectors via Newton-Raphson solution of Kepler's equation; used
   both to seed realistic scenarios and as a ground-truth check on the
   N-body integrator.
4. **Interactive HTML/Canvas visualizer** (`orrery/report.py`) —
   self-contained trajectory playback with trails, zoom/pan, per-body
   inspection, and a live energy-drift chart.

Scenario library so far: `solar_system`, `binary_star`, `figure_eight`
(the three-body choreography), `plummer_cluster`, `galaxy_collision`.
Collision/accretion merging is also implemented (stretch feature).

## Phase 3: adversarial review

Found and fixed 6 real issues — see `REVIEW.md` for full detail:

- Two crash bugs: a raw `ZeroDivisionError` on `--n 0`/negative cluster
  size, and a raw `OverflowError` on physically-tiny close encounters
  with `softening=0` (bypassed the "simulation diverged" safety net
  entirely). Both now raise clean, actionable errors.
- Three UX bugs in the HTML report: a `|v|` speed field that could never
  work (velocity was never exported to the client), every body rendering
  at nearly the same marker size (the Sun indistinguishable from
  Mercury), and a default camera view that scrunched the solar system's
  inner planets into unreadable overlapping pixels.
- Extended the Barnes-Hut benchmark's N range after discovering (and
  keeping, not hiding) a real finding: Barnes-Hut is *slower* than brute
  force below N≈300-400 in pure Python — tree-build overhead has to be
  paid back. The benchmark now runs far enough (N=1000+) to show the
  actual crossover instead of implying a universal speedup.

## Phase 4: stretch + polish

Both planned stretch features were already working end-to-end from Phase
2/3 (collision/accretion; the scenario library + Barnes-Hut benchmark
report) and got extra polish this phase:

- **Collision visibility.** Previously a merge was only visible as a body
  silently vanishing and the count dropping by one. The trajectory viewer
  now lists every collision event in the sidebar (survivor, absorbed,
  time), red tick marks appear on the timeline at each merge, and
  clicking an event jumps playback straight to it.
- **Keyboard shortcuts.** Space to play/pause, ←/→ to step one frame,
  Home/End to jump to the start/end.
- All of Phase 3's fixes (clean errors on bad input, the marker-sizing
  and speed-field bugs, the camera presets) carried through unchanged —
  re-verified via a full headless-Chromium pass with zero console errors
  across every report, including the new collision UI (click-to-jump,
  keyboard shortcuts).

Verification (formal test suite + demo.sh) and the final README are next.
