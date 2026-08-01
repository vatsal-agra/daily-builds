# Reflow

A browser rendering engine built from scratch: HTML parser → CSS cascade →
layout → paint → real PNG. See [PLAN.md](PLAN.md) for the full design and
feature list, and [REVIEW.md](REVIEW.md) for the adversarial review (11
real bugs found and fixed, plus what was deliberately left as a documented
limitation).

**Status: Phase 5 (verification) complete.** All four required features
and both stretch features work end-to-end, backed by a 107-test suite
and a runnable `demo.sh` that exercises every one of the six features
against real output on disk.

## Quick start

```
./demo.sh                    # tests + every feature, output in demo_output/

# render a file to PNG, or dump any pipeline stage
python3 cli.py render examples/hello.html -o out.png
python3 cli.py render examples/flex.html -o flex.png
python3 cli.py render examples/hello.html --dump-dom
python3 cli.py render examples/hello.html --dump-cascade
python3 cli.py render examples/hello.html --dump-layout

# interactive visualizer: paste HTML/CSS, see DOM / CSSOM+cascade /
# layout boxes (SVG) / final PNG update live, all computed by this engine
python3 server.py --port 8000
# then open http://127.0.0.1:8000/

# run just the test suite
python3 -m unittest discover -s tests
```

`examples/hello.html` exercises the box model, borders, backgrounds,
inline word-wrap, and text-align. `examples/flex.html` exercises a
toolbar (row, `justify-content: space-between`, `flex-grow`), a
sidebar layout (row, fixed + growing columns), and a card stack (column
direction). Render either and open the PNG in any image viewer.

## What's implemented

- `reflow/html_parser.py` — hand-written tokenizer + tree-construction
  parser (void elements, `<p>`/`<li>`/`<tr>`/`<td>`/etc. implicit
  closing, `<script>`/`<style>` raw text, comments, malformed/unclosed
  tags).
- `reflow/css_parser.py` — CSS tokenizer/parser into a CSSOM (`Rule`s with
  selector groups, combinators, specificity).
- `reflow/cascade.py` — selector matching + cascade (specificity → source
  order → `!important`) + property inheritance → `ComputedStyle` per
  node, plus a small UA stylesheet (heading sizes, bold/italic tags,
  link color, list margins/indent) fed through the same cascade as
  author CSS.
- `reflow/layout.py` — box model, block flow with sibling margin
  collapsing, inline flow with real greedy line-breaking (`<br>`-aware),
  and flexbox (row/column, `justify-content`, `align-items`, `gap`,
  `flex-grow`).
- `reflow/font.py` — an original hand-authored stroke font rasterized with
  Bresenham's line algorithm (no system/TrueType fonts).
- `reflow/paint.py` + `reflow/png_encoder.py` — paints the layout tree and
  encodes a genuinely valid PNG (correct chunks/CRCs, zlib-deflated rows).
- `reflow/visualize.py` + `server.py` + `viewer.html` — the interactive
  visualizer: a stdlib-`http.server` backend with zero client-side layout
  logic, and a dark-themed single-page UI showing the DOM tree, the
  CSSOM with per-element cascade explanations, an SVG diagram of the real
  layout box tree (actual pixel coordinates), and the final PNG, all
  computed live from whatever HTML/CSS you paste in.
- `cli.py` — render a file to PNG, or dump any pipeline stage; clear
  error messages (not a raw traceback) for bad paths/arguments.
- `tests/` — 107 unit/integration tests across every module (tokenizer
  edge cases, cascade tie-breaks, box-model math, flexbox, PNG byte
  round-tripping through an independent decoder, CLI subprocess behavior,
  and robustness against malformed/degenerate input) plus `demo.sh`,
  which runs the suite and then exercises all six features against real
  files and a live server, exiting non-zero on any failure.

Still to come: final ship-ready polish pass (Phase 6).
