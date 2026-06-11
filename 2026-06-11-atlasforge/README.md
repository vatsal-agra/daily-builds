# ⬢ Atlasforge

A procedural fantasy world generator in **pure Python (zero dependencies)**
that simulates a continent from first principles and renders it as a
**single self-contained interactive HTML map** — open it in any browser,
fully offline.

Every world is derived, not painted: temperature follows latitude and
altitude, moisture is carried by prevailing winds and rained out against
mountains (real rain shadows), rivers trace steepest descent through
priority-flood-filled terrain so they *provably* reach the sea, biomes
follow a Whittaker-style climate classification, and settlements appear
where fresh water, flat ground and temperate climate genuinely coincide.
Same seed ⇒ identical world, so a whole world is shareable as one integer.

## Run it

```bash
cd 2026-06-11-atlasforge
python3 -m atlasforge.cli --seed 42 -o world.html
# then open world.html in a browser
```

No installs, no dependencies — Python 3.10+ is all you need.

More options:

```bash
python3 -m atlasforge.cli --help
python3 -m atlasforge.cli --seed 1337 --land 0.22 -o archipelago.html   # island chains
python3 -m atlasforge.cli --width 240 --height 120 --land 0.55 \
        --title "The Sundered Reach" -o continent.html                  # wide continent
python3 -m atlasforge.cli --seed 42 --json world.json -o world.html     # machine-readable export
bash demo.sh     # runs the test suite, then generates three showcase worlds
```

Tests: `python3 -m unittest discover -s tests` (31 tests). The optional DOM
smoke test additionally needs node + jsdom:
`JSDOM_PATH=/path/to/node_modules python3 -m unittest discover -s tests`.

## Features

**Simulation**
1. **Deterministic terrain** — seeded fractal value noise with domain
   warping and a ridged-mountain component, shaped into a continent;
   configurable land fraction; same seed ⇒ byte-identical world.
2. **Physical hydrology** — priority-flood depression filling (Barnes
   et al.) guarantees every land cell drains; flow accumulation drives
   river extraction; rivers widen downstream and never dangle (verified
   across seeds in tests); filled depressions become lakes.
3. **Climate** — latitude/altitude temperature, wind-advected moisture
   with orographic rain shadows (tropical easterlies, temperate
   westerlies), rank-normalized so the full biome spectrum is reachable.
4. **18 biomes** — Whittaker-style classification: glacier, alpine,
   tundra, taiga, steppes, forests, rainforests, savanna, desert, marsh,
   beach, lake, shallows, ocean…
5. **Settlements & history** — habitability-scored placement (water
   access × flatness × climate) of capitals/towns/villages with spacing
   rules; order-2 Markov name generator with quality filters; founding
   years and historical notes in an in-map gazetteer.

**Output**
6. **Interactive single-file HTML map** — hillshaded biome raster plus
   elevation/temperature/rainfall layers (keys 1–4), pan/zoom,
   per-cell inspector (biome, altitude, °C, rainfall), vector
   coastlines and rivers, zoom-revealed village labels, click-to-fly
   gazetteer, legend, compass. ~370 KB, no external assets.
7. **JSON export** (`--json`) — full grids, rivers, lakes, settlements
   and stats for downstream tooling.

## Why this today

It's the first Daily Build, so I wanted something self-contained,
deterministic, and visually rewarding that needs *zero* dependencies —
including writing the PNG encoder from scratch (stdlib `zlib` + `struct`).
The interesting core is that each layer is physically derived from the
previous one, so the maps come out looking *plausible* — deserts sit
behind mountain ranges, rivers merge into drainage basins, towns hug the
water — rather than like colored noise.

## Where a human could take this next

- **Plate tectonics** — replace the radial continent mask with colliding
  plates for mountain arcs and island chains.
- **Roads & political borders** — A* between settlements weighted by
  slope/river crossings; Voronoi-ish regions claimed by capitals.
- **Erosion** — hydraulic/thermal erosion passes for valley carving.
- **Wraparound worlds** — cylindrical topology and a globe projection.
- **Web UI** — wrap the generator in a tiny HTTP server with a "reroll"
  button, or compile the pipeline to WASM and generate client-side.
- **Campaign export** — Foundry VTT / Azgaar-compatible export of the
  JSON world data.

## Build log

- Phase 1 — Plan ([PLAN.md](PLAN.md))
- Phase 2 — Core build (terrain, climate, hydrology, biomes, HTML map)
- Phase 3 — Adversarial review: 7 findings fixed, 2 accepted with
  rationale ([REVIEW.md](REVIEW.md)) — including a broken default CLI
  path the happy-path testing had hidden
- Phase 4 — Stretch + polish (settlements/names/history, realm titles,
  keyboard shortcuts, compass, hardened inputs)
- Phase 5 — Verification: 31 tests (simulation invariants, CLI behavior,
  PNG roundtrip, jsdom DOM smoke test) + `demo.sh`
- Phase 6 — Ship
