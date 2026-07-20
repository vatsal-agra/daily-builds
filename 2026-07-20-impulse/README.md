# Impulse

> Status: **Phase 2 — Core build complete.** All 5 required features work
> end-to-end. Adversarial review next.

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
  circles/boxes sized by drag distance, a grab tool to fling bodies
  around with a live mouse-spring, sliders for material/world params, a
  debug overlay (contact points + normals), and four preset scenes
  (pyramid, rope bridge, circle stack, Newton's cradle).

See [PLAN.md](PLAN.md) for the full architecture and feature list.

## Running it

```
python3 server.py 8765
# open http://localhost:8765
```

No dependencies to install — pure Python 3 stdlib.
