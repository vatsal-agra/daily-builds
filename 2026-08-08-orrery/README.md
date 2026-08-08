# Orrery

**Status: Phase 3 complete — adversarial review.** All 4 required
features are implemented and working end-to-end; 6 real bugs (2 crash
bugs, 3 UX bugs, 1 silently-ignored-flag issue) found and fixed. See
`PLAN.md` for the concept/feature list and `REVIEW.md` for the full
review.

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

Polish, stretch features, verification, and the full README are still to
come in later phases.
