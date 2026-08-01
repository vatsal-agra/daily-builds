# Reflow — a browser rendering engine, from scratch

## Concept

Every browser turns text (HTML + CSS) into pixels through the same four-stage
pipeline: **parse** markup into a DOM tree, **parse** stylesheets and **cascade**
them onto that tree, **layout** the styled tree into positioned/sized boxes,
then **paint** those boxes into a bitmap. Reflow implements all four stages
from scratch in pure Python — no `html.parser` tree-building shortcuts beyond
tokenizing, no `tinycss`/`cssutils`, no Pillow, no headless browser. Given a
real (possibly malformed) HTML document and a real stylesheet, it produces a
genuine PNG file that is the actual rendering, and it can show its own
intermediate state (DOM, CSSOM, cascade decisions, layout boxes) for any input.

## Why this is interesting

Every previous daily build that touched "from scratch X" has picked X from
compilers, databases, ML, physics, graphics/rendering (3D), crypto, or search.
None have touched the specific pipeline that turns markup into a web page.
It's a great fit for the repo's house style — a real spec-shaped algorithm
(the HTML5 tree-construction algorithm and CSS cascade are genuinely
subtle: implicit tag closing, specificity tie-breaking, inheritance,
line-breaking) with lots of internal state that's satisfying to visualize.
It also composes four non-trivial from-scratch algorithms into one product
instead of being a single algorithm demo, which keeps it closer to "build a
complete thing" than "implement one paper."

## Architecture

```
  HTML text                CSS text
     |                        |
     v                        v
 [html_tokenizer]       [css_tokenizer]
     |                        |
     v                        v
 [dom_builder]  -------> [css_parser]  -> CSSOM (rules + selectors)
     |                        |
     v                        v
   DOM tree  ------------>  [cascade]  -> computed style per DOM node
                                |
                                v
                          [layout engine]  -> positioned/sized box tree
                                |
                                v
                            [painter]  -> pixel buffer -> [png_encoder] -> .png
```

Everything lives under `reflow/`:
- `reflow/html_parser.py` — tokenizer + tree-construction state machine → `Node` DOM tree
- `reflow/css_parser.py` — CSS tokenizer + selector/declaration parser → `Stylesheet`
- `reflow/cascade.py` — selector matching, specificity, cascade, inheritance → `ComputedStyle` per node
- `reflow/layout.py` — box generation, block layout, inline layout w/ line-breaking, flexbox
- `reflow/paint.py` — paints a layout tree into an `RGB` pixel buffer (backgrounds, borders, text)
- `reflow/font.py` — hand-rolled 8x8 bitmap glyph table + text-measuring/rasterizing
- `reflow/png_encoder.py` — minimal valid PNG writer (IHDR/IDAT/IEND, zlib-compressed scanlines)
- `reflow/browser.py` — ties the pipeline together: `render(html, css) -> (dom, cssom, layout_tree, png_bytes)`
- `server.py` — stdlib `http.server` backing the interactive visualizer (all real logic, zero client-side layout code — same architecture as prior server-backed builds)
- `viewer.html` — single-file browser UI: paste HTML+CSS, POST to the server, render DOM tree / cascade explanation / layout box diagram (SVG) / final PNG side by side
- `cli.py` — `render <file.html> [--css file.css] -o out.png`, plus `--dump-dom`/`--dump-layout` debug dumps
- `tests/` — unit tests per stage + end-to-end golden-pixel tests

## Feature list

### Required (core, must work end-to-end with zero stubs)

1. **HTML5-style tokenizer + tree-construction parser.** A real state-machine
   tokenizer (data state, tag-open, attribute states, comment state) feeding a
   tree-construction algorithm that handles void elements (`<br>`, `<img>`),
   implicitly-closed elements (`<p>` auto-closes on a following `<p>`),
   unclosed/malformed tags, comments, and text nodes — producing a real DOM
   tree, not a naive regex strip.

2. **CSS parser + cascade.** A CSS tokenizer and parser that reads real
   selector syntax (type, `.class`, `#id`, descendant ` `, child `>`,
   comma-separated groups) and declarations into a CSSOM, then a cascade
   step that matches every selector against every DOM node, resolves
   conflicts by specificity → source order → `!important`, and applies
   property inheritance (e.g. `color`, `font-size` inherit; `margin` does
   not) to produce one `ComputedStyle` per node.

3. **Layout engine.** Turns the styled DOM into a positioned, sized box
   tree: the CSS box model (content/padding/border/margin), block-flow
   layout (vertical stacking, margin collapsing between adjacent block
   siblings), and inline layout with real greedy line-breaking that wraps
   text at word boundaries against the available width, measured against
   actual glyph widths from the bitmap font.

4. **Painter + real PNG output.** Walks the final layout tree in paint
   order and rasterizes backgrounds, borders, and glyph-rendered text into
   an RGB pixel buffer, then encodes that buffer as a genuinely valid PNG
   (correct IHDR/IDAT/IEND chunks, CRC-32 per chunk, zlib-compressed
   scanlines) — openable in any real image viewer, not a fake preview.

### Stretch (2+, implement at least 1)

5. **Flexbox layout mode.** `display: flex` containers with
   `flex-direction: row|column`, `justify-content`
   (start/center/end/space-between), `align-items` (start/center/end/stretch),
   `gap`, and `flex-grow` distributing remaining space among children — a
   second, selectable layout algorithm alongside block/inline flow.

6. **Interactive visualizer.** A server-backed page (`viewer.html` +
   `server.py`, stdlib `http.server` only) where pasting HTML+CSS and
   clicking "Render" makes a real round trip through the actual Python
   engine and returns: the DOM tree (indented, with computed tag/attrs),
   the CSSOM with each rule's specificity, a per-node cascade explanation
   (which rule won and why), an SVG diagram of the layout box tree with
   real pixel coordinates/dimensions overlaid, and the final rendered PNG
   — all four pipeline stages, side by side, for the exact same input.

## Non-goals (explicitly out of scope, to keep this a complete product rather than a fragment)

- JavaScript execution — this is a rendering engine, not a JS engine.
- Real font files (TrueType/OpenType parsing) — a hand-rolled bitmap font
  is real rasterization, just not scalable typography; documented in README.
- Network loading (`<link>`/`<img src>` fetching over HTTP) — inputs are
  local HTML/CSS text/files, which is enough to prove the pipeline.
- Full CSS3 (grid, animations, transforms, media queries) — the box model,
  block/inline flow, and flexbox subset above are the target surface.
