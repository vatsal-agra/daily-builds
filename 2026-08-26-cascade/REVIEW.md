# Adversarial Review

Self-review of Cascade as a hostile reviewer: hunting for bugs, broken
edge cases, and lazy shortcuts. Every issue below was found, then fixed —
the fix commit for each is the same phase-3 commit this file lands in.
The regression for each is now a permanent test in `tests/`, or (for the
oracle-tooling and test-fixture issues) baked into `oracle/` /
`testpages/` itself.

## Real bugs found and fixed

1. **Bare-text / no-`<body>` documents rendered nothing.** `layout_document`
   required finding `<body>` or `<html>`, and its fallback
   (`walk_elements()[0]`) only laid out the *first* top-level element,
   silently dropping any siblings after it. `render_html("hello world")`
   produced an empty, zero-height SVG — no visible bug in any test page
   (all of which had a real `<body>`), only surfaced by deliberately
   throwing malformed/minimal input at the engine. **Fix:** `html_parser.
   _ensure_body()` now mirrors real HTML5 parsing — any document without
   a `<body>` gets one synthesized around its actual content (with `<head>`
   kept outside it), so loose text and multiple top-level tags both work.
   Regression: `test_html_parser.py::test_bare_text_gets_implicit_body`,
   `test_multiple_top_level_tags_get_wrapped`.

2. **CSS type selectors were case-sensitive against already-lowercased
   HTML tags.** `DIV { color: red }` never matched a real `<div>`/`<DIV>`
   element because the selector's `type` field kept the CSS token's
   original case while `Element.tag` is always lowercased by the HTML
   parser. Real HTML tag matching is ASCII-case-insensitive.
   **Fix:** lowercase a type selector's token at parse time (classes/IDs
   correctly stay case-sensitive). Regression:
   `test_css_parser.py::test_type_selector_is_case_insensitive`.

3. **`parse_color("#zzz")` crashed the whole render.** The 3-digit hex
   branch (`#abc`) had no `try/except` around its `int(..., 16)` calls,
   unlike the 6-digit branch — any malformed 3-character hex color in
   *any* stylesheet took down the entire pipeline with an uncaught
   `ValueError`. **Fix:** wrap both hex-length branches in one
   `try/except`. Regression: `test_cascade.py::test_malformed_colors_never_raise`,
   `test_layout_paint.py::test_no_crash_on_extreme_inputs`.

4. **`box-sizing: border-box` was ignored for `height`.** Width correctly
   subtracted padding/border for `border-box` sizing; the height branch
   just assigned the raw `height` value as content height regardless of
   `box-sizing`, so a `border-box` element with padding was taller than
   specified. Caught by the Chromium oracle (`01_box_model.html`, `#box-b`
   was 76px tall instead of 50px). **Fix:** apply the same border-box
   subtraction to height. Regression:
   `test_layout_paint.py::test_box_sizing_border_box_width_and_height`.

5. **Whitespace-only text between block siblings silently blocked margin
   collapsing — i.e. it broke on almost all realistically-formatted HTML.**
   Any indentation/newline between two sibling `<div>`s (completely normal
   hand-written markup) becomes its own "inline run" during box-tree
   construction. The code unconditionally flushed the pending
   margin-collapse state for *every* inline run, including ones that
   tokenize to zero words — so a real block's bottom margin got fully
   "spent" advancing the flow cursor before the next block's top margin
   was even considered, doubling the gap instead of collapsing it (32px
   instead of the correct 16px in a 16px+16px case). This is the single
   most consequential bug found: it would have silently broken margin
   collapsing — one of only two required block-layout algorithms — for
   nearly every real document, while every hand-crafted single-line test
   HTML I'd been using to sanity-check happened not to trigger it.
   **Fix:** lay out the inline run speculatively first; only if it
   actually produces content does it count as a real box that flushes/
   resets the collapsing state. An empty run is now treated as absent
   from the tree, exactly like a real browser treats collapsible
   whitespace. Regression:
   `test_layout_paint.py::test_block_stacking_and_margin_collapsing`
   (written with real multi-line, indented HTML specifically so it can't
   regress silently again).

6. **The oracle's own tolerance formula could mask exactly that kind of
   bug.** `tol()` scaled every field's (x/y/width/height) tolerance off
   `max(width, height)` — so a wide-but-short element (e.g. a 790×40px
   div) got a >100px tolerance on its *y-position* purely because it was
   wide, even though y-position only relates to height. That's how bug #5
   above passed the differential suite on its first run despite the two
   sibling divs it affected being 16px apart when they should have been
   collapsed. **Fix:** scale each field's tolerance to the
   dimension it actually varies along (x/width → element width, y/height
   → element height).

7. **Font-metric calibration was corrupted by an unrelated Chromium
   quirk.** While calibrating `MONOSPACE_ADVANCE` against the oracle, an
   early measurement (`testpages/05_inline_block.html`, no explicit
   `font-size`) implied a real advance of ~0.49em — but Chromium applies
   its own separate "fixed-width font size" UI preference (default 13px)
   to monospace text with no explicit size, instead of the standard 16px
   default every other generic family gets. Dividing the measured pixel
   width by the *assumed* 16px silently baked a wrong ratio into the
   metrics table, which then caused a genuine extra/missing line-wrap
   in `04_floats.html`'s paragraph relative to Chromium. **Fix:** pinned
   explicit `font-size: 16px` in both test pages, re-measured
   (~0.602em, close to the original un-"corrected" guess of 0.62), and
   documented why the measurement has to fix font-size explicitly to be
   meaningful at all.

8. **CLI gave a raw Python traceback for a missing/invalid file.**
   `cascade render missing.html` dumped a full `FileNotFoundError`
   stack trace instead of a one-line error. **Fix:** catch
   `FileNotFoundError`/`IsADirectoryError` in `main()` and print a clean
   `cascade: <message>` to stderr with exit code 1.

## Dead/confusing code cleaned up during development (not left in)

- `css_parser.py`'s `border-width`/`border-style` shorthand expansion had
  an unreachable `... if False else ...` ternary and a no-op loop left
  over from an earlier draft — replaced with one clean
  `_expand_border_component()` helper shared by all three shorthands.
- At-rule (`@media`, `@import`, ...) skipping checked for a literal `"@"`
  token that the tokenizer's regex could never actually produce (`@` fell
  through every character class silently) — the dead checks were replaced
  with one working path once `@` was added to the tokenizer's punctuation
  class.
- An early version of `_tokenize_inline` built a throwaway dummy class
  per top-level Text node to reuse the recursive walker; replaced with a
  single lightweight `_Wrapper` used once.

## Deliberate, documented scope cuts (not bugs — verified as expected,
   not silently wrong)

These are called out in `PLAN.md` and in `cascade/layout.py`'s module
docstring, and the Chromium oracle's test-page choices work around them
specifically so the *implemented* algorithms get tested cleanly rather
than being masked by an unimplemented one:

- **Parent/first-child margin collapsing** (a child's margin-top/bottom
  collapsing *through* an auto-height, border/padding-less parent) is not
  implemented — only sibling-sibling collapsing is. Confirmed via the
  oracle (`testpages/02_margin_collapsing.html` wraps its test divs in a
  1px-bordered container specifically so this doesn't confound the
  sibling-collapsing check it's actually testing).
- **Floats** are only supported as direct block-level children, not
  floated elements embedded mid-paragraph inside inline content.
- **`inline-block`/float shrink-to-fit** measures only the element's own
  flattened inline *text* content (see `_measure_natural_inline_width`);
  an inline-block containing block-level children with no explicit width
  still falls back to filling the remaining containing-block width.
- **Sibling combinators** (`+`, `~`) are outside the supported selector
  grammar; a selector using one is dropped (contributes no rules) rather
  than silently mismatching.
- **Inline-element padding is drawn but not reserved** in line-breaking
  width — a `<span>` with `padding: 0 8px` gets its padding box painted
  correctly, but the extra 8px isn't subtracted from the available line
  width, so it can cosmetically nudge adjacent text.

## Gate check

After all fixes above: `python3 -m unittest discover -s tests` — 60/60
pass. `python3 oracle/run_diff.py testpages` — 7/7 pages, 0 mismatches
against real Chromium, with the corrected (non-masking) tolerance
formula. See `PHASE5` verification output in the README for the final
numbers after stretch features were added.
