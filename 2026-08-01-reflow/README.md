# Reflow

A browser rendering engine built entirely from scratch, in pure Python: a
real HTML5-style parser, a real CSS cascade, a real layout engine (block
flow, inline flow with line-breaking, and flexbox), and a real painter
that produces a genuinely valid PNG — no `html.parser` tree-building
shortcuts, no `tinycss`/`cssutils`, no Pillow, no headless browser, no
system/TrueType fonts. Give it an HTML file (optionally with CSS) and it
hands back the actual rendered pixels.

**Status: shipped.** All four required features and both stretch
features work end-to-end, backed by a 107-test suite and a runnable
`demo.sh` that exercises every feature against real output on disk. See
[PLAN.md](PLAN.md) for the original design and [REVIEW.md](REVIEW.md) for
the adversarial review (11 real bugs found and fixed, including a few
non-obvious ones, plus what was deliberately left as a documented
limitation rather than "fixed").

## How to run it

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

No dependencies beyond the Python 3 standard library (`zlib`/`struct` for
the PNG encoder, `http.server` for the visualizer, `html.unescape` for
entity decoding — everything else, including the font, is hand-rolled).

`examples/hello.html` exercises the box model, borders, backgrounds,
inline word-wrap, and text-align. `examples/flex.html` exercises a
toolbar (row, `justify-content: space-between`, `flex-grow`), a sidebar
layout (row, fixed + growing columns), and a card stack (column
direction). Render either and open the PNG in any image viewer, or paste
their contents into the visualizer to watch every pipeline stage at once.

## Full feature list

**Required (all four fully working, no stubs):**

1. **HTML5-style tokenizer + tree-construction parser** — a real character
   state walk (not a regex strip), handling void elements, implicit
   end-tag closing (`<p>`, `<li>`, `<dd>`/`<dt>`, `<tr>`/`<td>`/`<th>`,
   `<option>`), mismatched/unclosed tags, comments, and `<script>`/
   `<style>` raw text that survives HTML-looking substrings inside it.
2. **CSS parser + cascade** — real selector grammar (type/`.class`/`#id`,
   descendant/child combinators, comma groups), specificity → source
   order → `!important` conflict resolution, property inheritance, and a
   small user-agent stylesheet fed through the same cascade as author CSS.
3. **Layout engine** — the CSS box model (content/padding/border/margin),
   block flow with sibling margin collapsing, and inline flow with real
   greedy line-breaking against actual glyph widths (`<br>`-aware).
4. **Painter + real PNG output** — backgrounds, borders, and glyph text
   rasterized into an RGB buffer, encoded as a byte-correct PNG (proper
   IHDR/IDAT/IEND chunks, CRC-32, zlib-deflated scanlines) — verified in
   the test suite by decoding it back with an independent decoder.

**Stretch (both implemented):**

5. **Flexbox** — row/column direction, `justify-content` (start/center/
   end/space-between/space-around), `align-items` (start/center/end/
   stretch), `gap`, and `flex-grow`.
6. **Interactive visualizer** — a stdlib-`http.server` backend (zero
   client-side layout logic) plus a dark-themed single-page UI: paste
   HTML/CSS and see the DOM tree, the CSSOM with a per-element cascade
   explanation (which rule won and why), an SVG diagram of the real
   layout box tree with actual pixel coordinates, and the final PNG, all
   computed live by this engine for the exact same input.

**Also shipped, beyond the original plan:**

- An original hand-authored stroke font (Bresenham-rasterized, not a
  system/TrueType font) covering the full printable-ASCII range.
- `<img alt="...">` fallback-text rendering.
- A CLI with clean error messages for bad paths/arguments (not raw
  tracebacks).

## Why this today

Every earlier entry in this repo's history that says "from scratch X" has
picked X from compilers, databases, ML/transformers, physics engines,
graphics/3D rendering, crypto, or search — see `LEDGER.md`. None had
touched the specific pipeline that turns markup into a web page, even
though it's exactly the repo's house style: a real, spec-shaped algorithm
(the HTML5 tree-construction algorithm and the CSS cascade are genuinely
subtle — implicit tag closing, specificity tie-breaking, inheritance,
line-breaking) with rich internal state that's satisfying to visualize,
composed into one complete product rather than a single algorithm demo.
It also turned out to be a great stress test for exactly the kind of bug
that "looks right in a screenshot" hides — the flexbox text-position bug
in REVIEW.md only showed up once the rendered PNG was inspected at a
legible scale, not from checking a few background pixel values.

## Known limitations (by design, not oversights — see PLAN.md and REVIEW.md)

- No JavaScript, no network resource loading (`<img src>`/`<link>` are
  read as local text only), no real TrueType/OpenType fonts, no
  `box-sizing: border-box`, no CSS grid/animations/media queries.
- `line-height` is cascaded and inherited but not yet consumed by the
  inline layout (line spacing is a fixed font metric).
- `font-weight`/`font-style` are tracked through the cascade but the
  stroke font has only one weight/style, so bold/italic don't currently
  change how glyphs render.
- Flex-basis for `width: auto` row-direction items with no `flex-grow`
  uses an approximate text-measurement, not a true min/max-content pass.

## Where a human could take this next

- **Real fonts**: parse actual TrueType/OpenType glyph outlines instead
  of the hand-authored stroke font — the rasterizer interface
  (`render_glyph(ch, scale) -> pixel offsets`) is already isolated enough
  that swapping the backend wouldn't touch layout or paint at all.
- **Incremental layout**: right now every render recomputes the whole
  tree from scratch, which is fine for a static-page renderer but is the
  first thing a real browser optimizes away — dirty-flagging changed
  subtrees (the way `Formulate`, an earlier daily build, did dependency
  graph invalidation for its spreadsheet engine) would be a natural
  follow-up.
- **CSS Grid**: the flexbox implementation in `layout.py` already
  establishes the pattern (a container dispatch in
  `_layout_block_container`, a dedicated child-layout function) that a
  grid implementation would slot into directly.
- **A real min/max-content sizing pass**: would replace the
  text-measurement approximation used for flex-basis today and make
  block-level intrinsic sizing (`width: fit-content`) possible too.
- **`<table>` layout**: the parser already gets table tag auto-closing
  right (see REVIEW.md); actual table layout (columns, row/cell sizing)
  was out of scope but the DOM structure is already correct to build on.
- Wire the visualizer's cascade explanation up to also show *why* a
  losing declaration lost (not just which one won) — the data
  (`ComputedStyle.matches_debug`) is already collected, just not fully
  surfaced yet.
