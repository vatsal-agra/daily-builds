# Impulse

> Status: **Phase 5 — Verification complete.** 30 unit tests + a 10-check
> headless physics demo + a live HTTP server smoke test, all green. Run
> `./demo.sh` to reproduce. Shipping next.

A from-scratch 2D rigid-body physics engine (pure Python, zero dependencies)
with a real-time interactive browser sandbox.

## What's built so far

- `engine.py` — the physics engine: Vec2/Mat22 math, Circle/Polygon shapes
  with correct mass & moment of inertia, semi-implicit Euler integration,
  a spatial-hash broad phase, SAT narrow phase with clipped contact
  manifolds (circle-circle, circle-polygon, polygon-polygon), a
  sequential-impulse solver (restitution + Coulomb friction + Baumgarte
  positional correction), and three joint types (DistanceJoint,
  SpringJoint, PinJoint).
- `server.py` — a stdlib-only HTTP backend that runs the engine on a
  fixed-timestep thread and streams live state to the browser over
  Server-Sent Events, with REST endpoints for spawning shapes, grabbing
  and dragging bodies, tuning gravity/restitution/friction, pause/step/
  reset, and loading/exporting scenes.
- `static/` — a hand-styled dark-themed canvas sandbox: drag to spawn
  circles/boxes sized by drag distance, a grab tool (with a grab/grabbing
  cursor) to fling bodies around with a live mouse-spring, sliders for
  material/world params, a full debug overlay (contact points, contact
  normals, per-body velocity vectors, and the live broad-phase spatial-
  hash grid), and four preset scenes (pyramid, rope bridge, circle
  stack, Newton's cradle) — plus full scene save/export and load/import,
  including joints, so a saved bridge loads back as a bridge, not a pile
  of planks.

See [PLAN.md](PLAN.md) for the full architecture and feature list.

## Running it

```
python3 server.py 8765
# open http://localhost:8765
```

No dependencies to install — pure Python 3 stdlib.

## Verifying it

```
./demo.sh
```

Runs the 30-test unit suite (`tests/test_engine.py`), a headless physics
demo (`demo.py` — a box stack settling, a pin-joint pendulum staying
energy-bounded, a rope bridge sagging and holding a dropped boulder,
every collision-pair type), and a live server smoke test (spawns a body
over real HTTP, confirms it falls under gravity, loads every preset
scene, and re-checks the NaN-import regression from the adversarial
review).
