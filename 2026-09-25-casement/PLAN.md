# Casement — a from-scratch HTML/CSS layout & rendering engine

## Concept

Every browser hides the same machine underneath: parse markup into a tree,
parse stylesheets into rules, cascade those rules onto the tree, turn the
styled tree into boxes, lay the boxes out according to CSS's layout
algorithms, and paint pixels. Casement builds that machine from scratch in
pure Python — no `html.parser`, no `tinycss`, no browser library anywhere on
the rendering path — and renders real `.html` + `.css` input to a real PNG,
byte by byte, glyph by glyph.

## Why this is interesting

This repo has built plenty of renderers (a 3D rasterizer in Prism, a path
tracer in Lumina, a paragraph typesetter in Galley) and plenty of parsers/VMs
(Coil's bytecode language, PicoSQL's SQL engine, RegexLab's regex engine).
It has never built the specific two-dimensional constraint problem that
sits at the center of every web page: the CSS box model plus two genuinely
different layout algorithms sharing one box tree — normal block/inline flow
*and* flexbox — with margin collapsing, containing-block-relative
percentages, and z-index stacking for positioned elements all interacting.
Unlike a solved game or a deterministic VM, CSS layout has a real published
spec and a real oracle already sitting in this sandbox: a headless Chromium.
That means Casement gets something none of this repo's from-scratch engines
usually get — an *external, independent ground truth* to differentially
verify against, not just an internal test suite. `compare` renders the same
page in Casement and in real Chromium and diffs the actual computed box
geometry (`getBoundingClientRect`), element by element.

## Architecture

```
 .html file        .css file (inline <style> or external)
     |                    |
     v                    v
 HTML tokenizer      CSS tokenizer
     |                    |
     v                    v
 HTML tree builder    CSS parser  --> Stylesheet (rules + selectors + specificity)
     |                    |
     v                    |
   DOM tree  <------------+---- cascade + inherit ----> ComputedStyle per node
     |
     v
 Box tree builder (anonymous block/inline boxes, one box per styled node)
     |
     v
 Layout engine
   - Block/inline formatting context (normal flow, margin collapsing,
     text line-breaking + wrapping)
   - Flexbox formatting context (main/cross axis, grow/shrink, wrap,
     justify-content/align-items)
   - Positioned layout (relative offset, absolute w.r.t. nearest
     positioned ancestor, z-index paint ordering)
     |
     v
 Paint (software rasterizer: backgrounds, borders, box-shadow-free flat
 fills, bitmap-font text) -> RGBA framebuffer -> from-scratch PNG encoder
     |
     v
   output.png                    +  layout.json (exported box tree,
                                     for the inspector and the oracle diff)
```

Supporting tools: a hand-rolled 8x8 bitmap font (real glyph rasterization,
not filled rectangles), an interactive single-file HTML "DevTools" box-model
inspector that reads `layout.json` and lets you click any box to see its
margin/border/padding/content geometry exactly like a browser's inspector,
and a Playwright/Chromium-backed differential oracle.

## Feature list

1. **[required] HTML parser** — hand-written tokenizer (tags, attributes,
   text, comments, void elements) + tree builder with real HTML error
   recovery (auto-closing `<p>`, `<li>`, optional `</html>`/`</body>`,
   implicit `<tbody>`-style nesting rules for the subset of tags supported)
   producing a DOM tree of `Element`/`Text` nodes.
2. **[required] CSS parser + cascade** — tokenizer + parser for selectors
   (type, `.class`, `#id`, descendant, child `>`, comma groups, `*`,
   `:first-child`/`:last-child`), a real specificity calculator, cascade
   ordering (source order + specificity + `!important`), property
   inheritance, and computed-style resolution (percentages resolved against
   the containing block, `auto` keywords, shorthand expansion for
   margin/padding/border/font/background).
3. **[required] Block + inline layout** — the normal-flow algorithm: block
   box widths/auto-centering, adjacent-sibling and parent-child margin
   collapsing, an inline formatting context that shapes text + inline
   elements into line boxes with real greedy line-breaking/word-wrap against
   the available width, text-align, and line-height.
4. **[required] Flexbox layout** — `display: flex` with `flex-direction`
   (row/column, `-reverse`), `flex-grow`/`flex-shrink`/`flex-basis`,
   `flex-wrap`, `justify-content`, `align-items`, coexisting with block
   layout so a flex container can hold block children and vice versa.
5. **[stretch] Interactive box-model inspector** — a generated single-file
   HTML page (Canvas + vanilla JS, no framework) that loads the exported
   `layout.json`, renders the page's boxes, and on hover/click shows the
   real margin/border/padding/content box breakdown for that node, the way
   a browser's DevTools "Computed" panel does.
6. **[stretch] Chromium differential oracle** — a `compare` CLI command
   that opens the same HTML+CSS in headless Chromium via Playwright,
   extracts every element's real `getBoundingClientRect()`, and reports a
   per-element geometry diff against Casement's own computed boxes —
   external ground truth, not just self-consistency.
7. Positioned layout: `position: relative/absolute` with a real
   containing-block search and `z-index` paint ordering (bonus beyond the
   4+2 minimum if time allows).

## Honesty note on scope

Text is rendered with a hand-authored monospace bitmap font, not vector
font outlines — real glyph rasterization (actual pixels shaped like the
letters), but fixed-width. Because of that, the Chromium oracle diff (#6)
is restricted to elements whose geometry doesn't depend on text-width
(explicit `width`/`height`, or flex containers sized by their non-text
children) — comparing pixel-for-pixel text metrics against whatever font
Chromium substitutes for `monospace` on this machine would be comparing
Casement against an arbitrary, environment-dependent font rather than
against the CSS spec. Text line-breaking itself is verified by Casement's
own unit tests against hand-computed expected wrap points, not the
Chromium oracle. This restriction is decided up front, here, not
discovered as a convenient excuse during review.

`border-style` is parsed to its full CSS3 keyword set (`solid`/`dashed`/
`dotted`/`double`/`none`) for layout purposes (any non-`none` value gets a
border box at all, matching real browsers), but the rasterizer paints every
non-`none` border as a solid line -- dash/dot patterns are a paint-time
detail, not a layout one, and were traded for time spent on the box model
and flexbox algorithms themselves.

Every stage (box-tree building, layout, painting) recurses by DOM depth
rather than using an explicit stack, so a page nested many hundreds of
elements deep hits Python's own recursion limit. The CLI catches this and
reports a clean "too deeply nested" error instead of a raw traceback, but
it does not lift the limit — real-world HTML is essentially never nested
this deep, so an iterative rewrite wasn't worth trading for engine clarity.
