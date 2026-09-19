# Torque

A from-scratch 2D rigid-body physics engine, written in vanilla
JavaScript with zero dependencies, plus an interactive canvas playground
and a from-scratch test suite checked against real physics ground truth
instead of "looks about right."

## What it is

Torque implements the same core algorithm real 2D game physics engines
(Box2D, Chipmunk) are built on: an **impulse-based sequential solver**
over contacts and joints, with real per-shape mass/inertia tensors, warm
starting, Coulomb friction, and Baumgarte position correction. It handles
circles, arbitrary convex polygons, distance joints (rigid rods), and
revolute joints (pins), and ships with a live drag-and-drop playground
you can throw boxes around in.

- `engine/` — the physics engine itself. Eight small files, no build
  step, no bundler: the exact same source runs in Node (via CommonJS
  `require`) and in the browser (via plain `<script>` tags), so the code
  under test is identical to the code the demo runs live.
- `demo/` — an HTML5-canvas playground (`demo/index.html`).
- `tests/` — a hand-rolled Node test suite plus a Playwright-driven
  smoke test of the live playground.

## How to run it

**Playground:** open `demo/index.html` directly in a browser (no server,
no build step needed) — or serve the folder with anything static, e.g.
`python3 -m http.server` from the repo root and visit
`/2026-09-19-torque/demo/`.

**Tests:**
```
./demo.sh
```
Runs the 21-test physics suite (`node tests/run-all.js`) and, if
Playwright/Chromium is available, a live browser smoke test of the demo
(`node tests/smoke-demo.js`). Both are plain Node scripts if you want to
run them individually.

## Feature list

**Required (all 4 implemented and verified end-to-end):**

1. **Rigid body dynamics** — semi-implicit Euler integration of linear
   and angular velocity/position, with real analytical mass and
   rotational inertia per shape (not hardcoded constants): a circle's
   `1/2 m r^2`, and a general polygon's actual triangle-decomposition
   inertia integral (works for any convex polygon, verified against the
   standard rectangle formula as a special case).
2. **Collision detection** — broad-phase AABB sort-and-sweep to cull
   non-overlapping pairs, narrow-phase circle-circle, circle-polygon, and
   polygon-polygon via SAT with reference/incident-face clipping for a
   real up-to-2-point contact manifold (visible live via the demo's
   "Show contacts & joints" debug overlay).
3. **Impulse-based contact solver** — sequential impulse resolution with
   restitution, Coulomb friction (clamped to the normal impulse each
   iteration), warm starting (reusing the previous frame's impulse,
   matched by nearest contact point, as the next frame's starting guess),
   and Baumgarte position-error correction.
4. **Joints** — distance joints (fixed-length rods, used for Newton's
   cradle and the pendulum preset) and revolute joints (pins, used for
   the hanging-chain preset), solved in the same iterative velocity loop
   as contacts so a chain resting on a box stack behaves as one coupled
   system.

**Stretch (both implemented):**

5. **Sleeping bodies** — bodies below a velocity threshold for long
   enough stop being integrated/solved, and wake automatically when a
   moving body or joint touches them.
6. **Interactive canvas playground** — spawn circles/boxes/triangles/
   pentagons by clicking, drag anything around with a real mouse-joint
   (not a teleport hack — it has mass and inertia, so a flung box keeps
   its momentum), five one-click presets (box stack, Newton's cradle,
   pendulum, hanging chain, domino run), live gravity/restitution/
   friction sliders, pause/step/clear, and a debug overlay.

## Why this, today

This repo has a deep history of "from-scratch systems" builds — language
runtimes, distributed systems (Raft, a CRDT editor, a PoW blockchain), a
CPU pipeline simulator, an OS scheduler, a robot SLAM stack, an exchange
matching engine, and a couple of renderers — but none of them has modeled
**classical mechanics under contact and constraints**, which is a
different kind of correctness problem from anything prior here. There's
no single bit-exact right answer to check a physics engine against (unlike
two CPU models that must agree exactly, or a deterministic chain reorg);
instead correctness means the simulation obeys the *laws* the real world
obeys — an isolated elastic collision conserves momentum and energy, a
pendulum's period matches the textbook formula, a resting stack doesn't
sink through the floor or explode from numerical error. Holding a
"from-scratch" build to that standard, and finding it actually fails that
standard twice during review (see below), was the interesting part.

It's also the first build here written natively as an interactive browser
app with real mouse-driven physics, rather than a CLI or a Python
simulation exported to static frames — a good forcing function to prove
the engine is fast and stable enough to run live at 60fps under direct,
adversarial user interaction (flinging, spam-clicking, resizing
mid-drag), not just in a scripted batch demo.

## What the adversarial review actually caught

Full writeup in [REVIEW.md](./REVIEW.md), but the headline finding: a
revolute-jointed pendulum released from horizontal was supposed to swing
~57° in a third of a second (hand-derived from the real pendulum ODE). It
instead rotated ~0.001° and froze. The cause — jointed bodies' collision
shapes overlapping at their shared anchor (the default case for any chain
or pendulum built the direct way) made the contact solver fight the
joint's own constraint every single step. The fix, `collideConnected`
defaulting to `false` on both joint types, is the same fix Box2D and
every other engine with this problem converged on. A second, unrelated
bug made sleeping bodies falsely re-wake every frame when touching a
static body, because a static body's `isSleeping` flag is permanently
`false` in a way that isn't the same thing as "actively moving." Both are
regression-tested in `tests/joints.test.js` and `tests/dynamics.test.js`.

## Where a human could take this next

- **Continuous collision detection (CCD)** — the one accepted limitation
  in REVIEW.md: a small/fast body can tunnel through a thin static shape
  in a single large-`dt` step, the standard failure mode of discrete-time
  solvers.
- **More joint types** — a prismatic (slider) joint and a motor
  (driven revolute) would unlock vehicles and machinery scenes.
- **Soft bodies / cloth** — the contact solver's manifold generation and
  the joint solver's velocity-constraint machinery are most of what a
  particle-and-constraint cloth sim needs already.
- **Island-based sleeping and parallel solving** — the current sleep
  logic is per-body-with-neighbor-check; a proper union-find island
  system would let independent clusters (e.g. two separate box stacks)
  solve and sleep fully independently, and would parallelize cleanly.
- **A save/load and replay system** for the playground, now that the
  simulation is fully deterministic given fixed-step input.
