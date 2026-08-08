# Orrery

**Status: shipped.** All 6 phases complete — see `PLAN.md` for the plan
and `REVIEW.md` for the adversarial review.

A from-scratch gravitational N-body simulator: a Barnes-Hut octree for
O(N log N) gravity, a symplectic leapfrog integrator (measured against
naive Euler), a Kepler two-body analytic oracle used both to seed real
orbits and to validate the integrator, collision/accretion, a scenario
library (solar system, binary star, the three-body figure-eight
choreography, a Plummer-sphere star cluster, a galaxy collision), and an
interactive HTML/Canvas trajectory viewer. Pure Python 3 stdlib — no
NumPy, no SciPy, no third-party dependencies anywhere.

## What it is

An **orrery** is a mechanical model of the solar system — gears turning
planets around a sun. This is the computational version: real orbits
computed from Newton's law of gravitation and a real numerical
integrator, not pre-baked animation keyframes. Three ideas make it more
than "balls attract each other":

1. **Barnes-Hut**: direct pairwise gravity is O(N²) — fine for 9 planets,
   hopeless for a star cluster. Barnes-Hut builds an octree and lets
   distant clusters of mass approximate to a single point at their
   center of mass, trading a little accuracy for a lot of speed.
2. **Symplectic integration matters, provably**: naive (explicit) Euler
   integration of an orbit visibly gains energy every step and spirals
   outward no matter how small the timestep gets. A symplectic
   (leapfrog / velocity-Verlet) integrator conserves energy to within
   machine precision on the same orbit. The build measures this
   directly rather than asserting it.
3. **There's real ground truth to check against**: the two-body problem
   has a closed-form solution (Kepler's equation, solved via
   Newton-Raphson). Seeding a scenario from real orbital elements and
   checking the N-body integrator's output against the analytic ellipse
   at every step turns "the physics is correct" from a vibe into a
   number. The three-body figure-eight choreography (a real, famous,
   *non*-closed-form periodic solution) is a second, harder check: does
   the simulator reproduce a delicate periodic dance, or does it drift?

## How to run it

```bash
cd 2026-08-08-orrery

# The whole thing, in one command: 106 unit tests, a self-checking
# physics walkthrough, and CLI smoke tests, exiting non-zero on any
# failure. ~10 seconds.
bash demo.sh
```

Or drive it directly:

```bash
python3 -m orrery.cli info                                            # list scenarios
python3 -m orrery.cli run --scenario solar_system --steps 3000 --report solar.html
python3 -m orrery.cli run --scenario plummer_cluster --n 80 --collisions --report cluster.html
python3 -m orrery.cli bench --out benchmark.html                       # Barnes-Hut vs brute force
python3 -m orrery.cli run --scenario binary_star --steps 500 --out ckpt.json
python3 -m orrery.cli resume ckpt.json --steps 500 --report resumed.html
```

Open any `--report ... .html` file directly in a browser — it's fully
self-contained (data + CSS + JS inlined), no server needed. Controls:
scroll to zoom, drag to pan, click a body to inspect it, space to
play/pause, arrow keys to step frame-by-frame, and (if the run had any)
click a collision event in the sidebar to jump straight to it.

## Full feature list

**Required:**

1. **Barnes-Hut octree gravity** (`orrery/octree.py`) — configurable
   opening angle θ, softened at close range, verified to match brute
   force at θ=0 to floating-point precision, and gracefully raises a
   clean error (not a raw `OverflowError`) on a genuine numerical
   singularity instead of crashing.
2. **Symplectic leapfrog integrator vs. explicit Euler**
   (`orrery/integrator.py`) — leapfrog holds energy drift near machine
   precision (~1e-10 relative) over multiple orbits; Euler visibly leaks
   ~12% on the identical orbit over the identical span. Both ship so the
   difference is measured, not just claimed.
3. **Kepler analytic oracle** (`orrery/kepler.py`) — orbital elements →
   state vectors via Newton-Raphson solution of Kepler's equation, used
   to seed every realistic scenario and to differentially test the
   N-body integrator against a closed-form ellipse.
4. **Interactive HTML/Canvas trajectory viewer** (`orrery/report.py`) —
   self-contained playback with trails, zoom/pan, per-body inspection
   (position, mass, live speed), a live energy-drift chart, and
   collision events surfaced on the timeline and in a clickable list.

**Stretch (both shipped):**

5. **Collision/accretion** (`orrery/collision.py`) — perfectly inelastic,
   momentum-conserving merges when bodies overlap; radius grows by
   constant-density volume; chain merges (A absorbs B, the grown A then
   also overlaps C) resolve correctly in one step.
6. **Scenario library + Barnes-Hut benchmark report**
   (`orrery/scenarios.py`, `orrery bench`) — solar system (real
   approximate elements for the Sun + 8 planets), binary star, the
   figure-eight three-body choreography, a Plummer-sphere star cluster,
   a two-galaxy collision; plus a benchmark report that shows Barnes-Hut
   actually is slower than brute force below N≈300-400 in pure Python
   (tree-build overhead), and wins by ~2-5x at N=1000-2500 — the honest
   crossover, not an assumed universal speedup.

**Also shipped:** JSON checkpoint save/resume, keyboard shortcuts
(space/arrows) in the viewer, and a CLI (`run` / `resume` / `bench` /
`info` / `demo`) with clean, actionable errors on every bad-input path
tested (unknown scenario, negative/zero body count, non-positive dt,
missing/corrupt checkpoint, an early-closing pipe).

## Why this today

The repo already has a lot of "physics from scratch" (2D rigid-body
engines, evolving creatures, fluid simulation) and a lot of "verify
against an independent oracle" builds (SAT solvers, diff/merge vs. real
git, compression codecs), but nothing in the gravitational N-body space.
It's a genuinely different force law, a different acceleration structure
(octree vs. broad-phase grid/BVH), and a different, elegant oracle
(closed-form Kepler orbits, the figure-eight choreography) — a fresh
combination, not a rename of something already shipped. It also gives an
honest, measurable answer to a real question ("does Barnes-Hut actually
help, and at what N?") rather than a plausible-sounding claim.

## Adversarial review highlights

Full detail in `REVIEW.md`. Found and fixed 7 real issues: two crash bugs
(a raw `ZeroDivisionError` on `--n 0`, and a raw `OverflowError` on a
physically tiny close encounter with `softening=0` that completely
bypassed the "simulation diverged" safety net), a raw `BrokenPipeError`
crash found while writing the verification script itself, three HTML
report UX bugs (a `|v|` field that could never work because velocity was
never exported to the client; every body — including the Sun! —
rendering at nearly the same marker size; a default camera view that
scrunched the solar system's inner planets into unreadable overlapping
pixels), and one silently-ignored-flag issue. Also disclosed, not
fixed-because-not-broken: Barnes-Hut's real small-N slowdown (kept and
made visible in the benchmark rather than hidden), and the deliberately
scoped two-body-only Kepler oracle (parabolic/hyperbolic orbits are out
of scope — nothing in this build needs them).

## Where a human could take this next

- **Higher-order integrators.** A 4th-order symplectic integrator (e.g.
  Forest-Ruth or Yoshida) would tighten the Kepler-oracle match further
  and handle stiffer close encounters better than leapfrog without
  shrinking the timestep as much.
- **Adaptive timestepping**, especially for the star-cluster/galaxy
  scenarios where a handful of close encounters dictate the stable dt
  for the whole simulation.
- **A real 3D viewer.** The current viewer's projection is a fixed
  orthographic rotation; free-orbit camera controls (drag to rotate, not
  just pan) would make the inclined orbits and disk collisions much
  easier to read.
- **General relativistic corrections** (e.g. a 1PN term) would let it
  reproduce Mercury's perihelion precession — a famous, checkable,
  historically important number that pure Newtonian gravity gets
  slightly wrong.
- **Parallelizing Barnes-Hut** (multiprocessing tile-style, like some of
  this repo's ray tracers) — force evaluation is embarrassingly parallel
  per body once the tree is built.
- **A real ephemeris.** Swap the hand-picked orbital elements for actual
  JPL/NASA data (network access was unavailable in this sandbox) for a
  solar system that matches the real sky on a given date.
