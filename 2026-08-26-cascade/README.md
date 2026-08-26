# Cascade

A from-scratch HTML/CSS **layout and rendering engine** — the part of a
web browser that turns markup + stylesheets into an actual picture. Parse
HTML into a DOM, parse CSS and run the real cascade algorithm to get
computed styles, run a real box-model layout algorithm (block/inline
formatting contexts, margin collapsing, line breaking, floats), and paint
the resulting box tree to SVG. Verified not just against hand-written
expected values but *differentially against real headless Chromium* —
7/7 test pages match its actual `getBoundingClientRect()` geometry.

## Why this, today

See [PLAN.md](PLAN.md) for the full rationale. Short version: this
repo has built compilers, VMs, SAT solvers, path tracers, and nine
Transformers from scratch, but never the rendering pipeline behind the
single most-used piece of software architecture on Earth — and this
particular sandbox happens to have a real headless Chromium pre-installed
(`/opt/pw-browsers/chromium`, driven by Node's `playwright` package),
making it possible to verify a from-scratch layout engine against an
actual production browser engine's real numbers instead of only "looks
plausible."

## How to run it

```bash
# CLI: render any HTML file to SVG, or dump its box tree / computed styles
python3 cli.py render testpages/01_box_model.html -o out.svg
python3 cli.py dump-boxes testpages/04_floats.html
python3 cli.py dump-styles testpages/06_cascade_specificity.html

# Interactive playground: edit HTML/CSS live, hover any box to see its
# real margin/border/padding/content edges (server does the real layout;
# the browser client holds zero layout logic)
python3 server.py
# -> open http://127.0.0.1:8420/

# Full verification: unit tests + CLI + Chromium differential oracle +
# server smoke test + adversarial edge cases, one command
./demo.sh

# Just the differential oracle against real Chromium
python3 oracle/run_diff.py testpages

# Just the unit tests
python3 -m unittest discover -s tests
```

No dependencies beyond Python 3's standard library for the engine
itself. The Chromium oracle and playground use Node's globally-installed
`playwright` package and the pre-installed headless Chromium — both
already present in this sandbox.

## Architecture

```
cascade/html_parser.py    tokenizer + tree construction -> DOM
cascade/css_parser.py     CSS tokenizer + parser -> selectors/declarations
cascade/cascade.py        cascade algorithm (specificity, !important,
                           inheritance) + UA default stylesheet -> computed styles
cascade/layout.py         box model, block/inline formatting contexts,
                           margin collapsing, line breaking, floats
cascade/paint.py          box tree -> real SVG (backgrounds, borders, text)
cascade/engine.py         render_html(html, css) -> DOM + styles + boxes + SVG
cascade/fonts.py          hand-calibrated proportional/monospace metrics table

cli.py                    render / dump-boxes / dump-styles subcommands
server.py + playground.html   interactive box-model-inspector playground
oracle/diff.cjs + run_diff.py differential verification against real Chromium
testpages/*.html          fixtures fed to both Cascade and Chromium
tests/                    60 unit tests (unittest, stdlib only)
demo.sh                   one-command end-to-end verification
```

## Full feature list

**Required (all fully working end-to-end):**

1. **HTML parser** — hand-written tokenizer (tag/attribute/comment/
   raw-text states for `<script>`/`<style>`/`<textarea>`/`<title>`) + a
   simplified WHATWG-style tree-construction algorithm: implicit closing
   of unclosed `<p>`/`<li>`/`<td>`/`<tr>`/..., a void-element table,
   entity decoding, and graceful recovery from malformed/mismatched
   markup — never throws. A document with no `<body>` (even bare text)
   gets one synthesized around its actual content, matching real HTML5
   parsing.
2. **CSS parser + cascade** — real selector grammar (type, `.class`,
   `#id`, `*`, descendant, child `>`, `[attr]`/`[attr=val]`/`[attr~=val]`,
   `:first-child`/`:last-child`/`:nth-child(odd|even|an+b)`), CSS
   specificity (a/b/c), the real cascade order (`!important` → origin →
   specificity → source order), inline `style=""` handling, and property
   inheritance, all producing one `ComputedStyle` per DOM node. A UA
   default stylesheet supplies real browser-like defaults (block/inline
   display, heading sizes, link color, list-item, `<pre>` whitespace...).
3. **Layout engine** — real box model (content/padding/border/margin,
   `box-sizing: content-box | border-box`, for both width *and* height);
   a block formatting context with correct sibling-sibling margin
   collapsing (the real mixed-sign formula: max of positives + min of
   negatives); an inline formatting context with CSS whitespace
   collapsing, `white-space: pre`, greedy line breaking against
   proportional/monospace font metrics, `line-height`, and
   `text-align: left/center/right/justify`; `display: block | inline |
   inline-block | none`; `margin: auto` centering.
4. **Paint (SVG renderer)** — walks the final box tree and emits a real
   SVG document: background rects, independently-styled 4-sided borders,
   and text runs positioned per line box at their computed baseline. A
   multi-line `<span style="background:yellow">` gets correct real CSS
   inline-box fragmentation — one rect per line it touches, left edge
   only on its first fragment, right edge only on its last.

**Stretch (all three implemented):**

5. **Float layout** — `float: left/right` with a real "shelf" placement
   algorithm (floats stack side-by-side until they don't fit, then drop
   below the shortest), normal-flow content narrowing around active
   floats per line, and `clear: left/right/both`.
6. **Chromium differential oracle** — `oracle/diff.cjs` (Playwright) +
   `oracle/run_diff.py` render the same test pages in Cascade and in
   real headless Chromium and diff every element's border-box geometry.
   **7/7 test pages, 0 mismatches**, with a tolerance that's tight (a
   4-8px floor) for pure box-model layout and wider only for the
   font-metric noise inherent to not having a real font rasterizer.
7. **Interactive server-backed playground** — `server.py` (stdlib
   `http.server`, no framework) + `playground.html`: edit HTML/CSS,
   render with the real engine server-side, and hover any box in the
   preview for a live Chrome-DevTools-style box-model overlay (margin/
   border/padding/content, exact pixel dimensions) — the browser client
   holds zero layout logic, the same "server does the real work" pattern
   this repo used for Gambit's chess board, Formulate's spreadsheet, and
   Trove's search UI.

## Verification

- `tests/` — 60 unit tests across the HTML parser, CSS parser/cascade,
  layout engine, and paint, including regression tests for every real
  bug found in adversarial review.
- `oracle/run_diff.py testpages` — differential geometry test against
  real headless Chromium. **7/7 pages, 0 mismatches.**
- `demo.sh` — one command exercising every feature end-to-end (unit
  tests, CLI rendering, the Chromium oracle, a direct float-narrowing
  check, both server endpoints, and 6 adversarial edge cases).
- [`REVIEW.md`](REVIEW.md) — the adversarial-review writeup: 8 real bugs
  found and fixed (the most consequential: whitespace-only text between
  block siblings was silently breaking margin collapsing on almost all
  realistically-formatted HTML), plus the deliberate, documented scope
  cuts that are *not* bugs.

## Where a human could take this next

- **Real font metrics.** Swap the hand-calibrated advance-width table for
  actual font parsing (TTF/OTF `hmtx`/`cmap` tables) — this alone would
  tighten the Chromium oracle's tolerance dramatically and make
  wrap-boundary text height match exactly instead of approximately.
- **Parent/first-child margin collapsing** — the one deliberately
  unimplemented piece of the real collapsing algorithm (see REVIEW.md).
- **Flexbox or grid** — a genuinely different layout algorithm on top of
  the same box-model/cascade foundation; the cleanest next "required
  feature"-sized addition.
- **True shrink-to-fit** for `inline-block`/floats with `width: auto`
  (min-content/max-content sizing) instead of the current text-flattening
  approximation.
- **A real rasterizer** instead of SVG output — reuse this repo's own
  PNG-encoder pattern (Prism/Morphica/Optic) to paint real pixels with a
  hand-authored bitmap font, closing the loop on "no external rendering
  dependency at all."
- **CSS transitions/animations** via the playground's live-edit loop —
  the box-model overlay already has all the geometry needed to animate
  between two computed-style states.
