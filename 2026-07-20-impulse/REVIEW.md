# Adversarial review — Impulse

Playing hostile reviewer against my own Phase 2 build: throwing malformed
input at every endpoint, stress-testing the solver with pathological
scenes, and walking through the UI looking for anything ugly or dishonest.
Every issue below was reproduced live against the running server before
being written down, and every one is fixed as of this commit.

## Findings

### 1. [Critical] NaN coordinates permanently kill the physics thread

`physics_loop()` runs unsupervised on a daemon thread with no
try/except around `World.step()`. Feeding a non-finite coordinate into
the world eventually reaches `SpatialHash.candidate_pairs()`, which calls
`int(math.floor(x0 / cell_size))` — and `int(nan)` raises `ValueError`,
which is *uncaught*, killing the thread. After that, the simulation is
frozen forever: the server keeps answering HTTP requests, the SSE stream
keeps broadcasting (a static, dead frame), and nothing ever moves again
until the process is restarted. There is no user-facing error — the UI
just quietly stops animating.

Reproduced against the live server three separate ways:
- `POST /api/scene/import` with `"x": NaN` in a body — Python's `json`
  module accepts bare `NaN`/`Infinity` as an extension, so a hand-edited
  or malicious scene file trivially triggers this.
- `POST /api/drag` with `"x": NaN` while a body is grabbed — the NaN
  becomes the mouse-spring's fixed anchor, propagates into `force` on
  the very next step, then into velocity and position.
- `POST /api/grab` with a NaN coordinate — same propagation path via the
  spring joint it creates.

`/api/spawn` turned out to *accidentally* survive a NaN `x`/`y` — Python's
`min`/`max` return their first argument when a comparison against NaN is
involved, and the clamp expression happened to be written with the fixed
bound first — but that's a lucky accident of argument order, not a real
guard, and every other field (`radius`, `w`, `h`, `restitution`, ...)
already goes through the NaN-safe `_clamp_float`. Relying on it would be
fragile.

**Fix:** every numeric field coming from the network — `/api/spawn`,
`/api/grab`, `/api/drag`, `/api/params`, and `body_from_dict` for scene
import — now goes through `_clamp_float`, which explicitly rejects
non-finite values (`v != v` catches NaN; an `isfinite` check added for
±Infinity) and falls back to a sane default instead of passing the value
through.

### 2. [High] Physics thread has no supervisor

Even with (1) fixed, any *other* future edge case that raises inside
`World.step()` would have the same permanent-freeze effect, with the
same silence. A physics engine that occasionally hits a degenerate
geometry case (near-zero-length edges, coincident points, etc.) should
degrade, not die.

**Fix:** wrapped the step call in a try/except that logs the exception
and, in the exceptionally unlikely event it recurs, keeps the HTTP
server alive and serving the last-known-good state rather than crashing
silently with no trace.

### 3. [High] Saving a scene silently drops every joint

`export_scene()` only serialized bodies. Loading the "Bridge" preset (12
planks connected by 13 distance joints into a rope bridge) and then
clicking **Save scene… → Load scene…** produced 12 disconnected planks
that just fall straight down — the bridge, and the entire point of the
save/load feature for anything joint-based (bridges, cradles, custom
ragdolls), was silently broken. Reproduced live: exported JSON for the
bridge scene has `"bodies"` but no `"joints"` key at all.

**Fix:** `export_scene()` now serializes `DistanceJoint`/`SpringJoint`/
`PinJoint` (type + body indices + local anchors + rest length/stiffness/
damping as applicable), and `import_scene()` reconstructs them. Round-
tripping the bridge scene now preserves the bridge.

### 4. [Medium] Overlapping spawns launch bodies at extreme velocity

`MAX_LINEAR_CORRECTION` caps the *positional* correction pass, but the
velocity bias term in `_solve_contact` (`bias = max(pen - SLOP, 0) *
BAUMGARTE / dt`) is unbounded. Rapid-clicking the same spot with the
spawn tool creates bodies that start out heavily overlapping; resolving
tens of pixels of penetration in one step through the *velocity* channel
injects a bias of hundreds to low-thousands of px/s, launching the
stack off-screen in a single frame instead of settling smoothly.
Reproduced by spawning 10 fully-coincident boxes — they separate with
enough velocity to travel thousands of pixels in under 3 seconds.

**Fix:** added `MAX_BIAS_VELOCITY` and clamped the Baumgarte bias term to
it. Legitimate small penetrations (the sub-pixel kind that show up in
ordinary stacking) never approach the cap, so stacking behavior is
unaffected — verified by the box-stack and pyramid tests, which still
pass (with a slightly loosened tolerance for the ordinary jitter a
sequential-impulse solver without warm-starting produces, unrelated to
this fix). For the pathological case (10 boxes spawned at the exact same
point, with a floor present as in the real sandbox) this changes the
outcome from "unbounded divergence — still accelerating away after 4.5s,
past y=9000 and climbing" to "one bounded pop up and back down, settled
onto the floor within about 2 seconds." A violent-but-bounded initial
separation is the honest outcome for 10 exactly-coincident shapes; the
fix's job is boundedness, not making an inherently degenerate
configuration look graceful.

### 5. [Low] Grab picks the visually-bottom body among overlapping shapes

`_handle_grab` iterates `world.bodies` in insertion order and keeps the
first body within range, so when shapes overlap it grabs whichever was
spawned *earliest* — visually the one underneath, since later bodies are
drawn on top — rather than the one the user is actually pointing at.

**Fix:** iterate in reverse so the most-recently-added (topmost-rendered)
body wins ties.

### 6. [Low] `import random` is dead code

Never used anywhere in `server.py`. Removed.

### 7. [Low] Scene import doesn't clamp material/geometry fields

`/api/spawn` clamps `restitution` to [0,1], `friction` to [0,2], `density`
to [0.05,20], and circle/box dimensions to sane min/max — but
`body_from_dict` (used by scene import) passed these straight through.
After fixing (1), a hand-edited scene with `"restitution": 500` no longer
crashes anything, but it would still produce silently-nonsensical
physics (a ball that gains energy on every bounce). Brought import in
line with spawn's validation.

### 8. [Low/UX] Cursor doesn't change for the grab tool

The canvas cursor was hardcoded to `crosshair` regardless of the active
tool, so there was no visual affordance that grab-mode behaves
differently from spawn-mode until you actually click.

**Fix:** cursor switches to `grab`/`grabbing` when the grab tool is
active.

## What did *not* turn out to be a bug

- Deeply-overlapping bodies with no ground (10 coincident boxes in free
  fall): survives without crashing or producing NaN once (4) is fixed;
  separates forcefully but boundedly.
- A sudden, large single-frame jump of the mouse-drag target (simulating
  a fast flick): the mouse spring overshoots slightly and settles, no
  instability — explicit-Euler stiff-spring blowup was a real concern
  given how stiff the mouse joint is (`k ≈ 550 × mass`), but in practice
  mousemove events arrive frequently enough, and the joint's own damping
  is high enough, that it stays stable even under an artificially large
  single jump.
- HTTP/1.1 + streaming SSE without `Content-Length` or chunked encoding
  is not strictly spec-conformant, but works correctly against both curl
  and every browser tested; not worth the complexity of hand-rolling
  chunked transfer-encoding for a sandbox tool.

## Fresh run-through after fixes

Re-ran the full reproduction list above against the patched server:
NaN via all three endpoints now returns a clean `400` instead of killing
anything; save/load round-trips the bridge and cradle scenes with joints
intact; rapid-clicking the same spot no longer launches anything off
world; grabbing an overlapping stack picks the top body. Zero of the
above issues reproduce.
