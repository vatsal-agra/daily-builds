# Reflow

A browser rendering engine built from scratch: HTML parser → CSS cascade →
layout → paint → real PNG. See [PLAN.md](PLAN.md) for the full design and
feature list.

**Status: Phase 3 (adversarial review) complete.** All four required
features work end-to-end, and a hostile pass over the code found and fixed
10 real bugs (wrong DOM nesting, a `<tr>`/`<td>` auto-close gap, no default
heading/list styling, non-compounding `em` font sizes, a shorthand-parsing
bug on `rgb(...)` colors, non-functional `<br>`, a missing-margin bug, an
HTML attribute-parsing bug, and a CLI UX bug) — see [REVIEW.md](REVIEW.md)
for the full list, including what was *not* a bug (documented
limitations). Stretch features are still in progress.

## Quick start

```
python3 cli.py render examples/hello.html -o out.png
python3 cli.py render examples/hello.html --dump-dom
python3 cli.py render examples/hello.html --dump-cascade
python3 cli.py render examples/hello.html --dump-layout
```

`examples/hello.html` exercises the box model, borders, backgrounds,
inline word-wrap, and text-align in one page. Render it and open `out.png`
in any image viewer to see the actual output.

## What's implemented so far

- `reflow/html_parser.py` — hand-written tokenizer + tree-construction
  parser (void elements, `<p>`/`<li>`/etc. implicit closing, `<script>`/
  `<style>` raw text, comments, malformed/unclosed tags).
- `reflow/css_parser.py` — CSS tokenizer/parser into a CSSOM (`Rule`s with
  selector groups, combinators, specificity).
- `reflow/cascade.py` — selector matching + cascade (specificity → source
  order → `!important`) + property inheritance → `ComputedStyle` per node.
- `reflow/layout.py` — box model, block flow with sibling margin
  collapsing, and inline flow with real greedy line-breaking.
- `reflow/font.py` — an original hand-authored stroke font rasterized with
  Bresenham's line algorithm (no system/TrueType fonts).
- `reflow/paint.py` + `reflow/png_encoder.py` — paints the layout tree and
  encodes a genuinely valid PNG (correct chunks/CRCs, zlib-deflated rows).
- `cli.py` — render a file to PNG, or dump any pipeline stage.

Still to come: adversarial review (Phase 3), flexbox + the interactive
visualizer (Phase 4 stretch features), a test suite (Phase 5), and final
polish (Phase 6).
