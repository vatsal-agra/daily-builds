# Tumble

**A from-scratch 2D physics engine — Verlet integration + Position-Based
Dynamics (PBD) — with an interactive browser playground.**

Ropes, cloth, soft blobs and rigid boxes, all built from nothing but *particles*
and *distance constraints*. Drag bodies around, slice them with the cursor, pin
them, watch cloth tear under load. There is **one physics core written twice** —
a Python reference and a JavaScript mirror — and the two are verified to produce
**bit-for-bit identical** results.

```
2026-06-15-tumble/
├── tumble/            # Python reference engine (stdlib only)
│   ├── engine.py      #   World, Particle, constraints, collisions, step loop
│   ├── builders.py    #   rope / cloth / box / blob composite bodies
│   ├── scenes.py      #   8 deterministic preset scenes
│   ├── render_svg.py  #   headless SVG snapshot renderer
│   └── cli.py         #   python -m tumble  (scenes / sim / render / check)
├── web/
│   ├── engine.js      # JS mirror of the engine + builders + scenes (UMD)
│   ├── index.html     # the interactive Canvas playground (single file, no deps)
│   └── node_parity.js # headless harness for the JS↔Python parity tests
├── tests/test_tumble.py   # 27-test suite
├── demo.sh            # runs the CLI, renders a gallery, runs the suite
└── gallery/           # example SVG snapshots
```

## What it is

Tumble simulates physics the way modern games do cloth and rope: every object is
a cloud of point masses linked by **distance constraints**, integrated with
**Verlet** (position + previous position, velocity implicit) and solved by
iteratively **projecting** constraints back to their rest lengths
(Position-Based Dynamics). Collisions — particle vs particle, particle vs static
line, and the world bounds — are just more constraints applied each iteration.

Because the timestep is fixed and the solver visits everything in a fixed order,
a scene replays **identically** every run, which is what lets the JS playground
and the Python reference be checked for exact equality.

## How to run

**Playground (no install, no server):**

```bash
open web/index.html        # or just double-click it / drag into a browser
```

Tools: **Drag** (pull & fling bodies), **Cut** (slice links), **Pin**, **Spawn**
(rope/cloth/box/blob). Sliders for gravity, wind, solver iterations and tear
strain; toggles for tearing, particle self-collision, constraints and motion
trails. Export/import scenes as JSON and download an SVG snapshot.
Keyboard: `space` play/pause · `s` step · `r` reset · `1–4` select tool.

**CLI (pure Python 3 stdlib):**

```bash
python3 -m tumble scenes                                   # list presets
python3 -m tumble sim   --scene cloth --steps 300 -v       # headless + diagnostics
python3 -m tumble render --scene ballpit --steps 220 --out shot.svg
python3 -m tumble check                                    # physics invariants
```

**Everything at once:**

```bash
bash demo.sh                       # CLI + SVG gallery + parity check + tests
python3 -m unittest discover -s tests    # just the 27-test suite
```

## Features

**Core (required)**
1. **Verlet / PBD engine** — point masses with inverse mass & radius, gravity,
   global damping, pinning, a fixed-timestep deterministic `step()`, and distance
   constraints with per-constraint stiffness and inverse-mass-weighted projection.
2. **Collisions & containment** — particle↔particle circle collisions (via a
   uniform-grid broadphase), static line-segment obstacles, and world bounds with
   restitution + tangential friction.
3. **Composite bodies** — `rope`, `cloth` (structural + shear + bend links),
   rigid `box` (edges + diagonals), and soft `blob` (ring + hub spokes).
4. **Interactive playground** — single-file Canvas app with drag/cut/pin/spawn
   tools, live sliders & toggles, stress-coloured constraints and a diagnostics
   HUD, running entirely from `file://`.

**Stretch (shipped)**
5. **Tearable cloth** — links break past a strain threshold (from gravity load or
   the cut tool); UI toggle + threshold slider.
6. **Scene save/load + 8 presets** — every scene serialises to JSON; export/import
   in the UI and load custom JSON via the CLI.
7. **Headless SVG renderer + `check` command** — render any scene after N steps to
   a standalone SVG; `check` runs invariants across all presets.
8. **In-playground SVG snapshot download** + **motion trails** + velocity-
   preserving (flingable) drag.

**Verification**
- A **27-test** suite covering: free-fall vs the analytic Verlet recurrence
  (exact), pendulum length conservation (<0.1%), rigid-box rigidity (~1e-4 px),
  no-overlap resting, tearing, determinism, 5000-step endurance, bounded energy,
  JSON round-trip, segment obstacles, builders, CLI, SVG — and **JS≡Python
  parity** (max position diff `0.0` across all 8 scenes, builder + step level).

## Gallery

SVG snapshots (rendered headlessly by `python3 -m tumble render`) live in
[`gallery/`](gallery/): `rope`, `cloth`, `curtain`, `ballpit`, `blobs`,
`obstacles`. Constraints are coloured by stress (blue = slack → grey = rest →
red = taut); orange dots are pinned.

## Why this today

The two previous daily builds were a procedural world generator and a regex
engine. I wanted something in a completely different domain that is still deeply
algorithmic, *visual*, and *provably correct*. Position-Based Dynamics fits
perfectly: it's the real algorithm behind game cloth/rope, it's deterministic
enough to unit-test against analytic solutions, and "drag a sheet of cloth and
slice it" is genuinely fun to watch a machine produce overnight. The
"reference-engine-twice, verified bit-equal" trick (Python ↔ JS) also makes the
correctness story airtight without needing a browser in CI.

## Where a human could take this next

- **XPBD** (compliance-based constraints) for stiffness that's independent of
  iteration count and timestep.
- **Continuous collision detection** so fast particles can't tunnel thin
  obstacles, and **true polygon (SAT) contacts** for robust rigid-body stacking.
- **Angular constraints / shape matching** for proper rigid bodies and bendable
  beams.
- **Spatial-hash self-collision for cloth**, plus GPU/WebGL or WASM for tens of
  thousands of particles at 60 fps.
- A **timeline scrubber** (record states, rewind) built on the determinism, and
  shareable scene URLs that encode the JSON.
- Audio or haptics keyed to constraint stress; a level/puzzle mode ("get the
  blob into the cup").
