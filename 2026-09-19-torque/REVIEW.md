# Adversarial review

Hostile pass over the Phase 2 core build, looking specifically for the kind
of bug that doesn't show up in a five-second demo but ruins the engine the
moment someone builds a chain, a stack, or leaves it running: energy gain,
false convergence, and state that silently goes wrong.

## Bugs found and fixed

### 1. Sleeping bodies never actually stayed asleep (real, confirmed by trace)

`world.js`'s narrow phase woke a sleeping body whenever it was paired with
a body whose `isSleeping` flag was `false` -- but a **static** body's
`isSleeping` is permanently `false` (it's simply not a sleep-eligible
concept for something that never moves). A box resting on static ground
would go to sleep, and on the very next step the ground/box pair would
read `bodyA.isSleeping (false) !== bodyB.isSleeping (true)`, re-run the
narrow phase, and immediately call `setAwake(true)` on the box again --
forever. Traced with per-frame logging: `sleepTime` climbed to the 0.5s
threshold, the body slept for exactly one frame, then woke back up and
restarted the climb, in an endless cycle every single time any dynamic
body touched any static body.

**Fix:** redefined "active" as *dynamic and not sleeping* and required at
least one **active** neighbor (not just a non-sleeping one) before waking
a sleeping body, and skip narrow-phase work entirely when neither body in
a pair is active. Verified with a per-frame trace: a dropped box now
reaches `isSleeping: true` once and stays there indefinitely.

### 2. Jointed bodies fought their own joint through the contact solver (real, confirmed by trace)

This was the serious one. A revolute-jointed pendulum (anchor box + a link
box pinned at their shared corner) was supposed to swing from horizontal
and settle hanging straight down. Instead it barely rotated at all and
froze near its starting angle within a third of a second -- with no
damping configured. Hand-deriving the expected physical-pendulum angular
acceleration (`I·φ'' = -mgd·sinφ`) predicted ~57° of rotation in that same
0.33s; the engine produced ~0.001°.

Root cause, found by reproducing a single solver step by hand: the
anchor's and link's collision shapes **overlapped** at the shared pivot
(as jointed bodies' shapes almost always do -- a chain link and its
neighbor, a pendulum bob and its anchor). The contact solver was
generating a real penetration-correction contact between them on top of
the joint's own point constraint, and the two fought each other every
step -- the contact push and the joint's pull-back canceling out into
near-zero net motion instead of a swing. Confirmed by re-running the same
scenario with non-overlapping shapes: the pendulum swung exactly as the
hand-derived physics predicted (angular velocity growing smoothly,
matching the analytical value to 3 decimal places).

**Fix:** added `collideConnected` to both joint types, **defaulting to
false** (the same default Box2D and every other engine with this problem
settled on) -- two bodies linked by a joint no longer generate a contact
with each other. `world.js` rebuilds a no-collide pair set from the
current joint list each step and the narrow phase skips those pairs
entirely. Re-verified: the same pendulum now converges smoothly to
hanging straight down (`angle -> -π/2`) under damping, and a 6-link chain
that previously produced chaotic, exploding-looking motion now hangs in a
smooth monotonic curve.

### 3. `applyImpulse` could silently corrupt a sleeping body's velocity

`applyForce`/`applyTorque` already no-op on a sleeping body, but
`applyImpulse` (used by both the contact and joint solvers) only checked
`isStatic`. A joint connecting an awake body to a sleeping one would run
its solver on the sleeping body every step -- since nothing woke it (see
bug 4) -- and `applyImpulse` would still write into its velocity, which
the position integrator would never pick up (it skips sleeping bodies).
The body would carry a corrupted, invisible velocity until it next woke
by some other means, then visibly pop.

**Fix:** `applyImpulse` now no-ops on a sleeping body too, matching
`applyForce`/`applyTorque`, so a solver can never perturb a sleeping
body's velocity without going through `setAwake` first.

### 4. Sleeping bodies weren't woken by joints, only by contacts

Following directly from bug 3: `_narrowPhase` woke a sleeping body touched
by an active *contact*, but nothing did the equivalent for a sleeping body
linked to an active one purely by a *joint* (no touching shapes involved,
e.g. a chain link two links away from the moving end). Combined with bug
3's fix, such a body would now correctly never move but also never
resolve its joint constraint -- freezing the whole chain built on top of
it.

**Fix:** added `_wakeJointedSleepers()`, run every step before joints are
solved, mirroring the contact wake logic: a sleeping body jointed to an
active one wakes up.

## Checked and confirmed correct (not bugs)

Verified against ground truth rather than "looks plausible":

- **Elastic collision, damping disabled:** equal-mass head-on circle
  collision at v=3 swaps velocities exactly (`vA: 0.00000, vB: 3.00000`),
  momentum and energy conserved to float precision. With default damping
  enabled the same test showed ~2-5% loss over 2.5s -- correctly
  attributable to the nonzero default `linearDamping`/`angularDamping`
  (0.01), not the solver; confirmed by re-running with damping at 0.
- **Restitution:** a ball dropped with `restitution: 0.8` bounced back to
  92% of the energy-conservation prediction (measured peak 3.39 vs.
  predicted 3.38 for `0.5 + 0.64 * 4.5`).
- **Friction:** a box launched at 5 m/s along `friction: 0.8` ground comes
  to a complete stop within the simulated window.
- **Stacking:** 5-box stacks and rotated-square/vertex-landing drops
  settle without sinking through the floor or exploding, including the
  degenerate "balanced exactly on one corner" case (correct given a
  perfectly symmetric drop with zero initial angular velocity).
- **Joints:** revolute-jointed pendulum keeps anchor-to-bob distance
  within 0.3% over a full swing; distance joint likewise.
- **Non-axis-aligned SAT:** rotated boxes colliding at an angle, a
  triangle and a regular pentagon settling on flat ground, and a ball
  landing on a rotated box's vertex all produced finite, physically
  sensible results.
- **Input validation:** zero/negative density, negative radius, and
  degenerate (<3-vertex) polygons all throw at construction; `dt <= 0`
  throws at `World.step`; removing a body drops any joints that
  referenced it instead of crashing the next step.

## Minor cleanups (lazy shortcuts caught, not bugs)

- Removed a dead, never-read `id` field being copied onto solver contact
  points (a leftover from an earlier persistent-ID warm-start design that
  was replaced with the current nearest-point matching in `world.js`).
- `World.removeBody` left that pair's cached contact impulses in
  `_contactCache` forever (body ids are never reused). Fixed to prune
  matching cache entries on removal -- relevant because the interactive
  demo (Phase 4) spawns and removes bodies continuously in one long-lived
  `World`.

## Accepted limitation (not fixed, out of scope for this build)

No continuous collision detection (CCD): a small/fast body can tunnel
through a thin static shape in one large-`dt` step. This is a standard,
widely-accepted limitation of discrete-time impulse solvers (Box2D itself
ships without CCD enabled by default); mitigated in the demo by running at
a fixed 1/120s substep and by the broad-phase AABB margin, but not solved.
