# Cascade

A browser layout engine, built entirely from scratch: an HTML parser, a
CSS parser with the real cascade (specificity, inheritance, `!important`),
a layout engine implementing the actual box model plus block and inline
formatting contexts with margin collapsing, a flexbox subset, and a
from-scratch PNG rasterizer with a hand-rolled bitmap font. No browser, no
HTML/CSS parsing library, no imaging library anywhere in the pipeline —
the only place a real browser appears is as an independent *test oracle*,
confirming the engine's output is correct.

```
HTML text --tokenize--> tokens --parse--> DOM tree
CSS text  --tokenize--> tokens --parse--> rules (selectors + declarations)
                                              |
                            cascade: match selectors, resolve specificity/
                            !important/inheritance -> computed style/node
                                              |
                        layout: box model, block/inline formatting
                        contexts, margin collapsing, flexbox -> box tree
                                              |
                              +---------------+---------------+
                              v                               v
                     paint.py -> real PNG          viz.py -> interactive
                     (hand-rolled encoder +        HTML box inspector
                      bitmap-font rasterizer)       (click any box)
```

## Why this, today

Scanning this repo's history (see `LEDGER.md`) turns up SAT solvers,
GPT-style transformers, path tracers, chess engines, search engines,
compression codecs, version control systems, a JIT compiler, a CPU
simulator, a CRDT editor, a SLAM simulator, an exchange matching engine —
a genuinely wide spread of classical CS algorithms, graphics, and ML. What
it has never once touched is the parsing-and-layout pipeline that decides
how every web page you've ever looked at actually reaches your screen.
That gap, plus a rare asset sitting unused in this exact sandbox — a real
Playwright + Chromium install — made this an obvious pick: for once,
"is this correct?" doesn't have to mean "does it look plausible," it can
mean *"is it pixel-identical to the actual reference implementation of
the thing being rebuilt,"* the same differential-testing pattern this
repo has used against real `git`/`sqlite3`/`gcc`/NLTK, applied to a
domain that had never gotten it before.

## What it does

1. **HTML parser** (`html_tokenizer.py`, `html_parser.py`, `dom.py`) — a
   real tokenizer (tags, attributes, comments, entity decoding) and a
   tree-construction pass with the practical parts of the real HTML5
   algorithm: implicit `<html>/<head>/<body>`, void elements, auto-close
   rules (`<p>`, `<li>`, table rows/cells), and forgiving recovery from
   mismatched/unclosed tags.
2. **CSS parser + cascade** (`css_tokenizer.py`, `css_parser.py`,
   `selector.py`, `cascade.py`, `css_values.py`) — selectors covering
   type/class/id/universal/attribute/`:not()`/`:nth-child()`/descendant/
   child/adjacent-sibling combinators, real (a,b,c) specificity, source
   order, `!important`, property inheritance, shorthand expansion
   (`margin`, `border`, `flex`, `font`, ...), and a built-in user-agent
   stylesheet, resolving one computed style per DOM node.
3. **Layout engine** (`layout.py`, `flexbox.py`, `font.py`) — the CSS box
   model (content/padding/border/margin), a block formatting context
   (width resolution against the containing block including auto-margin
   centering, and adjoining-sibling margin collapsing), an inline
   formatting context (text flattened to word tokens, line-box wrapping,
   `<br>`, inline-block), list-item bullets, and a flexbox subset
   (row/column, `justify-content`, `align-items`,
   `flex-grow`/`flex-shrink`/`flex-basis`).
4. **Renderer** (`png_encoder.py`, `paint.py`) — a from-scratch PNG
   encoder (hand-written chunk framing + Sub filter over `zlib` DEFLATE,
   no PIL) rasterizing the box tree to real pixels: backgrounds, all four
   border edges independently, and text through a hand-rolled 5x7 bitmap
   font — a genuine `.png` any image viewer opens (confirmed by the
   system `file` utility, not just our own decoder).
5. **Flexbox** — see layout engine above; also independently verified
   against real Chromium (below).
6. **Chromium differential oracle** (`tools/oracle/measure.js` +
   `tests/test_diff_oracle.py`) — renders a battery of fixed-dimension
   pages in both Cascade and real headless Chromium (via Playwright),
   reads every probed element's true `getBoundingClientRect()`, and
   asserts Cascade's box geometry is pixel-identical. **12/12 pixel-exact**
   across box model math, margin collapsing, percentage resolution, and
   the full flexbox algorithm.
7. **Interactive box inspector** (`viz.py`, `cascade viz`) — a
   self-contained "DevTools-lite" HTML page: click any box to see its
   full box-model breakdown (margin/border/padding/content, to scale) and
   computed style, generated from one real Cascade layout run with zero
   client-side layout logic. Headless-Chromium-verified: zero console
   errors, click-to-inspect actually populates the panel
   (`tests/test_viz_ui.py`).

## How to run it

```
cd src
python3 cli.py render ../examples/cards.html --width 900 --out out.png     # -> real PNG
python3 cli.py layout ../examples/article.html --width 720                 # dump the box tree
python3 cli.py boxes-json ../examples/cards.html --width 900               # box geometry as JSON
python3 cli.py viz ../examples/cards.html --width 900 --out inspector.html # interactive inspector
python3 cli.py demo                                                        # render every example
```

Or run everything at once:

```
./demo.sh
```

15/15 checks green (exits 0), including — when the Chromium oracle is set
up — the 12-fixture pixel-diff and the headless UI smoke test:

```
cd tools/oracle && PLAYWRIGHT_SKIP_BROWSER_DOWNLOAD=1 npm install
```

(Chromium itself is already present in this environment at
`/opt/pw-browsers/chromium`; only the `playwright` npm package needs
installing. Without it, the two Chromium-backed test files skip
themselves cleanly rather than failing.)

## Tests

```
cd tests
python3 -m unittest discover -s . -p "test_*.py" -v
```

**153/153 tests green**: unit tests for every stage (tokenizers, parsers,
selector matching + specificity, cascade + inheritance, box model + margin
collapsing, inline wrapping, flexbox, PNG round-tripping), the Chromium
differential oracle, headless-browser UI tests for the inspector, and CLI
subprocess tests for error handling.

## Where a human could take this next

- **Real font metrics.** The bitmap font (uppercase-only, fixed
  advance-width) is honestly disclosed as an approximation — swapping in
  a real TrueType/OpenType parser (or even just accurate per-glyph
  advance-width tables) would make text layout and the differential
  oracle agree with Chromium on text-heavy pages too, not just
  fixed-dimension ones.
- **`@media` queries.** Currently every `@media` block is unconditionally
  inlined; evaluating the actual condition against a configurable
  viewport would make this a real (if basic) responsive layout engine.
- **CSS Grid.** The natural next layout mode after flexbox, and this
  engine's box-tree/cascade architecture would support it without a
  rewrite.
- **Parent/child margin collapsing and negative margins** — the two
  margin-collapsing cases this build deliberately scoped out (see
  `REVIEW.md`).
- **A real event loop for the inspector** — right now it's a static,
  precomputed page; wiring `cascade viz` up to a `watch` mode that
  re-lays-out on file change would turn it into a genuinely useful local
  dev tool.
- **`position: absolute/relative/fixed`** and `z-index` stacking contexts
  — layout currently only covers normal flow.
