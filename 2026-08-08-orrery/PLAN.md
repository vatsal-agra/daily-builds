# Orrery — a from-scratch gravitational N-body simulator

## Concept

An **orrery** is a mechanical model of the solar system — gears turning
planets around a sun. This build is the computational version: a real
gravitational N-body simulator, written from scratch, that gets its orbits
from physics rather than from pre-baked animation keyframes.

Three numerical-methods problems make this genuinely interesting, not just
"balls attract each other":

1. **Force evaluation is O(N²)** for direct summation — fine for a handful
   of planets, hopeless for a star cluster. The classic fix is the
   **Barnes-Hut algorithm**: build an octree over the bodies, and let
   distant clusters of mass approximate to a single point (their center of
   mass) instead of visiting every body individually. This is one of the
   more elegant "trade a little accuracy for a lot of speed" ideas in
   computational physics, and it is genuinely tricky to get right (the
   opening-angle criterion, recursive center-of-mass accumulation, and the
   softening term that keeps close encounters from blowing up to infinite
   force all have real edge cases).

2. **Integrator choice determines whether orbits are real or decay.**
   Naive explicit Euler integration of an orbit visibly spirals outward
   over time — it does not conserve energy, no matter how small the
   timestep. A **symplectic** integrator (velocity Verlet / leapfrog)
   conserves energy on average and keeps closed orbits closed indefinitely.
   Building both and empirically showing the difference (Euler's orbit
   decaying/exploding vs. leapfrog's staying put, with measured energy
   drift over time) is a real, checkable claim, not a vibe.

3. **There is an actual ground truth to check against.** The unperturbed
   two-body problem has a closed-form analytic solution (Kepler's equation,
   solved via Newton-Raphson for eccentric anomaly). Seed a two-body
   scenario from real orbital elements, run it through the N-body
   integrator, and compare the simulated trajectory to the analytic
   ellipse at every step — if they match to numerical precision, the
   integrator is doing real physics, not just producing a plausible-looking
   animation. The three-body "figure-eight" choreography (Moore 1993 /
   Chenciner-Montgonery 2000) is used as a second, harder validation case:
   a famous periodic solution with no closed form, which the simulator
   should reproduce as a stable closed figure-eight rather than have it
   fly apart.

## Architecture

```
orrery/
  vector.py       Vec3 — dot/cross/norm, operator overloads, no numpy
  body.py         Body: position, velocity, mass, radius, name, color
  bruteforce.py   O(N^2) direct-summation gravity (reference/oracle)
  octree.py       Barnes-Hut octree: build, center-of-mass, opening-angle
                  force approximation, softened gravity
  integrator.py   Explicit Euler (for comparison) + symplectic leapfrog
                  (kick-drift-kick velocity Verlet); energy & angular
                  momentum accounting
  kepler.py       Orbital-elements -> state-vector conversion via Kepler's
                  equation (Newton-Raphson); analytic position-at-time
                  oracle for validation
  collision.py    Perfectly inelastic merge (momentum-conserving, radius
                  from constant-density volume)
  scenarios.py    Preset scenes: solar system (real approximate elements),
                  binary star, figure-eight three-body, Plummer-sphere
                  star cluster, galaxy collision (two Plummer disks)
  simulation.py   Simulation driver: step/run loop, trajectory recording,
                  energy/momentum history, JSON checkpoint save/load
  report.py       Self-contained HTML/Canvas trajectory visualizer +
                  Barnes-Hut accuracy/speed benchmark report
  cli.py          `orrery run|bench|viz|demo|info`
tests/            unittest suite (physics correctness, not just "it runs")
demo.sh           end-to-end walkthrough
```

Pure Python 3 stdlib only — no NumPy, no SciPy, no third-party deps — in
keeping with this repo's from-scratch tradition. Physics runs in true 3D
(Vec3, octree) even though most demo scenes are near-planar, so inclined
orbits and disk collisions are physically real rather than a 2D cheat.
The HTML visualizer does a simple rotating orthographic projection.

## Feature list

**Required (core, must work end-to-end):**

1. **Barnes-Hut octree force approximation** — O(N log N) gravity with a
   configurable opening angle (θ), softened at close range, verified
   against brute-force O(N²) summation (both on random clouds and on the
   θ→0 limit, where Barnes-Hut must reduce to exact brute force).
2. **Symplectic leapfrog integrator with measured energy conservation** —
   velocity-Verlet kick-drift-kick, run side-by-side against explicit
   Euler on the same scenario, with total energy and angular momentum
   tracked over the run and reported numerically (not just "looks stable").
3. **Kepler two-body analytic oracle** — orbital elements → state vectors
   (solving Kepler's equation via Newton-Raphson), and a differential test
   that runs a real two-body scenario through the N-body simulator and
   checks it stays within numerical tolerance of the closed-form ellipse
   over many orbital periods.
4. **Interactive HTML/Canvas visualizer** — self-contained single file,
   plays back a recorded simulation with trails, adjustable playback
   speed, zoom/pan, per-body info on click, and a live energy-drift graph.

**Stretch:**

5. **Collision/accretion model** — perfectly inelastic, momentum-conserving
   merges when bodies overlap, with radius derived from constant-density
   volume (mass grows, gravity of the survivor increases).
6. **Scenario library + Barnes-Hut benchmark report** — solar system
   (real approximate orbital elements for the 8 planets), the figure-eight
   three-body choreography, a collapsing Plummer-sphere star cluster, and
   a two-galaxy collision (two Plummer disks on an intercept course); plus
   a benchmark report measuring Barnes-Hut speed and accuracy vs.
   brute-force as N and θ vary.

## Why this today

The repo already has plenty of "physics from scratch" (2D rigid-body
engines, evolving creatures, fluid simulation) and plenty of "verify
against an independent oracle" builds (SAT solvers, diff/merge vs. real
git, compression codecs). Gravitational N-body sits in neither bucket —
it's a different force law, a different acceleration structure (octree
vs. broad-phase grid/BVH), and a different, genuinely elegant oracle
(closed-form Kepler orbits and the figure-eight choreography) — a fresh
combination for this repo, not a rename of something already shipped.
