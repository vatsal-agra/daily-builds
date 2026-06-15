# Tumble — Plan

## Concept
**Tumble** is a from-scratch 2D physics engine built on **Verlet integration +
Position-Based Dynamics (PBD)**, plus an interactive browser playground where you
can spawn ropes, cloth, soft blobs and rigid boxes, then drag, cut, tear and pin
them in real time.

There is **one physics core, written twice**: a reference implementation in pure
Python (used for the CLI, the SVG renderer and the test suite) and a byte-for-byte
mirror in JavaScript (used by the canvas playground). Because both are plain IEEE-754
double arithmetic doing the *same operations in the same order*, the two engines are
cross-checked for **bit-close parity** by running an identical scene N steps in Node
and comparing against Python. (This is the same "source-of-truth twice, verified
equal" trick the earlier RegexLab build used for its VM — but with no browser
required: Node runs the JS core directly.)

## Why it's interesting
- PBD is the algorithm behind real cloth/rope in games (and the basis of XPBD,
  used in modern engines). Implementing it from scratch — integration, constraint
  projection with inverse-mass weighting, collision as constraints, tearing — is a
  genuinely meaty algorithmic core, not a toy.
- It's *deterministic*: fixed timestep + fixed solver iteration order means the same
  scene replays identically, which makes it both testable and shareable (scenes are
  just JSON).
- It looks great and is tactile — dragging a piece of cloth and slicing it with the
  cursor is the kind of thing that's fun to watch a machine build at 3am.
- It's wholly distinct from the prior two daily builds (procedural world-gen; a
  regex engine).

## Architecture
```
tumble/
  vec.py          # tiny 2D vector helpers (pure functions on tuples/floats)
  engine.py       # World, Particle, constraints, collisions, the step() loop
  builders.py     # rope / cloth / box / blob / chain composite builders
  scenes.py       # named preset scenes (deterministic)
  render_svg.py   # headless SVG snapshot of a world (no browser needed)
  cli.py          # `python -m tumble ...` : scenes / sim / render / check
web/
  engine.js       # the JS mirror of engine.py + builders + scenes (UMD: browser+Node)
  index.html      # the interactive canvas playground (single file, no deps)
  node_parity.js  # headless Node harness: run a scene N steps, dump JSON state
tests/
  test_tumble.py  # full Python suite + invokes node_parity for JS≡Python check
demo.sh           # runs CLI commands + renders SVGs + runs the test suite
```

### The step loop (both engines, identical order)
1. **Integrate** each particle with Verlet: `x' = x + (x - x_prev)*(1-damping) + a*dt²`,
   then `x_prev = x_old`. Pinned particles (`inv_mass == 0`) don't move.
2. **Solve** for `iterations` passes, each pass in fixed order:
   a. distance constraints (PBD projection weighted by inverse mass; stiffness),
   b. particle–particle circle collisions (positional, mass-weighted),
   c. static line-segment obstacles,
   d. world bounds (with restitution + tangential friction via prev-position edit).
3. **Tear**: distance constraints whose current length exceeds
   `rest * (1 + tear_strain)` are removed (only if tearing enabled).

## Feature list

### Required (4)
1. **Verlet/PBD core** — particles with inverse mass & radius, gravity, global damping,
   pinning, fixed-timestep deterministic `step()`, distance constraints with stiffness
   and inverse-mass weighting. Gate: pendulum keeps its length; free-fall matches the
   Verlet recurrence analytically.
2. **Collisions & containment** — particle–particle circle collision, world bounds with
   restitution + friction, and static line-segment obstacles. Gate: dropped particles
   come to rest inside the box with no overlap and no tunnelling.
3. **Composite bodies** — rope, cloth (structural+shear+bend constraints), rigid box
   (edges+diagonals at high stiffness), and soft blob (ring+hub spokes), via `builders`.
   Gate: a rigid box keeps its edge lengths within tolerance after dropping; cloth
   pinned at the top hangs and settles.
4. **Interactive playground** — single-file HTML/Canvas app driven by the JS core:
   real-time sim with play/pause/step/reset, gravity & iteration sliders, mouse
   **drag**, **cut** (slice constraints), and **pin** tools, spawn ropes/cloth/boxes/blobs,
   stress-coloured constraints, and a live diagnostics overlay. Gate: loads and runs
   from `file://` with zero dependencies.

### Stretch (2+)
5. **Tearable cloth** — constraints break past a strain threshold; cut tool and gravity
   load both trigger it; UI toggle + threshold slider.
6. **Scene save/load + presets** — every scene serialises to JSON; export/import in the
   UI and via CLI; a library of deterministic preset scenes shared by Python & JS.
7. **Headless SVG renderer + CLI** — render any scene after N steps to a standalone SVG
   (great as a verification artifact and for the README), plus a `check` command that
   runs physics invariants and reports pass/fail.

## Verification strategy
Pure-Python tests for: free-fall recurrence, pendulum length conservation, cloth
settling & pinning, no-overlap resting stacks, rigid-box rigidity, tearing reduces
constraint count, full determinism (state hash stable across runs), 5000-step
no-NaN endurance, bounded energy in a sealed box, and **JS≡Python parity** by
running `node_parity.js` on the same scenes and diffing positions to a tight
tolerance. `demo.sh` ties it together and emits SVG snapshots.
```
```
