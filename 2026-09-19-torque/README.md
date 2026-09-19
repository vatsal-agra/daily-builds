# Torque

A from-scratch 2D rigid-body physics engine in vanilla JavaScript — no
dependencies, no framework — with an interactive canvas playground and a
Node test suite checked against real physics ground truth.

**Status: Phase 2 (core build) complete.** All 4 required features are
implemented and manually verified end-to-end:

- Rigid body dynamics integration (semi-implicit Euler, real per-shape
  mass/inertia) — verified: a box dropped onto the ground settles at the
  expected resting height and goes to sleep.
- Collision detection (broad-phase AABB sweep + narrow-phase
  circle-circle / circle-polygon / polygon-polygon SAT with clipped
  manifolds) — verified: a 5-box stack settles without sinking or
  exploding.
- Impulse-based contact solver (warm starting, Coulomb friction,
  restitution, Baumgarte position correction) — verified: a perfectly
  elastic equal-mass head-on circle collision swaps velocities exactly
  (momentum and energy conserved to float precision with damping off); a
  ball dropped with restitution 0.8 bounces back to ~64% of its drop
  height as the physics predicts; a box sliding with friction 0.8 comes
  to a full stop.
- Joints (distance + revolute) — verified: a revolute-jointed pendulum
  keeps its anchor-to-bob distance within 0.3% over a full swing; a
  distance-jointed body oscillates like a pendulum.

**Status: Phase 3 (adversarial review) complete.** See
[REVIEW.md](./REVIEW.md) for the full hostile-review pass. It found and
fixed two real, confirmed-by-trace bugs: sleeping bodies that never
actually stayed asleep (a static neighbor's permanently-`false`
`isSleeping` flag kept re-waking them every frame), and jointed bodies
silently fighting their own joint through the contact solver whenever
their shapes overlapped at the anchor (the default case for any chain or
pendulum) -- confirmed by hand-deriving the expected pendulum physics and
finding the engine produced ~0.001° of rotation where ~57° was expected,
then tracing it to the missing `collideConnected` exclusion every other
engine with this problem has.

**Status: Phase 4 (stretch features + polish) complete.** Both stretch
features are shipped:

- **Sleeping bodies** (built during Phase 2/3, exercised hard by this
  phase's presets): resting stacks and settled pendulums measurably stop
  costing CPU.
- **Interactive canvas playground** (`demo/index.html`): spawn
  circles/boxes/triangles/pentagons by clicking, drag any shape around
  with the mouse via a real mouse-joint (not a teleport hack), five
  one-click presets (box stack, Newton's cradle, pendulum, hanging chain,
  domino run), live gravity/restitution/friction sliders, pause/step/clear,
  and a debug overlay that draws the actual contact points and joints the
  solver is using.

Verified live in headless Chromium (Playwright), not just by reading the
code: every preset, all four spawnable shapes, drag-and-drop, pause/step/
clear, the debug overlay, and a narrow mobile viewport were each
screenshotted and checked for console/page errors (zero found after
fixes). That pass caught and fixed three real UI-layer bugs the engine
tests below wouldn't have: the side panel rendering fully off-screen (a
flexbox `min-width` issue with `<canvas>`'s intrinsic size), the pendulum
preset's joint anchor being 4 units from the bob instead of at its center,
and the domino preset's first tile toppling away from the row instead of
into it (a rotation-direction sign error).

**Status: Phase 5 (verification) complete.** Run `./demo.sh` to execute
everything below in one shot:

- `tests/run-all.js` — 21 hand-rolled Node tests (zero test-framework
  dependency, matching the engine) across four suites (`shapes`,
  `dynamics`, `solver`, `joints`), checking analytical mass/inertia
  formulas, momentum/energy conservation, the restitution-predicted bounce
  height, friction bringing a slide to a stop, a measured pendulum period
  against `2*pi*sqrt(L/g)` within 3%, input validation, and dedicated
  regression tests for both bugs found in Phase 3 (sleep/wake, and
  `collideConnected`).
- `tests/smoke-demo.js` — drives the actual `demo/index.html` in headless
  Chromium via Playwright: all 4 shapes, all 5 presets, a real mouse drag,
  pause/step/clear, the debug overlay, and a mobile viewport, failing on
  any console/page error. `demo.sh` runs this too and skips it with a
  clear message (not a failure) if Playwright/Chromium isn't present.

Current result: **21/21 physics tests, 13/13 smoke checks, all green.**

See [PLAN.md](./PLAN.md) for architecture/feature list and
[REVIEW.md](./REVIEW.md) for the adversarial review. Next: final polish
and shipping (Phase 6).
