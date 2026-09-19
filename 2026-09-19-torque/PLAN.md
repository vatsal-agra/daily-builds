# Torque — a from-scratch 2D rigid-body physics engine

## Concept

A 2D rigid-body physics engine, written from scratch in vanilla JavaScript
(no Box2D, no matter.js, no npm dependencies at all), implementing the same
core algorithm real game engines use: an **impulse-based sequential solver**
over contacts and joints, with proper mass/inertia tensors, warm starting,
Coulomb friction, and position correction. It ships with an interactive
HTML5-canvas playground (drag bodies, spawn shapes, load presets) and a
headless Node test suite that checks the engine against physics ground
truth — momentum conservation, analytical pendulum period, energy behavior,
and stack stability — not just "it looks right on screen".

## Why this is interesting

This repo has a deep "from-scratch systems" history — language runtimes
(Coil, Kiln, Ember, Unify), distributed systems (Quorum's Raft, Concord's
CRDT, Vein's PoW blockchain), a CPU pipeline simulator (Silicon), an OS
scheduler + VM manager (Quantum), a robot SLAM stack (Beacon), an exchange
matching engine (Matchbook), and renderers (Prism's rasterizer, Pathtracer).
None of them has modeled **classical mechanics under contact and
constraints** — the actual algorithm behind every 2D game physics engine
(Box2D, Chipmunk) and the collision/constraint layer under every 3D engine
too. It's a genuinely different kind of correctness problem from anything
prior in this repo: there's no single "right answer" state to check bit-for-
bit (unlike Silicon's two CPU models, or Vein's deterministic reorg) —
instead correctness means the simulation obeys the *laws* the real world
obeys (momentum is conserved in an isolated collision, a pendulum's period
matches the textbook formula, a resting stack of boxes stays put instead of
sinking through the floor or exploding from numerical error). That's a
different, arguably harder, kind of ground truth to hold a "from-scratch"
build to, and this repo hasn't tried it yet.

It's also the first build in this repo's history written natively as
interactive browser JS with a genuine drag-and-drop playground, rather than
a Python simulation exported to static PNG frames (Prism) or a CLI (most
others) — good excuse to prove the engine is fast and stable enough to run
live in real time, at 60fps, under direct user interaction, not just in a
batch script.

## Architecture

```
torque/
  engine/
    vec2.js        - 2D vector math (add/sub/scale/dot/cross/rotate/normalize)
    shapes.js       - Circle, Polygon (incl. box helper); centroid, area,
                      and analytical moment-of-inertia formulas per shape
    body.js         - RigidBody: transform, linear/angular velocity, mass &
                      inverse mass, inertia & inverse inertia, force/torque
                      accumulators, restitution, friction, sleep state
    aabb.js         - axis-aligned bounding box + broad-phase sweep-and-prune
    collision.js    - narrow-phase: circle-circle, circle-polygon,
                      polygon-polygon (SAT + reference/incident face contact
                      clipping -> up to 2-point contact manifolds)
    solver.js       - sequential-impulse contact solver: warm-started normal
                      + friction impulses, Baumgarte position correction,
                      per-manifold accumulated impulse caching across frames
    joints.js       - DistanceJoint (rigid rod) and RevoluteJoint (pin), each
                      with its own velocity-constraint Jacobian and bias
    world.js         - World: body/joint registry, fixed-step loop (broad
                      phase -> narrow phase -> velocity solve (contacts +
                      joints, N iterations) -> integrate -> position solve
                      -> sleep/wake bookkeeping)
  demo/
    index.html, demo.js, style.css
                    - canvas playground: spawn circles/boxes, drag with the
                      mouse (implemented as a temporary stiff distance
                      joint, not teleportation), gravity/restitution/
                      friction sliders, and presets (box stack, Newton's
                      cradle, pendulum, chain/ragdoll, domino run)
  tests/
    *.test.js       - Node-run scripts (no test framework dependency;
                      hand-rolled assert + pass/fail summary) checking the
                      engine against analytical/conservation ground truth
  demo.sh           - runs the full test suite + a Playwright screenshot
                      smoke check of the live playground
```

All engine files are written UMD-style (`module.exports` in Node,
`window.Torque.X` in the browser) from a single source file each — no
bundler, no build step, no framework — so the exact same engine code that
Node tests exercise headlessly is what the browser loads and runs live.

## Feature list

**Required (core, must work end-to-end):**

1. **Rigid body dynamics integration** — semi-implicit (symplectic) Euler
   integration of linear and angular velocity/position under gravity and
   accumulated forces/torques, with correct per-shape mass and rotational
   inertia (circle: `1/2 m r^2`; polygon: real polygon inertia formula via
   the shoelace/triangle-decomposition integral, not a hardcoded constant).
2. **Collision detection** — broad-phase AABB sweep-and-prune to cull
   non-overlapping pairs, narrow-phase circle-circle, circle-polygon, and
   polygon-polygon SAT with clipped contact manifolds (correct contact
   points and penetration depth, not just a boolean).
3. **Impulse-based contact solver** — sequential impulse resolution with
   restitution (bounciness), Coulomb friction (both static-like and
   kinetic, via the friction-impulse clamp against the normal impulse),
   warm starting (reusing last frame's impulse as the initial guess for
   faster convergence and stability), and Baumgarte position correction to
   fix penetration without adding energy.
4. **Joint constraints** — distance joints and revolute (pin) joints solved
   in the same iterative velocity-constraint loop as contacts, so a chain
   of pinned bodies and a pile of boxes interact correctly in one world.

**Stretch (2+, implement at least 1):**

5. **Sleeping bodies** — bodies whose linear/angular velocity stays below a
   threshold for long enough are put to sleep (skipped in integration and
   solving) and woken by a new contact or joint impulse touching them, for
   stability and performance in resting stacks.
6. **Interactive canvas playground** — live drag-and-drop (via a mouse
   joint, not a teleport hack), spawnable shapes, tunable
   gravity/restitution/friction, and one-click presets (box stack, Newton's
   cradle, pendulum, hanging chain, domino run) that exercise every
   required feature live in the browser at 60fps.
