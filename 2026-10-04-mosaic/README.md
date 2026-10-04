# Mosaic

Wave Function Collapse engine in Rust (zero dependencies) with trail-based backtracking.
**Status: Phase 2 — core build done** (plan: PLAN.md).

```
cargo build --release
target/release/mosaic list
target/release/mosaic overlap --sample dungeon --out dungeon.png
target/release/mosaic overlap --sample city --ground --size 64x24 --out city.png
target/release/mosaic tiled --set terrain --size 30x20 --out terrain.png
target/release/mosaic bench overlap --sample wires --n 4 --wrap-in --wrap-out --size 50x50
```

## Built so far (required features)
1. Generic WFC solver core (min-entropy, support counts, weighted collapse, periodic grids)
2. Overlapping model (NxN extraction, symmetries, wrap-in, ground anchoring)
3. Tiled model (edge sockets, auto rotation; `circuit` and 81-tile `terrain` sets)
4. Backtracking with trail + decision stack, restart budget and stats

## Phase 3 — adversarial review
11 findings fixed (see REVIEW.md): 28 MB flipbooks -> real deflate, pin glyph bug, scale OOM, empty animation,
self-overlapping periodic outputs, wrong error advice, no resource limits, backtracking thrash -> hybrid budget,
PNG sample loading added.

## Phase 4 — stretch + polish
Stretch shipped: pinned cells (`--pin`), collapse-animation flipbook (`--anim`, sampled evenly over the real event count),
benchmark mode (`bench`). Polish: precise errors with exit code 2, resource limits, dark flipbook viewer with scrubber.

## Phase 5 — verification
`./demo.sh` builds, runs 40 tests (unit + integration + CLI) and exercises every feature, failing on any validator
violation. All green; mutation checks (broken undo, broken socket rotation) were caught by the suite.
