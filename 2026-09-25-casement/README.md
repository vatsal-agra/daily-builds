# Casement

A from-scratch HTML/CSS layout and rendering engine in pure Python: a
hand-written HTML parser, a CSS parser + cascade engine, a block/inline +
flexbox layout engine, and a software rasterizer (with a hand-authored
bitmap font) that paints real pixels to a from-scratch PNG encoder. Ships
with an interactive DevTools-style box-model inspector and a Chromium
differential oracle that checks Casement's own layout math against a real
browser.

## Why this, today

This repo has built plenty of renderers (a 3D rasterizer, a path tracer, a
paragraph typesetter) and plenty of parsers/VMs (a bytecode language, a SQL
engine, a regex engine) — but never the two-dimensional constraint problem
sitting at the center of every web page: the CSS box model plus two
genuinely different layout algorithms sharing one box tree (normal
block/inline flow *and* flexbox), with margin collapsing, percentages, and
z-index stacking all interacting. Unlike a solved game or a deterministic
VM, CSS layout has a real spec — and, in this sandbox, a real independent
oracle already sitting there: headless Chromium. `casement compare` uses
it to diff Casement's computed box geometry against a real browser's
`getBoundingClientRect()`, element by element. Building that stretch
feature paid for itself immediately: it caught a cascade bug that had been
silently overriding every page's own CSS with the wrong defaults.

## How to run it

```bash
cd 2026-09-25-casement

# Run the full test suite (103 tests: parser, cascade, layout, flexbox,
# CLI error handling, adversarial edge cases, and — when Node+Playwright
# are available, as they are in this sandbox — real Chromium diffs).
python3 -m unittest discover -s tests

# Render a page to a real PNG.
python3 -m casement.cli render examples/showcase.html -o out.png --width 700

# Generate the interactive box-model inspector (open in any browser).
python3 -m casement.cli inspect examples/showcase.html -o inspector.html --width 700

# Diff against real headless Chromium.
python3 -m casement.cli compare examples/oracle_test.html --width 800 --tolerance 4

# Or run everything end-to-end in one shot:
./demo.sh
```

`examples/showcase.html` exercises the box model, flexbox (row/wrap/grow),
inline-block, percentage widths, `position: relative/absolute`, and text
wrapping in one page. `examples/oracle_test.html` is a second page, built
entirely from explicitly-sized boxes (no text-dependent sizing), so its
comparison against real Chromium isn't confounded by font-metric
differences — see PLAN.md for why that split matters.

## Full feature list

**Required (all 4 shipped):**

1. **HTML parser** (`casement/html_parser.py`) — a hand-written tokenizer
   (tags, attributes, text, comments, raw-text `<script>`/`<style>`, void
   elements) and a stack-based tree builder with real HTML error recovery:
   an open `<p>` is implicitly closed by the next block-level start tag, an
   open `<li>` by the next `<li>`, and mismatched/stray end tags recover by
   searching the open-element stack instead of crashing — exactly the
   malformed-markup cases that make HTML parsing harder than "just read the
   tags."
2. **CSS parser + cascade** (`casement/css_parser.py`, `casement/selector.py`,
   `casement/style.py`) — selectors (type, `.class`, `#id`, descendant,
   child `>`, comma groups, `*`, `:first-child`/`:last-child`), a real
   specificity calculator, cascade ordering (source order + specificity +
   `!important`, author rules correctly outranking the built-in user-agent
   stylesheet at equal specificity), property inheritance, and shorthand
   expansion (`margin`, `padding`, `border`, `background`, `font`, `flex`).
3. **Block + inline layout** (`casement/layout.py`) — block box
   width/auto-centering, adjacent-sibling and parent/first-child margin
   collapsing, and a real inline formatting context: text and inline
   elements shape into line boxes via greedy line-breaking/word-wrap
   against the available width, honoring `text-align` and `line-height`.
4. **Flexbox layout** (`casement/layout.py`) — `display: flex` with
   `flex-direction` (row/column, `-reverse`), `flex-grow`/`flex-shrink`/
   `flex-basis`, `flex-wrap`, `justify-content`, `align-items`, correctly
   coexisting with block layout so a flex container can hold block
   children (and a flex item can itself contain arbitrary block/inline
   content) — verified to sub-pixel agreement with real Chromium.

**Stretch (both shipped):**

5. **Interactive box-model inspector** (`casement/inspector.py`, `casement
   inspect`) — a self-contained HTML page (Canvas-free, plain positioned
   `<div>`s + vanilla JS, no build step, no dependencies) showing the
   actual rendered page; hovering any element highlights its margin/
   border/padding/content boxes on the page and renders the real
   DevTools-style nested box-model diagram with every edge's numeric value,
   picking the innermost real element under the cursor. Verified with a
   real headless-Chromium pass: zero console errors, hover panel updates.
6. **Chromium differential oracle** (`casement/oracle.py`, `casement
   compare`) — renders the identical page (via a from-scratch DOM
   serializer) in real headless Chromium and Casement, matches elements by
   an injected `data-cid` attribute, and diffs every element's real
   `getBoundingClientRect()` against Casement's own computed border box.
   External, independent ground truth — not just internal self-consistency.

**Bonus beyond the 4+2 minimum:** `position: relative`/`absolute` with a
real containing-block search (nearest positioned ancestor, or the true
viewport if there isn't one) and `z-index`-ordered paint stacking.

## Verification

- 103 unit tests (`python3 -m unittest discover -s tests`): parser
  error-recovery rules, cascade specificity/inheritance/shorthands, exact
  layout geometry (not "did it crash" — real pixel/box-position
  assertions), CLI error handling, a 19-case adversarial battery of
  hostile HTML/CSS, the inspector's generated output, and real
  headless-Chromium differential tests.
- `casement compare examples/oracle_test.html --tolerance 4` agrees with
  real Chromium **exactly** (0.0px) on 14 of 17 elements; the remaining 3
  differ only by the documented ~3px inline-block baseline-strut quirk
  (a font-metric difference, not a layout bug — see PLAN.md).
- `./demo.sh` runs all of the above plus a real render, a real
  headless-Chromium inspector smoke test, and an independent manual CLI
  walkthrough — 11/11 checks green.
- `REVIEW.md` documents 13 real bugs found by adversarial testing and
  fixed before shipping, several of them structural (a coordinate-model
  ordering bug, a cascade tie-break bug that silently overrode every
  page's own CSS resets, flex items ignoring their own computed size).

## Where a human could take this next

- **Real font rendering.** Swap the hand-authored monospace bitmap font
  for actual vector glyph outlines (TrueType/OpenType parsing + a
  scanline rasterizer) — the layout engine's line-breaking already
  measures per-character advance width generically, so it would mostly be
  a drop-in under `casement/font.py`.
- **Tables.** `<table>`/`<tr>`/`<td>` currently fall back to generic block
  behavior (no column-width algorithm, no cell layout) — a real table
  layout algorithm is its own, differently-shaped constraint problem.
- **CSS Grid.** The flexbox solver's structure (box-model resolution →
  main/cross axis distribution → position) generalizes reasonably well to
  a two-dimensional grid track algorithm.
- **Multi-level margin collapsing** and the empty-block self-collapsing
  case, both explicitly scoped out in `PLAN.md`/`REVIEW.md`.
- **A real static-position algorithm** for `position: absolute` with no
  `top`/`left` set, instead of the current 0-fallback approximation.
- Wire `casement compare` into a CI check that fails a PR if a layout
  change regresses agreement with the Chromium oracle beyond a tolerance —
  the pieces (`OracleDiff`, `--tolerance`) are already there.
