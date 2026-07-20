# Impulse

A from-scratch 2D rigid-body physics engine — pure Python, zero
dependencies (no numpy, no pymunk, no pygame) — with a real-time
interactive browser sandbox. Every falling box, every collision, every
joint constraint is computed live by a semi-implicit Euler integrator
and a sequential-impulse solver; nothing is pre-baked or scripted.

## What it is

`engine.py` implements the actual physics: circle and convex-polygon
rigid bodies with correct mass/moment-of-inertia, a spatial-hash broad
phase, SAT narrow-phase collision detection with clipped contact
manifolds (circle-circle, circle-polygon, polygon-polygon), a
sequential-impulse solver (restitution, Coulomb friction, Baumgarte
positional correction), and three joint types (rigid distance joints,
damped springs, and point-to-point pin joints). `server.py` drives that
engine on a fixed-timestep background thread and streams its state to
the browser over Server-Sent Events, with REST endpoints for every user
action. `static/` is a hand-styled canvas sandbox — the browser only
renders; it never simulates.

## How to run it

```
python3 server.py 8765
# open http://localhost:8765
```

Pure Python 3 standard library — nothing to `pip install`.

To verify everything works end-to-end:

```
./demo.sh
```

This runs the 30-test unit suite, a headless physics demo (box stack
settling, a pin-joint pendulum staying energy-bounded over 30 simulated
seconds, a rope bridge sagging under its own weight and holding a
dropped boulder, every collision-pair type), and a live HTTP smoke test
against a real running server instance.

## Feature list

**Core:**
1. **Rigid body dynamics** — circles and convex polygons (boxes are a
   polygon special case), correct per-shape mass/inertia, gravity,
   semi-implicit Euler integration of linear and angular velocity.
2. **Collision detection** — spatial-hash broad phase, SAT narrow phase
   with clipped contact-manifold generation (up to 2 contact points per
   polygon-polygon pair, not a single approximation).
3. **Impulse-based resolution** — sequential-impulse solver with
   restitution, Coulomb friction, and Baumgarte positional correction,
   iterated for stability under stacking (10 iterations/step).
4. **Joints** — rigid DistanceJoint (rods/rope segments), damped
   SpringJoint, and point-to-point PinJoint (revolute hinges).
5. **Interactive real-time sandbox** — drag-to-spawn circles/boxes sized
   by drag distance, a grab tool with a live mouse-spring to fling
   bodies (correctly picks the topmost body when shapes overlap),
   material/world sliders, pause/step/reset, and a live body-count/FPS
   HUD.

**Stretch:**
6. **Scene presets + full save/load** — four built-in scenes (box
   pyramid, rope bridge, circle stack, Newton's cradle) plus JSON
   export/import of the live scene, including all joints — a saved
   bridge loads back as a bridge, not a pile of disconnected planks.
7. **Debug visualization overlay** — contact points, contact normals,
   per-body velocity vectors, and the actual broad-phase spatial-hash
   grid the engine uses, all toggleable live.

## Why I built this today

No daily build so far has touched rigid-body dynamics, and it hits a
sweet spot: real numerical methods (integration, constraint solving),
real computational geometry (SAT, contact clipping), and a real-time
client-server systems problem (streaming physics state live), all in
service of something immediately, viscerally satisfying to watch work —
a box pyramid actually settling, a rope bridge actually sagging into a
catenary, a Newton's cradle actually transferring momentum through the
chain. It's also a domain with sharp, checkable correctness properties
(does the stack tip over? does the pendulum's rod length drift? does
energy roughly conserve?), which made the adversarial-review phase
unusually productive — see [REVIEW.md](REVIEW.md) for a critical bug
that would have been very easy to ship silently: a single malformed
coordinate (NaN, whether from a hand-edited scene file, a fast mouse
drag, or a flaky client) could permanently freeze the entire physics
thread with zero user-facing error.

## Where a human could take this next

- **Warm starting** — cache accumulated impulses between steps for
  faster convergence and less jitter under heavy stacking (the classic
  Box2D-style optimization this implementation deliberately skipped for
  simplicity).
- **More shapes** — capsules, or general concave polygons decomposed
  into convex pieces.
- **More joints** — motors (a PinJoint with a target angular velocity),
  angle limits, or a weld joint.
- **Continuous collision detection** — fast-moving small bodies can
  still tunnel through thin walls between steps; a swept-shape check
  would close that gap.
- **Multiplayer** — the server/SSE architecture already separates
  simulation from rendering; broadcasting one authoritative world to
  multiple simultaneous browser sessions (shared sandbox, or split
  input authority) would be a small step from here.
- **WASM port of the solver** for a version that runs client-side at
  higher fidelity without the network round-trip on every drag frame.

## Project layout

```
engine.py        Physics engine (pure Python, zero deps)
server.py        HTTP backend: physics thread + SSE + REST API
static/          Canvas sandbox UI (HTML/CSS/vanilla JS)
tests/            30 unit tests covering math, collisions, joints, restitution, friction
demo.py           Headless end-to-end verification demo
demo.sh           Full verification run (tests + demo + live server smoke test)
PLAN.md           Original architecture & feature plan
REVIEW.md         Adversarial review findings and fixes
```
