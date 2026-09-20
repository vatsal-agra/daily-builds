# Folio

A from-scratch HTML/CSS layout & rendering engine — a toy browser engine.
Parses real HTML into a DOM, real CSS into a cascade, runs a real block/
inline box-model layout algorithm (including float layout), and paints the
result to both an independently-decodable PNG and an interactive DOM/
box-model inspector.

**Status: shipped.** All 4 required features and both stretch features
work end to end, backed by 103 unit/integration tests plus an 8-scenario
differential test suite against real headless Chromium (Folio's computed
box geometry matches Chromium's `getBoundingClientRect()` exactly, to
rounding, across box-sizing, percentages, auto-margin centering, sibling
margin collapsing, over-constrained margins, and float placement/clear).
A hostile self-review (Phase 3, extended into Phase 4 while building float
layout) found and fixed 9 real bugs, including 5 critical ones — a
tokenizer infinite loop on malformed tags, a multi-root HTML fragment
silently dropping all but its first element, percentage heights silently
clipping content off the canvas, `margin-left` being computed but never
actually applied to a box's position, and floats never affecting any
sibling's layout, only their own children's. See [REVIEW.md](REVIEW.md)
for the full write-up and [PLAN.md](PLAN.md) for the architecture.

Run `./demo.sh` for a full, real-CLI walkthrough of every feature (test
suite, PNG rendering + independent `file`-utility validation, float
layout, the interactive inspector including a real headless-Chromium
click-through, the Chromium differential oracle, and CLI error handling).

## Why this project

See "Why this is interesting" in [PLAN.md](PLAN.md) — short version: every
prior build in this repo's history has *used* a browser to render its
visualizer, but none has ever built the HTML/CSS engine that does that
rendering. Folio is that engine.

## Feature list

1. **HTML parser → real DOM tree** (required) — tolerant tokenizer + tree
   builder (implied end tags, void elements, raw-text `<script>`/`<style>`,
   entities), never crashes or hangs on malformed input.
2. **CSS parser + cascade → computed style per node** (required) — real
   selectors (type/class/id/universal/descendant/child/adjacent-sibling/
   comma-lists), specificity, `!important`, inheritance, a default
   user-agent stylesheet, inline `style=""`.
3. **Block + inline box-model layout engine** (required) — containing-block
   width resolution, auto-margin centering, sibling margin collapsing,
   `box-sizing`, and real greedy line-breaking text wrap on a fixed-pitch
   grid.
4. **Paint to an independently-decodable PNG** (required) — a hand-rolled
   PNG encoder + from-scratch bitmap font; verified with the system `file`
   utility, not just Folio's own decoder.
5. **Float layout + clearance** (stretch) — `float: left/right` with real
   text reflow in the gap between two floats, `clear: left/right/both`,
   correctly shared across sibling block-formatting-context boxes.
6. **Interactive DOM/box-model inspector** (stretch) — a self-contained
   HTML/Canvas/JS page: click any rendered element to see its DOM path,
   full computed style, and a devtools-style box-model diagram with real
   measured margin/border/padding/content pixel values.

## How to run

```
python3 -m folio.cli render examples/basic.html -o out.png -w 500
python3 -m folio.cli render examples/floats.html -o floats.png -w 500
python3 -m folio.cli inspect examples/basic.html -o inspector.html -w 500
python3 -m folio.cli info examples/basic.html
```

- `render` runs the full pipeline (HTML → DOM → cascade → layout → paint)
  and writes a real PNG, viewable in any image viewer.
- `inspect` writes a self-contained interactive HTML page — open it in any
  browser and click on the rendered page to explore the DOM/box model that
  produced it.
- `info` prints DOM/CSS/layout stats without writing a file.

Try `examples/basic.html` for the core box model + inline styling, and
`examples/floats.html` for float layout with real text reflow.

## Testing

```
python3 -m unittest discover -s tests   # 103 tests: parser, cascade, layout, paint, PNG, integration
python3 -m unittest tests.test_oracle   # 8 scenarios checked against real headless Chromium
./demo.sh                                # everything above, plus the CLI + a real-browser click-through
```

`test_oracle.py` needs the `playwright` Python package (`pip install
playwright`); this environment's Chromium is already pre-installed at
`/opt/pw-browsers/chromium`, so no browser download is needed. Every other
test file is pure stdlib. `demo.sh` detects whether `playwright` is
importable and skips the Chromium-dependent checks (with a clear `[SKIP]`
line) rather than failing if it isn't.

## Honest scope boundaries

See PLAN.md for the full list; the headline one is that text is measured
and painted on a fixed-pitch (monospace) grid rather than with real
proportional font metrics — deliberate, so every layout number is exact,
checkable arithmetic instead of a guess. No JavaScript execution, no
network loading of images/stylesheets, and CSS selector support stops at
type/class/id/combinators (no `:nth-child()`, no attribute selectors).
Margin collapsing implements the sibling case only, not the parent-child
case (also in PLAN.md).

## Where a human could take this next

- **Real proportional text.** Swap the fixed-pitch model for actual glyph
  metrics (even a simple per-character width table for one real font)
  and the Chromium oracle in `test_oracle.py` could be extended to assert
  on text-driven geometry too, not just explicit-dimension boxes.
- **Inline box model.** `<span>`/`<a>` currently carry no padding/border/
  margin of their own (style-only). Giving inline elements real boxes
  (including line-box height growing to fit a tall inline border) is the
  next standard CSS visual-formatting-model chapter after this one.
- **`display: table`/flexbox.** The layout tree already cleanly separates
  "box generation" from "box positioning" (`layout.py`'s `TreeBuildState`
  vs. `layout_block`/`layout_inline_children`), so a new formatting context
  is a new sibling function, not a rewrite.
- **Side-by-side float packing.** Floats on the same side currently stack
  strictly vertically (PLAN.md's stated scope); real multi-column float
  packing (several floats sharing a row) is a natural follow-up to
  `FloatContext`.
- **A live edit-and-reload loop.** `folio.cli`'s `render`/`inspect` are a
  batch pipeline; wiring a `watch` subcommand (or the existing inspector's
  page) up to a file watcher would make Folio interactively usable as a
  little CSS playground, not just a one-shot renderer.
- **Serve it live.** Several other builds in this repo (Gambit, Formulate,
  Torque) drive their interactive visualizer from a real running Python
  server instead of a static export; Folio's inspector could do the same,
  streaming a fresh render on every keystroke in a textarea.
