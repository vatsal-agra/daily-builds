# Tumble — Adversarial Review (Phase 3)

I attacked my own build as a hostile reviewer: looked for crashes, NaN/instability,
physics that silently lies, and bad UX. Findings below, each with disposition.
Re-run after fixes: every listed bug is gone.

## Bugs found & fixed

### B1 — Drag couldn't fling, and could crash on reset mid-drag  *(FIXED)*
The drag tool pinned a particle (`inv_mass = 0`) and each frame snapped its
position **and** previous position to the cursor, so release velocity was always
zero — you couldn't throw anything, which feels dead. Worse, `endDrag` indexed
`world.particles[dragIdx]` without checking the array still had that index, so
hitting **Reset** while a drag was in progress could throw and kill the render
loop.
*Fix:* `applyDrag` now moves *prev → last position* and *pos → cursor*, so the
implicit Verlet velocity tracks the cursor and you can fling bodies. `endDrag`
and `applyDrag` bounds-check `dragIdx` against the live particle array.

### B2 — `scene_rope` built a throwaway rope then cleared it  *(FIXED)*
A leftover placeholder call created one rope, then `particles.clear()` /
`constraints.clear()` wiped it before building the real one — dead code that
would confuse anyone reading the scene and risked drift from the JS mirror.
*Fix:* removed; the scene now builds the rope once. (Also hoisted a per-iteration
`import Particle` out of `scene_ballpit`.)

### B3 — Imported / hand-edited scene JSON could crash the loop  *(FIXED in Phase 4)*
`World.fromDict` trusted constraint endpoint indices; an out-of-range `i`/`j`
from pasted JSON would throw on the next `step()`, outside the import try/catch,
killing the animation. Hardened in the polish phase with a validator that
rejects malformed scenes with a toast instead of dying.

## Verified correct (attempted to break, couldn't)

- **Free-fall** matches the analytic Verlet recurrence `xₙ₊₁ = 2xₙ − xₙ₋₁ + a·dt²`
  to **0.0** over 50 steps.
- **Pendulum** (stiff link, 30 iterations) holds its rest length to **0.000%**
  over 1000 steps.
- **Rigid box** keeps every edge length to **1e-4 px** after dropping and resting,
  and lands exactly on the floor (`center = height − radius`).
- **No-overlap resting**: two big circles dropped together settle with **0**
  penetration.
- **Determinism**: the same scene run twice produces a **bit-identical** state
  hash; **JS ≡ Python** parity is **0.0** max position diff across all 8 scenes,
  including the grid broadphase and the BigInt-LCG ball-pit.
- **Endurance**: 5000 steps of a busy scene — all values finite.
- **Stability**: a sealed box with `damping = 0`, perfect restitution — kinetic
  energy peaks at **1.00×** its start and never explodes.
- **JSON round-trip** reproduces an identical state hash.
- `tumble check` reports all 8 presets finite with nothing escaping bounds.

## Known limitations (by design, documented — not bugs)

- **No continuous collision detection.** A very fast particle can tunnel through a
  *thin* static segment within one step. Mitigated by giving segments real
  thickness (`radius`) and by the modest per-step velocities the default forces
  produce. Walls (world bounds) are clamped every solver iteration and never
  tunnel.
- **Energy is not conserved in particle–particle collisions.** PBD resolves
  overlaps positionally, which is inherently inelastic (no restitution between
  particles; restitution applies only at world bounds). This is standard for PBD
  and is the *safe* failure mode — energy decays, never blows up.
- **Rigid bodies are constraint networks, not true polygons.** Boxes/blobs hold
  their shape via stiff edges + diagonals and rest correctly on the floor, but
  robust box-on-box *stacking* would need SAT polygon contacts, which is out of
  scope. Reflected honestly in the `boxes` scene (bodies land and settle rather
  than stacking into towers).
- **Cloth bend links don't tear** (only structural + shear do), so a fully shredded
  cloth can leave a few long fold-resistance links across a rip. Kept on purpose:
  they stop the cloth folding through itself, and the visible tearing reads fine.
