
# Daily Build Ledger

## 2026-06-11 — Atlasforge
- **What:** Procedural fantasy world generator rendering interactive single-file HTML maps (terrain → climate → rivers → biomes → named settlements), deterministic per seed.
- **Stack:** Pure Python 3 stdlib (incl. hand-rolled PNG encoder), inline SVG/JS; jsdom for DOM tests only.
- **Features shipped:** deterministic fractal terrain w/ domain warp; priority-flood hydrology with never-dangling rivers + lakes; wind-advected climate w/ rain shadows; 18 Whittaker biomes; habitability-placed settlements w/ Markov names + founding history; interactive map (4 layers, pan/zoom, inspector, gazetteer fly-to); JSON export; CLI; 31-test suite + demo.sh.
- **Verdict:** Shipped. All 4 required + 3 stretch features done; adversarial review caught a broken default CLI path (fixed) — 31/31 tests green, ~2 s per 160×160 world.

## 2026-06-12 — RegexLab
- **What:** From-scratch regex engine (parser → Thompson NFA → Pike VM with captures → Hopcroft-minimized DFA) with an interactive single-file HTML visualizer that steps the VM over any test string, live threads highlighted in the real automaton.
- **Stack:** Pure Python 3 stdlib; generated HTML embeds a JS mirror of the Pike VM (no deps); Playwright/Chromium for browser tests only.
- **Features shipped:** full parser w/ positioned errors (greedy+lazy quantifiers, classes, anchors, `\b`); `match/fullmatch/search/finditer/findall` w/ groups — differentially fuzzed vs `re`, zero diffs incl. the 3.7 must-advance rule; subset-construction DFA + Hopcroft (Moore-cross-checked, textbook 4-state `(a|b)*abb`); interactive viz (tape, transport, keyboard, NFA+DFA views, capture table); `explain`, verified `gen`, first-class `fuzz` CLI; linear-time — `(a+)+$` ReDoS case in <1 ms.
- **Verdict:** Shipped. 4/4 required + 3/3 stretch; adversarial review found 12 issues (worst: search died at dead spots, `\D` lost negation) — all fixed; 50/50 tests green incl. headless-Chromium JS≡Python parity.

## 2026-06-15 — Tumble
- **What:** From-scratch 2D physics engine (Verlet integration + Position-Based Dynamics) with an interactive single-file Canvas playground — ropes, cloth, soft blobs and rigid boxes built from particles + distance constraints, draggable/cuttable/tearable in real time.
- **Stack:** Pure Python 3 stdlib (engine, CLI, SVG renderer, tests); a JavaScript mirror of the engine for the browser; Node for headless parity tests (no browser dependency).
- **Features shipped:** Verlet/PBD core (inverse-mass-weighted distance constraints, stiffness, pinning, fixed-step determinism); collisions (particle↔particle via uniform-grid broadphase, static segments, bounds w/ restitution+friction); composite bodies (rope/cloth/box/blob); interactive playground (drag-fling/cut/pin/spawn, sliders, stress-coloured links, HUD, trails); tearable cloth; JSON save/load + 8 presets; headless SVG renderer + `check` CLI; in-app SVG snapshot download.
- **Verdict:** Shipped. 4/4 required + 4 stretch; adversarial review fixed a zero-velocity drag + a reset-mid-drag crash; 27/27 tests green incl. free-fall vs analytic Verlet (exact), pendulum length <0.1%, box rigidity ~1e-4 px, and JS≡Python parity (max diff 0.0, bit-identical) across all 8 scenes.
