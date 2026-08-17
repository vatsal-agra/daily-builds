# Folio — a browser rendering engine, built from scratch

## Concept

Every prior build in this repo's history that touches "rendering" has rendered
either 3D scenes (Prism, Lumina, Lumen, Pathtracer) or 2D physics/data
visualizations. None has touched the single most-used rendering pipeline on
the planet: the one that turns HTML + CSS into pixels on a screen. Folio is
a from-scratch browser engine core — HTML parser → DOM → CSS cascade →
computed styles → box-model layout → paint — implementing the actual
algorithms real browsers use (CSS2.1 §8/§9/§10: the box model, block
formatting contexts, margin collapsing, inline formatting contexts) rather
than a toy approximation.

## Why it's interesting

1. **A genuinely new domain for this repo.** 60+ prior builds cover
   compilers/VMs/JITs, physics/fluid/creature sims, SAT solvers, path
   tracers, crypto, compression, search engines, and (extremely heavily)
   from-scratch transformers — but never document layout. It is a different
   kind of hard: not numerical, not combinatorial search, but a cascading
   constraint-resolution algorithm operating over a tree, with a spec that
   reads like a legal document (CSS2.1) and decades of implementation
   folklore behind "just render this div."
2. **Unusually strong, unusually *real* ground truth.** Playwright/Chromium
   is pre-installed in this environment. For the CSS2.1 subset Folio
   implements (block boxes: width/height/margin/padding/border resolution,
   auto-margin centering, adjoining-margin collapsing, containing-block
   chains), the box-model algorithm is exactly specified — a real browser
   and a correct from-scratch implementation must produce the *same*
   `getBoundingClientRect()` geometry, to the pixel. That gives Folio an
   oracle no prior "renderer" build in this repo has had: not "looks
   plausible," not "matches a hand-derived closed form," but "the actual
   engine that renders billions of pages agrees with mine, exactly."
   (Text/inline metrics are the one place this breaks down honestly — see
   Architecture — and Folio verifies those against a self-contained,
   independently-implemented reference instead of pretending to match
   Chromium's real font rasterizer.)
3. **A complete, demoable pipeline.** Feed it a `.html` file with a `<style>`
   block (or linked `.css`), get back an interactive SVG render plus a
   Chrome-DevTools-style box-model inspector — a satisfying, visual result
   that also happens to be a serious systems-engineering exercise.

## Architecture

```
  .html text
      │  tokenizer (tag soup tolerant: implicit closes, void elements,
      │             comments, entities, raw text elements)
      ▼
  token stream
      │  tree construction (stack-of-open-elements, insertion-mode-lite)
      ▼
  DOM tree (Document/Element/Text/Comment nodes)
      │
      │  .css text (author stylesheet) ──┐
      │                                  │  CSS tokenizer + parser
      │  UA default stylesheet ──────────┤  (rules = selector-list + decls)
      │  inline style="" attributes ─────┘
      ▼
  selector matching + cascade
      │  (specificity (a,b,c,d), !important, source order,
      │   inheritance for inherited props, initial values otherwise)
      ▼
  computed style per DOM node
      ▼
  layout tree (anonymous block box wrapping for mixed inline/block content)
      │  block formatting context: width/height resolution over the CSS2.1
      │  §10.3/§10.6 auto rules, containing-block chains, auto-margin
      │  centering, adjoining-margin collapsing (parent/child, siblings,
      │  empty blocks)
      │  inline formatting context: greedy line-breaking over a bundled,
      │  self-consistent monospace-grid font-metric model, line-height,
      │  text-align (left/right/center/justify)
      │  float layout (stretch): float:left/right, content flows around,
      │  clear:left/right/both
      ▼
  positioned box tree (content/padding/border/margin rects per box, in
  document coordinates)
      │  paint
      ▼
  self-contained interactive HTML/SVG viewer:
    - rendered page (background/border/text as SVG)
    - click-to-inspect box model (Chrome-DevTools-style nested
      content/padding/border/margin rectangles + computed style table)
    - oracle-diff panel: the same fixtures rendered by real headless
      Chromium via Playwright, geometry overlaid with px deltas
```

## Feature list

**Required (core, must fully work end-to-end):**

1. **HTML parser → DOM tree.** Tag-soup-tolerant tokenizer + tree builder:
   implicit `<p>`/`<li>`/`<tr>` closing, void elements (`<br>`, `<img>`,
   `<meta>`, ...), comments, `<script>`/`<style>` raw-text handling, HTML
   entity decoding (`&amp;` `&lt;` `&nbsp;` numeric `&#...;`), malformed/
   mismatched close tags recovered without crashing.
2. **CSS cascade engine.** CSS tokenizer + parser for a real rule grammar
   (selector lists, declaration blocks); selector matching for type, `.class`,
   `#id`, `*`, descendant, child (`>`), comma groups, attribute selectors
   (`[attr]`, `[attr=val]`), and structural pseudo-classes (`:first-child`,
   `:last-child`); full specificity-tuple cascade with `!important` and
   source-order tie-breaking; property inheritance; a real default
   user-agent stylesheet (block-level `<div>`/`<p>`/headings, `<li>` markers,
   etc.) so unstyled HTML still lays out sanely, exactly like a real browser.
3. **Block layout engine (CSS2.1 box model), verified against Chromium.**
   Correct width/height auto-resolution over the containing-block chain,
   auto-margin centering, and adjoining-margin collapsing (parent↔first-child,
   sibling↔sibling, empty-block self-collapse) — differentially checked
   against real headless Chromium's `getBoundingClientRect()` on the same
   fixtures via Playwright, box-for-box, to the pixel.
4. **Inline layout / text flow.** Line-box construction via greedy word
   wrapping against a bundled fixed-grid font-metric model, `line-height`,
   and `text-align: left/right/center/justify` (justify redistributes
   inter-word space so every non-last line's content edges are flush);
   independently verified against a brute-force reference line-breaker.

**Stretch:**

5. **Float layout.** `float: left/right` with later inline content flowing
   around the float's margin box, and `clear: left/right/both` on
   subsequent block boxes.
6. **Interactive DevTools-style inspector + oracle-diff viewer.** Click any
   rendered element to see its nested content/padding/border/margin box
   model (the real Chrome DevTools diagram) and its resolved computed
   style; a second panel overlays Folio's block geometry against the
   Playwright/Chromium oracle for the same fixture with numeric px deltas.

## Phase 4 status

Both stretch features shipped:

5. **Float layout** — `float:left/right`, source-order left-to-right/
   right-to-left packing with wrap-to-next-line when a float doesn't fit,
   `clear:left/right/both`, CSS2.1 9.7 "blockification" of a floated
   inline-level element (a floated `<img>` lays out as a block, not
   flattened text), and a documented shrink-to-fit approximation for
   `float` boxes with `width:auto`. In-flow text re-queries the float
   exclusion zone per line and wraps around it; a real bug (a float's
   margin box silently absorbing the rest of its container's width by
   reusing the *normal* block width algorithm, which is wrong for floats)
   was caught by direct testing and fixed with a dedicated
   `resolve_float_width` — see REVIEW.md.
6. **Interactive box-model inspector + Chromium oracle-diff viewer**
   (`folio inspect`) — a self-contained HTML page (no CDN, no build step):
   click any rendered element to see a Chrome-DevTools-style nested
   content/padding/border/margin diagram and its resolved computed style,
   plus (when `data-t` attributes and Playwright are available) a live
   Folio-vs-Chromium Δpx table for the same fixture — the test suite's
   oracle, made visible and interactive rather than only living in
   `tests/test_layout_block.py`.

## What could replace a required feature

Not anticipated to be necessary — the four required features are the
well-specified, load-bearing core of any browser engine (parse → cascade →
box layout → text flow) and are scoped to what a single from-scratch Python
implementation can do correctly and verifiably in one day. If inline/text
layout verification against Chromium turns out to be unworkably imprecise
(different font metrics between engines), Folio will verify it against its
own independently-written brute-force reference line-breaker instead of
silently dropping the feature — see Architecture above; this is the plan,
not a fallback discovered mid-build.
