# Casement

*Status: Phase 4 (stretch features + polish) complete — both stretch
features shipped, and building the Chromium oracle found 3 more real bugs
(one of them a cascade-ordering bug affecting nearly every page). See
`REVIEW.md`. Verification (Phase 5) and final polish next.*

A from-scratch HTML/CSS layout and rendering engine in pure Python: a
hand-written HTML parser, a CSS parser + cascade engine, a block/inline +
flexbox layout engine, and a software rasterizer (with a hand-authored
bitmap font) that writes real PNGs. See `PLAN.md` for the full design,
feature list, and disclosed scope decisions.

## Quick start

```
python3 -m casement.cli render examples/showcase.html -o out.png --width 700
python3 -m casement.cli inspect examples/showcase.html -o inspector.html --width 700
python3 -m casement.cli compare examples/oracle_test.html --width 800 --tolerance 4
```

`examples/showcase.html` exercises the box model, flexbox (row/wrap/grow),
inline-block, percentage widths, `position: relative/absolute`, and text
wrapping in one page. `examples/oracle_test.html` is a second page,
deliberately built from explicitly-sized boxes only (no text-dependent
sizing), for meaningful comparison against a real browser.

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
- **Interactive box-model inspector** (`casement/inspector.py`, `casement
  inspect`): a self-contained HTML page (no build step, no dependencies)
  that shows the actual rendered page and, on hover, the real margin/
  border/padding/content breakdown for whichever box is under the cursor —
  a browser DevTools-style box-model diagram, but for Casement's own
  layout. Verified with zero console errors in headless Chromium.
- **Chromium differential oracle** (`casement/oracle.py`, `casement
  compare`): renders the same page in Casement and in real headless
  Chromium and diffs the computed border-box geometry of every element —
  genuine external ground truth, not just self-consistency with Casement's
  own assumptions. Building this immediately found 3 more real bugs (see
  `REVIEW.md`), including one that affected the position of nearly every
  element on nearly every page.

103 unit tests pass (`python3 -m unittest discover -s tests`), covering the
parser's error-recovery rules, the cascade, layout geometry (not just "did
it crash" — exact pixel/box-position assertions), CLI error handling, a
19-case adversarial battery of hostile HTML/CSS input, the inspector's
generated output, and (when Node + Playwright are available, as they are
in this environment) real headless-Chromium differential tests.

Full feature list and verification results land in the remaining phases
of this build; see `PLAN.md` for design/scope decisions and `REVIEW.md`
for what adversarial review found and fixed (13 real bugs across Phases 3
and 4, several of them structural).
