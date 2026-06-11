# Atlasforge — Procedural Fantasy World Generator

**Date:** 2026-06-11
**Stack:** Pure Python 3.11 (stdlib only), output is a single self-contained HTML file.

## Concept

A command-line world generator that simulates a fantasy continent from first
principles — plate-like elevation, prevailing winds, rainfall, rivers that
actually flow downhill into the sea, climate-driven biomes, and settlements
with procedurally generated names — and renders the result as a polished,
interactive, single-file HTML map you can open in any browser.

## Why it's interesting

Most "random map" toys paint noise and call it terrain. Atlasforge runs a
small physical simulation pipeline where each layer is *derived* from the
previous one: temperature falls with latitude and altitude, moisture is
carried by wind and rained out against mountains (orographic rain shadow),
rivers trace steepest-descent paths and carve through depressions via lake
filling, biomes follow a Whittaker-style climate classification, and towns
appear where habitability is genuinely high (fresh water + flat land +
temperate climate). Everything is deterministic per seed, so worlds are
shareable as a single integer. The whole thing is stdlib-only — including the
noise functions, the priority-flood hydrology, and the SVG renderer.

## Architecture

```
atlasforge/
  __init__.py
  noise.py        # seeded fractal value noise (no deps)
  terrain.py      # elevation: continent mask + fBm + sea level
  climate.py      # temperature (latitude+altitude), wind-advected moisture
  hydrology.py    # priority-flood depression filling, flow routing, rivers, lakes
  biomes.py       # Whittaker-style biome classification
  settlements.py  # habitability scoring, town placement, Markov name generator
  worldgen.py     # pipeline orchestrator -> World dataclass
  render.py       # SVG layers + interactive single-file HTML viewer
  cli.py          # argparse CLI (seed, size, sea level, output, JSON export)
tests/
  test_atlasforge.py
demo.sh
```

Pipeline: `seed -> elevation -> temperature -> moisture -> hydrology ->
biomes -> settlements -> render`.

Grid: square heightmap (default 160×160), rendered as SVG cells with
hillshading, vector coastline, river polylines and settlement markers.

## Features

### Required (4)

1. **Deterministic terrain generation** — seeded fractal value noise with a
   radial continent mask and configurable sea level; same seed ⇒ identical
   world, different seeds ⇒ different worlds.
2. **Physical hydrology** — priority-flood depression filling so every land
   cell drains; flow accumulation; rivers traced from high-accumulation
   sources that provably reach the sea or a lake; lakes where depressions
   were filled.
3. **Climate & biome simulation** — latitude/altitude temperature field,
   wind-advected moisture with orographic rain shadow, and a Whittaker-style
   classifier producing 12+ biomes (tundra, taiga, steppe, desert, savanna,
   temperate forest, rainforest, alpine, glacier, marsh…).
4. **Interactive single-file HTML map** — embedded SVG with hillshaded biome
   colors, coastlines, rivers, lakes; pan/zoom; hover tooltip showing each
   cell's elevation, temperature, rainfall and biome; layer switcher
   (biome / elevation / temperature / moisture views). No external assets,
   works offline.

### Stretch (3)

5. **Settlements & naming** — habitability-scored placement of capitals,
   towns and villages; Markov-chain name generator trained on a built-in
   corpus, with collision avoidance; names drawn on the map and listed in a
   gazetteer side panel.
6. **World JSON export** — `--json` dumps the full world (grids, rivers,
   lakes, settlements) as machine-readable JSON for downstream use.
7. **History epochs (flavor)** — generate a short founding-era timeline for
   the named settlements (founded year, notable event) shown in the
   gazetteer.

## Definition of done

- `python3 -m atlasforge.cli --seed 42 -o world.html` produces an
  interactive map in < 30 s.
- Test suite covers: determinism, drainage (every river ends at sea/lake),
  biome coverage, settlement constraints (on land, near water), name
  generator sanity, CLI behavior on bad input.
- Adversarial review written and all findings fixed.
