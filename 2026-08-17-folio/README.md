# Folio

A browser rendering engine built entirely from scratch in pure Python:
**HTML text → DOM tree → CSS cascade → computed styles → CSS2.1 box-model
layout → paint**, verified against real headless Chromium rather than only
against itself.

This is Folio's core claim, and you can check it yourself:

```
$ python3 cli.py render fixtures/sample1.html -o out.svg --width 600
wrote out.svg (600x381)
```

That SVG is Folio's own from-scratch rasterization of the box model + text
flow it computed — no browser involved in producing it. Separately,
`tests/test_layout_block.py::TestAgainstChromium` renders the *same* HTML
in real headless Chromium and asserts Folio's box geometry matches
`getBoundingClientRect()` to the pixel.

## What it is

Every prior build in this repo's history that touches "rendering" has
rendered 3D scenes, physics sims, or data visualizations. None has built
the single most-used rendering pipeline on the planet: the one that turns
HTML + CSS into pixels. Folio implements the actual algorithms real
browsers use for the subset of CSS2.1 it covers — not a toy approximation:

- A hand-written HTML tokenizer + tree-builder (tag-soup tolerant: implicit
  `<p>`/`<li>`/`<tr>` closing, void elements, raw-text `<script>`/`<style>`
  handling, character-reference decoding, malformed-markup recovery).
- A CSS parser + selector-matching + cascade engine (specificity,
  `!important`, source order, inheritance, a real default user-agent
  stylesheet) that turns markup + stylesheets into one resolved computed
  style per element.
- A CSS2.1 §8/§10 box-model layout engine: width/height auto-resolution
  over containing-block chains, auto-margin centering, and — the genuinely
  hard part — **margin collapsing** (sibling-to-sibling, parent↔first/
  last-child collapse-through at unlimited nesting depth, self-collapsing
  empty boxes) implemented as a real recursive algorithm, not a special
  case or two.
- A greedy inline formatting context (line-box construction, `text-align:
  left/right/center/justify`) and **float layout** (`float: left/right`
  with real left-to-right packing and wrap-to-next-line, `clear`, and
  CSS2.1 9.7 "blockification" of a floated inline element).
- An SVG paint stage, and an **interactive box-model inspector**
  (`folio inspect`) — click any rendered element for a Chrome-DevTools-
  style content/padding/border/margin diagram, its computed style, and (for
  fixtures with `data-t` attributes) a live Folio-vs-Chromium Δpx panel.

## Why this, today

1. **A genuinely new domain for this repo.** 60+ prior builds cover
   compilers/VMs/JITs, physics/fluid sims, SAT solvers, path tracers,
   crypto, compression, search engines, and (extremely heavily) from-
   scratch transformers — never document layout: a cascading
   constraint-resolution algorithm over a tree, governed by a spec that
   reads like a legal document and decades of implementation folklore.
2. **Unusually real ground truth.** Playwright + headless Chromium are
   pre-installed in this environment. For the CSS2.1 subset Folio
   implements, the box-model algorithm is exactly specified — a correct
   from-scratch implementation and a real browser *must* produce identical
   `getBoundingClientRect()` geometry. That gave this build an oracle no
   prior "renderer" project in this repo has had: not "looks plausible,"
   not "matches a hand-derived closed form," but "the actual engine that
   renders billions of pages agrees with mine, to the pixel" — and that
   oracle earned its keep immediately: it caught a quirks-mode trap in the
   test setup itself, a margin-collapsing double-processing bug, a
   self-collapsing-box positioning bug, and (while building floats) a
   float width algorithm that was silently wrong, not just imprecise. See
   `REVIEW.md`.
3. **A complete, demoable pipeline with an honest scope boundary.** Folio
   does not rasterize real font glyphs — it says so explicitly
   (`fontmetrics.py`) rather than pretending to match Chromium's text
   metrics, and the test suite's oracle comparisons are scoped accordingly
   (box-model geometry is checked exactly; line-height-derived height is
   not). Disclosed limitations, not silent ones.

## How to run it

```bash
# Full verification: unit tests + end-to-end demo + CLI smoke checks
bash demo.sh

# Individual pipeline stages
python3 cli.py parse    fixtures/sample1.html                    # DOM tree dump
python3 cli.py cascade  fixtures/sample1.html                    # computed styles
python3 cli.py layout   fixtures/sample1.html --width 600        # box-model tree dump
python3 cli.py render   fixtures/sample1.html -o out.svg --width 600
python3 cli.py inspect  fixtures/sample1.html -o inspect.html --width 600
                                                    # open inspect.html: click to explore

python3 -m unittest discover -s tests -v            # 138 tests
```

The Chromium-oracle half of the test suite (`TestAgainstChromium` in
`tests/test_layout_block.py`, and the diff panel in `folio inspect`) needs
`playwright` (`pip install -r requirements-dev.txt`; the Chromium binary is
already present at `/opt/pw-browsers/chromium-1194` in this environment).
Without it, that one test class is skipped automatically and everything
else — including `demo.sh` — still runs and passes.

## Feature list

**Required (all shipped, each demonstrated end-to-end in `folio/demo.py`
and covered by dedicated tests):**

1. HTML parser → DOM tree (`folio/html_parser.py`, `folio/entities.py`).
2. CSS cascade engine (`folio/css_parser.py`, `folio/cascade.py`).
3. Block layout / CSS2.1 box model, verified pixel-exact against Chromium
   for 14 fixtures (`folio/layout.py`, `tests/test_layout_block.py`).
4. Inline layout / text flow, verified against an independent brute-force
   reference line-breaker (`tests/test_layout_inline.py`).

**Stretch (both shipped):**

5. Float layout — packing, wrapping, `clear`, blockification
   (`tests/test_floats.py` + 2 Chromium-oracle fixtures).
6. Interactive box-model inspector + live oracle-diff viewer
   (`folio/inspector.py`, `tests/test_inspector.py`).

**Plus:** an SVG paint stage, a 6-subcommand CLI, a clean-error CLI layer
(no raw tracebacks for missing files / empty documents / malformed CSS /
negative dimensions / pathologically deep nesting), and a bundled
end-to-end demo + gallery generator.

## Verification

- **138 automated tests** (`python3 -m unittest discover -s tests`):
  HTML parser (20), CSS parser (17), cascade (24), block layout incl. 14
  Chromium-oracle fixtures (34), inline layout incl. an independent
  brute-force line-breaker oracle (12), floats (7), the inspector (4),
  paint (6), entities (8), CLI robustness/regression (6), plus the demo's
  own assertions.
- **`demo.sh`**: the full test suite + a narrated, assertion-backed
  walkthrough of every feature against real input + direct CLI smoke
  checks — 13/13 green, works with or without Playwright installed.
- **`REVIEW.md`**: the adversarial-review record — 14 real bugs found by
  actually running the engine against hostile/edge-case input (not by
  inspection), every one fixed with a regression test. Read it for the
  interesting stuff: the quirks-mode oracle trap, the margin-collapsing
  double-processing bug, the float-width algorithm bug, and more.

## Architecture

```
  .html text --tokenizer+tree builder--> DOM tree
  .css text  --parser--------------------> stylesheet
  DOM + stylesheet(s) --selector match + cascade + inheritance--> computed style/element
  computed styles --anonymous-box-wrapped layout tree builder--> LayoutBox tree
  LayoutBox tree --CSS2.1 width/height/margin-collapsing/float/line-break algorithms--> positioned boxes
  positioned boxes --paint-------------------------------------> SVG
                   --inspector------------------------------------> interactive HTML
```

See `PLAN.md` for the full architecture writeup and feature rationale.

## Where a human could take this next

- **Real font metrics.** Swap the fixed-advance monospace model for actual
  glyph metrics (even a bundled TTF + a simple hinting-free shaper) to get
  Chromium-matching text geometry, not just Chromium-matching box geometry.
- **Full float propagation.** Extend `FloatContext` to propagate into
  nested descendant containers (not just the direct-sibling scope this
  build covers) — the general algorithm is a well-known extension of what's
  here, mainly bookkeeping.
- **Inline formatting fidelity.** Per-run vertical alignment (`vertical-
  align`), mixed font-sizes within one line box computing a proper
  "strut," and `white-space: nowrap`/`pre-wrap`.
- **CSS coverage.** Flexbox or Grid (a real second layout mode), `position:
  absolute/fixed` (currently parsed but not specially laid out — see
  REVIEW.md), sibling combinators (`+`, `~`), media queries actually
  evaluated rather than skipped, CSS custom properties.
- **A real event loop.** Wire `folio inspect`'s click-to-inspect page up to
  a live re-render-on-edit CSS playground (Folio's own engine already runs
  fine driven from a small JS↔Python bridge like Formulate/Gambit's
  server-backed UIs elsewhere in this repo) instead of only inspecting a
  static render.
- **Performance.** The layout walk is currently O(n) in DOM size (after the
  Phase-3 fix to the margin-collapsing accumulator) but single-threaded and
  re-lays-out the whole tree on any change; incremental/dirty-subtree
  relayout would be the natural next step for anything interactive.
