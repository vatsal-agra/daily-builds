# Cascade

A from-scratch HTML/CSS **layout and rendering engine** — the part of a web
browser that turns markup + stylesheets into an actual picture: parse HTML
into a DOM, parse CSS and apply the cascade to get computed styles, run a
real box-model layout algorithm (block + inline formatting contexts, margin
collapsing, line breaking, floats), and paint the resulting box tree to SVG.

## Why this is interesting

This repo has built compilers, VMs, SAT solvers, path tracers, search
engines, and nine Transformers from scratch — but never the single most
*used* piece of software architecture in the world: the HTML/CSS rendering
pipeline every person on Earth looks through dozens of times a day. It sits
in genuinely uncharted territory for this ledger:

- Galley (2026-06-18) did optimal *paragraph* line-breaking (Knuth-Plass) —
  Cascade needs line breaking too, but as one piece of a much larger box
  tree with block/inline formatting contexts, margin collapsing, and a
  cascade/specificity system on top.
- Optic (2026-06-28) and Prism (2026-06-28) did pixel-level rendering, but
  from a numeric/3D scene description, not from a *document* with a
  cascading style language over a tree.
- No prior build has implemented CSS's cascade algorithm, the CSS box
  model, or the block/inline formatting-context distinction that decides
  whether `<div>`s stack vertically or text flows and wraps horizontally.

It also has an unusually strong verification story available in *this*
sandbox specifically: a real headless Chromium is pre-installed
(`/opt/pw-browsers/chromium`, driven by Node's `playwright` package). That
means Cascade's layout output can be differentially checked against an
actual production browser engine's real `getBoundingClientRect()` geometry
— not just "looks plausible," but "the same box positions Chromium
computes," the same spirit as Graft diffing against real `git` or Faraday
checking against closed-form circuit theory.

## Architecture

```
testpages/*.html          hand-written HTML+CSS fixtures (also fed to Chromium)
        |
        v
cascade/html_parser.py    tokenizer (data/tag/attr/comment states) + tree
        |                 construction (implicit tag closing, void elements)
        v  DOM tree
cascade/css_parser.py     CSS tokenizer + parser -> stylesheet
        |                 (selectors, declarations, specificity)
        v  Stylesheet
cascade/cascade.py        UA stylesheet + author stylesheet + inline style
        |                 -> cascade + specificity + !important + inheritance
        v  ComputedStyle per DOM node
cascade/layout.py         box model: block formatting context (vertical flow,
        |                 margin collapsing) + inline formatting context
        |                 (whitespace collapsing, greedy line breaking,
        |                 proportional font metrics) + floats
        v  LayoutBox tree (x, y, width, height, edges)
cascade/paint.py          LayoutBox tree -> SVG document (backgrounds,
        |                 4-sided borders, positioned text runs)
        v
render.svg

cascade/engine.py         render_html(html, extra_css) -> (dom, styles, box tree, svg)
cli.py                    `cascade render page.html -o out.svg`, `cascade dump-boxes`

oracle/diff.mjs           Node+Playwright: loads a test page in real headless
                           Chromium, reads getBoundingClientRect() for every
                           element, and diffs it against Cascade's own layout
                           for the same page (oracle/run_diff.py drives both
                           sides and reports per-element deltas).

server.py                 stdlib http.server: POST /render {html, css} ->
                           runs the real engine, returns SVG + box-model
                           overlay JSON. playground.html is a thin client
                           (zero layout logic — same "server does the real
                           work" pattern as Gambit/Formulate/Trove in this
                           repo's own history).
```

## Feature list

**Required (core, must fully work end-to-end):**

1. **HTML parser** — hand-written tokenizer + tree-construction algorithm
   producing a real DOM (elements, attributes, text nodes, comments), with
   implicit closing of unclosed tags (`<p>`, `<li>`, `<td>`...), a table of
   void elements (`<br>`, `<img>`, `<input>`...), and graceful recovery from
   malformed markup (never throws on real-world HTML).
2. **CSS parser + cascade** — CSS tokenizer + parser for a real selector
   grammar (type, `.class`, `#id`, `*`, descendant, child `>`, attribute
   `[attr]`/`[attr=val]`, `:first-child`/`:last-child`/`:nth-child(n)`) and
   declaration blocks; a UA default stylesheet; the real cascade algorithm
   (source order → specificity → `!important`) plus CSS inheritance,
   producing one `ComputedStyle` per DOM node.
3. **Layout engine** — real box model (content/padding/border/margin,
   `box-sizing`), a block formatting context (vertical stacking, width
   resolution from the containing block, margin collapsing between
   adjacent siblings and parent/first-child), and an inline formatting
   context (CSS whitespace collapsing, greedy line breaking against
   proportional per-character font metrics, line boxes, `line-height`,
   `text-align: left/center/right/justify`).
4. **Paint (SVG renderer)** — walks the final box tree and emits a real SVG
   document: background rects, independently-styled 4-sided borders, and
   text runs positioned per line box at their computed baseline — not a
   passthrough of the input, a genuine geometric renderer of Cascade's own
   layout numbers.

**Stretch:**

5. **Float layout** — `float: left/right` with normal-flow content wrapping
   around floated boxes, and `clear: left/right/both`.
6. **Chromium differential oracle** — a Playwright-driven harness that
   renders the same test pages in real headless Chromium and reports
   per-element bounding-box deltas against Cascade's own layout, used as
   the primary verification tool in place of (or alongside) hand-written
   expected values.
7. **Interactive server-backed playground** — edit HTML/CSS in a browser
   page, submit to a stdlib `http.server` that runs the *real* Cascade
   engine and returns the rendered SVG plus a box-model debug overlay
   (hover a box to see its margin/border/padding/content edges) — the
   browser client holds zero layout logic.
