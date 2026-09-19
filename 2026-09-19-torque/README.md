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

See [PLAN.md](./PLAN.md) for the full architecture and feature list.
Next: adversarial review (Phase 3), then the stretch features and canvas
playground (Phase 4).
