# Folio — a from-scratch HTML/CSS layout & rendering engine

## Concept

Every prior "from scratch" build in this repo has picked a runtime, a data
structure, or a simulation to reimplement: language VMs (Coil), a JIT (Ember),
a WASM toolchain (Kiln), a CPU pipeline (Silicon), SAT solvers, databases,
chess, physics engines, path tracers, tiny transformers (Loom ×8, Sprout),
compression codecs, a spreadsheet, search engines, a version-control system,
a blockchain, a CRDT editor, a matching engine, a Raft simulator, a SLAM
stack, a roguelike. One thing every one of those projects has quietly relied
on but never itself built: **the thing that turns HTML/CSS text into pixels
on a screen.** Every interactive visualizer in this repo's history has
outsourced that job to a real browser. Folio *is* that job.

Folio parses real (if simplified) HTML into a DOM tree, parses real CSS into
a stylesheet, resolves the CSS cascade (selector matching, specificity,
inheritance, `!important`) into a computed style per DOM node, runs a real
block-and-inline layout algorithm (box model, containing blocks, text line
wrapping, floats) to compute exact geometry for every box, and paints the
result — both to a real, independently-decodable PNG file (a hand-rolled
encoder, zero client-side logic, so the pixels are undeniably Folio's own
work) and to an interactive HTML/SVG "devtools" view for inspecting the
DOM/CSSOM/layout tree that produced them.

## Why this is interesting

- It is a genuinely new *kind* of artifact for this repo: not a solver, not
  a simulator, not a generative model — a deterministic pipeline that turns
  a declarative document + a declarative stylesheet into a two-dimensional
  arrangement of boxes, which is a different flavor of "hard, real,
  well-specified engineering problem" than anything shipped before.
- It has extremely legible ground truth: every real browser (there's a
  headless Chromium pre-installed in this environment) can render the exact
  same HTML/CSS input, so instead of an ad-hoc oracle, Folio's layout output
  can be differentially checked against real Chromium's computed box
  geometry (`getBoundingClientRect` / `getComputedStyle`) the same way past
  builds cross-checked against `gcc`, `objdump`, `sqlite3`, `git`, or Node's
  own WASM runtime. That is an unusually strong correctness signal for a
  "toy browser" — most from-scratch layout engines have no oracle at all.
- The CSS box model (margin/border/padding, containing blocks, block vs.
  inline formatting contexts, float layout, text line-breaking) is a rich
  enough problem to have a real required/stretch split without stretching
  for size: line-wrapping alone is a legitimate greedy algorithm with edge
  cases (long words, trailing whitespace, empty lines), and float layout is
  a genuinely different mode (boxes are removed from normal flow and other
  content wraps around them) from block/inline layout.
- It is honestly scoped down in exactly one place, stated up front rather
  than discovered as a shortcut later: text is measured and painted on a
  **fixed-pitch grid** (a monospace model — one design decision, applied
  consistently in the Python layout math, the PNG bitmap font, and the SVG
  inspector's `font-family: monospace`), so line-wrapping decisions are
  exact integer arithmetic instead of guessing real proportional glyph
  widths. This keeps every layout number checkable by hand and by the
  Chromium oracle (which is told to render the same monospace stack), the
  same way Beacon (2026-09-02) stated its MCL scope up front rather than
  quietly under-delivering on a "kidnapped robot" claim.

## Architecture

```
 .html text                          .css text
      │                                   │
      ▼                                   ▼
 ┌──────────┐                      ┌──────────────┐
 │  Tokenizer│                     │  CSS tokenizer│
 │  (HTML)   │                     │  + parser     │
 └────┬─────┘                      └──────┬────────┘
      ▼                                   ▼
 ┌──────────┐   default UA sheet   ┌──────────────┐
 │Tree builder│◄── + <style>/style=│  Stylesheet   │
 │ → DOM tree│                     │  (rule list)  │
 └────┬─────┘                      └──────┬────────┘
      │                                   │
      └────────────────┬──────────────────┘
                        ▼
                ┌────────────────┐
                │     Cascade    │  selector matching, specificity,
                │  → ComputedStyle│  origin/!important, inheritance,
                │   per DOM node │  used-value defaulting
                └───────┬────────┘
                        ▼
                ┌────────────────┐
                │  Layout tree   │  box generation (block/inline/none),
                │  builder +     │  block formatting context recursion,
                │  box-model     │  containing-block width resolution,
                │  layout engine │  inline line-box text wrapping,
                │                │  float layout + clearance
                └───────┬────────┘
                        ▼
                ┌────────────────┐
                │  Paint command │  ordered list of {rect fill, rect
                │  list          │  stroke (borders), text run} in
                │                │  painter's-algorithm (DOM) order
                └──┬──────────┬──┘
                   ▼          ▼
           ┌────────────┐ ┌─────────────────────┐
           │ PNG raster │ │ Interactive HTML/SVG │
           │ (hand-rolled│ │ inspector: click a  │
           │ encoder,   │ │ box → DOM path,      │
           │ bitmap font)│ │ computed style, box  │
           │            │ │ model diagram        │
           └────────────┘ └─────────────────────┘
```

## Stack

Pure Python 3 stdlib only for the whole engine (tokenizer, tree builder, CSS
parser, cascade, layout, paint, PNG encoder, bitmap font) — no `html.parser`,
no `tinycss`, no `PIL`, no layout library of any kind. The interactive
inspector is a single self-contained HTML/SVG/vanilla-JS file with the full
paint-command list embedded as inline JSON (no server, no client-side layout
logic — the browser only draws exactly what Folio computed). Playwright /
headless Chromium (pre-installed in this environment) is used exclusively as
an **external differential oracle**: it never appears inside the engine, only
in `tests/test_oracle.py`, to independently confirm Folio's computed box
geometry against a real browser's layout of the same monospace-styled HTML.

## Features (6 total: 4 required, 2 stretch)

1. **[Required] HTML parser → real DOM tree.** A hand-written tokenizer
   (tags, attributes with quoted/unquoted/boolean values, comments, raw-text
   elements `<script>`/`<style>`, character references `&amp;&lt;&gt;&quot;&nbsp;`)
   feeding a tree builder that is tolerant like a real browser: auto-closes
   unclosed `<p>`/`<li>` per a small implied-end-tag table, treats a known
   set of void elements (`<br>`, `<img>`, `<hr>`, `<meta>`, `<link>`) as
   self-closing without requiring `/>`, and never raises on malformed input.

2. **[Required] CSS parser + cascade → computed style per node.** A CSS
   tokenizer/parser for a real (subset of) CSS grammar — type/class/id/
   universal/descendant/child/adjacent-sibling selectors, comma-separated
   selector lists, `!important` — producing a rule list with real CSS
   specificity (a,b,c,d tuples), sorted and cascaded against a default
   user-agent stylesheet (block-level defaults, `<a>` color, etc.), author
   `<style>` rules, and inline `style=""` attributes, with correct property
   inheritance (`color`, `font-*`, `text-align`, `line-height`, ...) down
   the DOM tree.

3. **[Required] Block + inline box-model layout engine.** Real containing-
   block width resolution (percentages resolve against the parent content
   box, `auto` margins center a block), the full box model (content +
   padding + border + margin, `box-sizing: content-box`/`border-box`),
   recursive block-formatting-context layout (children stack vertically,
   margins collapse between adjacent block siblings per spec), and inline
   layout that wraps text + inline elements into line boxes by a real
   greedy line-breaking algorithm on the fixed-pitch text grid.

4. **[Required] Paint to an independently-decodable PNG.** A paint-command
   list (background/border rects in DOM paint order, text runs) rendered by
   a hand-rolled PNG encoder (zlib DEFLATE via Python's `zlib` module for
   the compressed-stream framing only — no drawing/layout help from it) and
   a from-scratch fixed-width bitmap font (a hand-authored glyph table for
   the printable ASCII range) — the final image is decodable and diffable
   with zero Folio code, e.g. by the system `file`/`convert` tools or any
   standard image library, proving it's a real PNG and not a shortcut.

5. **[Stretch] Float layout + clearance.** `float: left`/`float: right`
   pulls a box out of normal flow to a packed edge of its containing block;
   subsequent in-flow inline content flows around the remaining space on
   the same lines (real text reflow around a float, not just a repositioned
   box), and `clear: left/right/both` on a later block forces it below any
   active floats — the two behaviors together are what let real web pages
   from the mid-2000s (before flexbox/grid) do multi-column layout at all.

6. **[Stretch] Interactive DOM/box-model inspector.** A self-contained
   HTML/SVG page that renders the same paint-command list Folio's PNG
   encoder consumes, overlaid with clickable per-box hit regions: clicking
   any rendered box highlights it, shows its DOM path (`html > body > div.card`),
   its resolved CSS specificity-cascade origin(s), its full computed style,
   and a devtools-style box-model diagram (content/padding/border/margin
   as nested colored rectangles with real measured pixel values) — the
   from-scratch analogue of a real browser's "Inspect Element."

## Differential verification strategy

`tests/test_oracle.py` renders each example page in real headless Chromium
(monospace font-family forced via injected CSS, matching Folio's fixed-pitch
model) and reads back every element's `getBoundingClientRect()` position and
size, then asserts Folio's own layout-tree geometry for the same element
agrees within a small integer tolerance (rounding/subpixel differences).
This is a genuine second, independent, off-the-shelf implementation of CSS
layout to check against — the same role `gcc`/`objdump` played for Ember,
`sqlite3` played for PicoSQL, and Node's `WebAssembly` played for Kiln.

## Honest scope boundaries (stated up front, not discovered as a shortcut)

- Text is fixed-pitch/monospace only — no proportional font metrics, no
  font-weight-dependent glyph widths, no font shaping. Stated in Feature 3
  above; the whole point is that this makes line-wrap arithmetic exact and
  checkable against both a hand-computed answer and the Chromium oracle.
- No JavaScript execution, no network loading (`<img src>`/external
  stylesheets are parsed as inert attributes, not fetched) — Folio is a
  layout/paint engine, not a full user agent.
- Selector support covers type/class/id/universal/descendant/child/adjacent-
  sibling/comma-lists/`!important`, not the full CSS3 selector grammar
  (no `:nth-child()`, no attribute selectors) — deliberately enough to
  express real specificity/cascade conflicts without an open-ended grammar.
