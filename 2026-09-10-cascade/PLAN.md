# Cascade — a browser layout engine, from scratch

## Concept

Every prior build in this repo's history that touches "rendering" has rendered
either 3D geometry (Prism, Lumina/Lumen/Pathtracer, Silicon's pipeline
visualizer) or a bespoke 2D scene (Tumble, Flux, Waveforge). None of them has
ever taken **HTML and CSS** — the actual document format the entire web is
built on — and turned it into a laid-out page the way a real browser's engine
does. That's the gap Cascade fills: an HTML tokenizer and DOM tree builder, a
CSS tokenizer/parser with real selector matching and specificity, the CSS
cascade (source order, specificity, `!important`, inheritance) resolving a
computed style per node, and a layout engine that implements the actual
algorithms browsers use — the box model, block and inline formatting
contexts, margin collapsing, and a flexbox subset — to turn a DOM + computed
styles into a tree of positioned, sized boxes. Those boxes are then painted
to real pixels with a hand-rolled rasterizer (backgrounds, borders, a
bitmap-font text renderer) producing a genuine PNG file, with no browser
involved in producing that image at all.

## Why it's interesting

1. **A genuinely new domain for this repo.** Scanning `LEDGER.md`: SAT
   solvers (6), GPT-style transformers (6+), path tracers (3), chess engines
   (2), search engines (3), compression codecs (3), version control (3),
   crypto suites (2) — this repo has gone deep on classical CS algorithms and
   graphics/ML, but never on the parsing-and-layout pipeline that defines how
   every web page you've ever looked at actually got onto your screen.
2. **A rare, extremely strong ground-truth oracle is sitting right in this
   environment.** Playwright + a real Chromium build are pre-installed. For
   any test page built from explicit pixel dimensions (no font-metric
   dependence), Chromium's own `getBoundingClientRect()` for every element is
   an independently-produced, industrially-correct answer key. Nothing else
   in this repo's history gets to differentially test against the actual
   reference implementation of the thing it's rebuilding, in the same
   sandbox, for free. That upgrades "layout looks right" into "layout is
   measured, in pixels, against real Chromium and found identical."
3. **It's a real engineering problem with real subtlety**, not a toy: margin
   collapsing, the CSS cascade's specificity tie-breaking, inline line-box
   wrapping, and flexbox's grow/shrink distribution algorithm are all
   genuinely tricky to get right, with well-known edge cases to get wrong.

## Architecture

```
example.html + style.css
        |
        v
  html_tokenizer.py  --tokens-->  html_parser.py  --DOM tree-->  dom.py (Node)
        |                                                            |
  css_tokenizer.py  --tokens-->  css_parser.py --CSSOM (rules)--     |
                                          |                          |
                                          v                          v
                                      cascade.py  (match selectors, compute
                                                    specificity, cascade +
                                                    inherit)  --> computed
                                                    style per DOM node
                                                            |
                                                            v
                                                      layout.py
                                          (box model, BFC, IFC + line
                                           wrapping, margin collapsing,
                                           flexbox)  --> box tree with
                                                          x/y/w/h per node
                                                            |
                                              +-------------+-------------+
                                              v                           v
                                         paint.py                  viz.py
                                    (from-scratch PNG            (self-contained
                                     rasterizer: bg/border/       interactive HTML
                                     bitmap-font text)            box-inspector page
                                              |                   driven by the real
                                              v                   computed layout,
                                         out.png                  zero client logic)
```

`cli.py` wires all of this into a `cascade` command. `tests/test_diff_oracle.py`
drives real headless Chromium via Playwright, renders the same fixed-dimension
test pages, and asserts our layout engine's box geometry is pixel-identical
to the browser's own `getBoundingClientRect()` output.

## Feature list

**Required (core, must fully work end-to-end):**

1. **HTML parser** — tokenizer (tags/attributes/text/comments, entity
   decoding for the common named + numeric entities) and a tree-construction
   pass implementing the practical parts of the real algorithm: implicit
   `<html>/<head>/<body>`, void elements, auto-closing of `<p>`/`<li>`/table
   cells per the real HTML5 rules, mismatched/unclosed tag recovery — into a
   real DOM tree (`Node`, `Element`, `Text`, parent/children/siblings).
2. **CSS parser + cascade** — a CSS tokenizer and a parser producing real
   rules (selector list, declaration block), selectors covering type/class/
   id/universal/attribute/descendant/child/adjacent-sibling/pseudo-class
   (`:first-child`, `:last-child`, `:nth-child`), specificity computed by the
   real (a,b,c) counting rule, source-order tie-breaking, `!important`, and
   property inheritance (e.g. `color`/`font-*` inherit, `margin`/`border`
   don't) resolving one computed style per DOM node against a built-in
   user-agent stylesheet plus the author stylesheet.
3. **Layout engine** — the CSS box model (content/padding/border/margin),
   block formatting context (vertical stacking, width resolution against the
   containing block, adjoining-margin collapsing per spec), and inline
   formatting context (text run splitting + line-box wrapping to the
   available width, `<br>` handling) producing an exact x/y/width/height box
   tree.
4. **Renderer** — a from-scratch PNG encoder (zlib deflate + PNG chunk
   framing, no PIL) rasterizing the box tree to real pixels: solid
   background-color fills, all four border edges (with distinct widths per
   side), and text rendered through a hand-rolled bitmap font (no system font
   library) — a real `.png` file a real image viewer opens, produced with
   zero use of a browser or any imaging library.

**Stretch (all 3 shipped):**

5. **Flexbox subset** — `display:flex`, `flex-direction` (row/column),
   `justify-content` (flex-start/center/flex-end/space-between/space-around),
   `align-items` (stretch/flex-start/center/flex-end), and `flex-grow`/
   `flex-shrink`/`flex-basis` free-space distribution per the real algorithm.
   ✅ Shipped in Phase 2, 10 unit tests + 6 Chromium-diffed cases.
6. **Chromium differential oracle** — a Playwright-driven test suite that
   renders a battery of fixed-dimension HTML/CSS pages in real headless
   Chromium, reads every element's true `getBoundingClientRect()`, and
   asserts our layout engine computes pixel-identical boxes — turning "no
   crashes" into "provably correct against the real reference
   implementation" for the pages that don't depend on font metrics.
   ✅ Shipped in Phase 4 (`tools/oracle/measure.js` +
   `tests/test_diff_oracle.py`) — **12/12 pixel-identical to real Chromium**
   across box model, margin collapsing, percentages, and flexbox.
7. An interactive self-contained HTML "DevTools-lite" box
   inspector: click any box to see its full computed style and box-model
   breakdown, generated from one real Cascade layout run with zero
   client-side layout logic (same server/precompute-then-render pattern this
   repo has used since Gambit/Formulate). ✅ Shipped in Phase 4
   (`src/viz.py`, `cascade viz`), headless-Chromium-verified zero console
   errors + working click-to-inspect (`tests/test_viz_ui.py`).

## Verification strategy

- Unit tests for every stage in isolation (tokenizer edge cases, selector
  matching + specificity ordering, box-model arithmetic, margin collapsing,
  line wrapping, flexbox distribution) against hand-computed expected values.
- The Chromium differential oracle (stretch #6) as the strongest possible
  check for anything with fixed pixel dimensions.
- A rendered PNG gallery of several real-looking pages (nav bar, card grid,
  form) as a visual sanity check, committed to the repo.
