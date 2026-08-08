# Orrery

**Status: Phase 2 complete — core build.** All 4 required features are
implemented and demonstrably working end-to-end. See `PLAN.md` for the
full concept and feature list.

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

Adversarial review, polish, verification, and the full README are still
to come in later phases.
