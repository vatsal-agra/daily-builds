# Casement

*Status: Phase 3 (adversarial review) complete — 10 real bugs found and
fixed, see `REVIEW.md`. Stretch features next.*

A from-scratch HTML/CSS layout and rendering engine in pure Python: a
hand-written HTML parser, a CSS parser + cascade engine, a block/inline +
flexbox layout engine, and a software rasterizer (with a hand-authored
bitmap font) that writes real PNGs. See `PLAN.md` for the full design,
feature list, and disclosed scope decisions.

## Quick start

```
python3 -m casement.cli render examples/showcase.html -o out.png --width 700
```

`examples/showcase.html` exercises the box model, flexbox (row/wrap/grow),
inline-block, percentage widths, `position: relative/absolute`, and text
wrapping in one page.

## What's built so far

- **HTML parser** (`casement/html_parser.py`): tokenizer + stack-based tree
  builder with real error recovery (auto-closing `<p>`/`<li>`, void
  elements, raw-text `<script>`/`<style>`, mismatched/stray end tags).
- **CSS parser + cascade** (`casement/css_parser.py`, `casement/selector.py`,
  `casement/style.py`): selectors (type/class/id/descendant/child/
  first-last-child), specificity, `!important`, inline styles, inheritance,
  shorthand expansion (`margin`/`padding`/`border`/`background`/`font`/
  `flex`).
- **Layout engine** (`casement/layout.py`): block formatting (auto-width
  fill, margin auto-centering, the two most common margin-collapsing
  cases), inline formatting (real greedy line-breaking/word-wrap), and a
  fully solved flexbox algorithm (grow/shrink/wrap/justify-content/
  align-items), plus `position: relative/absolute` with z-index paint
  ordering.
- **Paint + PNG** (`casement/paint.py`, `casement/font.py`,
  `casement/png_encoder.py`): a software rasterizer painting real pixels
  (backgrounds, borders, and an original hand-authored bitmap font), a
  from-scratch PNG chunk encoder.

93 unit tests pass (`python3 -m unittest discover -s tests`), covering the
parser's error-recovery rules, the cascade, layout geometry (not just "did
it crash" — exact pixel/box-position assertions), CLI error handling, and
a 19-case adversarial battery of hostile HTML/CSS input.

Full feature list, stretch features, and verification results land in
later phases of this build; see `PLAN.md` for design/scope and `REVIEW.md`
for what Phase 3's adversarial review found and fixed (10 real bugs,
several of them structural).
