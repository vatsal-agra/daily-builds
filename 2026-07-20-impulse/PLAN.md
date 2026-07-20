# Impulse — a from-scratch 2D rigid-body physics engine with a live sandbox

## Concept

A real 2D physics engine — the kind that powers Box2D, Matter.js, Chipmunk —
built from first principles in pure Python (no numpy, no pymunk, no pygame),
plus a real-time interactive browser sandbox to play with it. No canned
animations, no pre-baked trajectories: every falling box, every collision,
every joint constraint is computed by a semi-implicit Euler integrator and a
sequential-impulse solver, stepped live and streamed to the browser.

## Why this is interesting

Physics engines sit at the intersection of numerical methods, geometry, and
real-time systems engineering — narrow-phase collision detection (SAT with
contact manifold clipping), constraint solving (sequential impulses with
Baumgarte stabilization), and a live client-server loop are each nontrivial
on their own. Building all three from scratch, correctly, in one day, and
making the result interactive (not just a batch demo) is a genuine
engineering exercise with an immediately satisfying, visual payoff. No prior
daily build has touched rigid-body dynamics.

## Architecture

```
2026-07-20-impulse/
  engine.py        Core physics engine (pure Python, zero deps)
                      Vec2 — 2D vector math
                      Shape — Circle, Polygon (incl. Box factory)
                      Body — mass/inertia, position, velocity, angle, angular velocity
                      World — gravity, broad-phase, narrow-phase, solver, joints, step()
                      Joints — DistanceJoint, SpringJoint, PinJoint (all velocity-impulse based)
  server.py         stdlib http.server backend:
                      - runs World.step() on a fixed-timestep background thread
                      - streams world state to the browser via Server-Sent Events
                      - exposes REST endpoints for spawn/drag/reset/save/load/params
  static/
    index.html      Sandbox page shell
    style.css       Hand-styled dark UI (not default browser styling)
    app.js          Canvas renderer + input handling (drag-to-spawn, mouse-joint drag,
                      toolbar, sliders, debug overlay, scene save/load)
  tests/
    test_engine.py  unittest suite: vector math, integration, every collision pair,
                      restitution/friction correctness, every joint type, energy/momentum checks
  demo.py           Headless script exercising every engine feature end-to-end, prints
                      a verification report (also importable by tests)
  demo.sh           Runs the full test suite + demo.py + a server smoke test
  scenes/           JSON preset scenes (pyramid, bridge, cradle, box stack)
  PLAN.md / README.md / REVIEW.md
```

Data flow: the browser never runs physics. It renders whatever `World`
computes and sends user intent (spawn a shape at (x,y), grab body N and drag
to (x,y), change gravity/restitution/friction, pause/step/reset, save/load a
scene) as small POSTs. The World thread applies those intents between steps.
This keeps *one* physics implementation as the single source of truth —
testable headlessly and drivable live — rather than duplicating engine logic
in JS.

## Feature list

**Required (core, must fully work end-to-end):**

1. **Rigid body dynamics** — circles and convex polygons (boxes are a
   polygon special case), correct mass/moment-of-inertia computation per
   shape, gravity, semi-implicit Euler integration of linear + angular
   velocity, linear/angular damping.
2. **Collision detection** — broad-phase uniform spatial hash grid to avoid
   O(n²) pair checks, narrow-phase via circle-circle, circle-polygon, and
   polygon-polygon SAT with clipped contact-manifold generation (1-2 contact
   points per pair, not just a single approximate point).
3. **Impulse-based collision resolution** — sequential-impulse solver with
   restitution (bounciness), Coulomb friction, and Baumgarte positional
   correction to stop bodies sinking into each other, solved over multiple
   iterations per step for stability under stacking.
4. **Joints/constraints** — DistanceJoint (rigid rod between two bodies or a
   body and a fixed anchor), SpringJoint (damped elastic connection), and
   PinJoint (revolute joint pinning a body point to a world anchor), all
   solved as velocity constraints alongside collisions.
5. **Interactive real-time web sandbox** — HTML5 canvas rendering at 60fps,
   click-drag to spawn circles/boxes (drag distance sets size), click a body
   and drag to fling it via a live mouse-spring, toolbar for shape/tool
   selection, sliders for gravity/restitution/friction, pause/step/reset,
   HUD showing body count and live FPS.

*(That's 5 — the plan requires at least 4; all 5 are treated as required
since together they're the minimum for a physics engine that is actually a
physics engine rather than a toy.)*

**Stretch:**

6. **Scene presets + save/load** — built-in preset scenes (box pyramid,
   rope bridge of distance joints, circle stack, Newton's-cradle-style pin
   chain) selectable from the UI, plus exporting/importing the live scene as
   JSON.
7. **Debug visualization overlay** — toggle to draw contact points, contact
   normals, velocity vectors, and broad-phase grid cells directly on canvas,
   for both aesthetics and genuinely understanding solver behavior.

## Verification plan

`tests/test_engine.py` unit-tests vector math, per-shape inertia, single-step
integration, every collision pair type, restitution edge cases (e1 vs
e0 vs e0.5), friction (an object on a ramp above/below the friction angle),
and every joint type's constraint error converging toward zero. `demo.py`
runs longer headless simulations (a box stack settling, a pendulum on a pin
joint conserving energy within tolerance, a bridge under load) and asserts
end states. `demo.sh` ties it together plus a live server smoke test
(spawn a body via HTTP, read the SSE stream, confirm it falls under
gravity).
