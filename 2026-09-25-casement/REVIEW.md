# Phase 3 — Adversarial Review

Method: attack the engine as a hostile reviewer rather than trust "the demo
looked fine." Concretely: (1) re-derive the coordinate math by hand and
check every call site against it, (2) render real, visually-inspectable
pages (not just assert on numbers) and look for anything that reads wrong,
(3) throw a battery of edge-case HTML/CSS at the pipeline (empty input,
malformed CSS, extreme nesting, unicode, negative margins, zero-width
containers) and check for crashes *and* silently-wrong output, (4) exercise
the CLI's failure paths, not just its happy path.

This pass was run continuously while building the layout/flex engine (not
bolted on at the end), because several of the worst bugs below are exactly
the kind that "it renders something and doesn't crash" hides. All were
fixed before Phase 4.

## Issues found and fixed

1. **CRITICAL — a box's own children were laid out before the box's final
   position was known.** The original `layout_children_in_flow` read
   `child.dims.y` as the "content top" *before* the caller had set it,
   because the code set `child.dims.y` only *after* calling `layout_box`
   on the child. Any nested content (a `<div>` inside a flex item inside a
   `<div>`, for example) was positioned relative to `(0, 0)` instead of its
   real parent origin. Caught by writing
   `test_nested_content_inside_flex_item_positions_correctly` before trusting
   the flex implementation, not by inspection. Fixed by restructuring block
   flow into "resolve this child's box model, compute its final origin,
   *then* recurse into it" — the coordinate-model contract now documented
   at the top of `layout.py`.

2. **CRITICAL — flex items ignored their own computed main size whenever
   they had an explicit CSS `width`/`height`.** The flex algorithm computed
   a grow/shrink-adjusted main size per item, then tried to hand it to the
   item by setting `ContainingBlock(width=fm)` and calling the ordinary
   `layout_box` — which for a box with its own explicit `width` just uses
   that width and ignores the containing block's width entirely (correct
   for *normal* block layout, wrong here). A `flex-shrink` test
   (`.item { width: 150px; flex-shrink: 1 }` in a 200px row) produced a
   total of 300px instead of 200px — the shrink computation ran, but its
   answer was silently discarded. Fixed by adding an explicit
   `forced_width`/`forced_height` override to `layout_block`/`layout_flex`
   that flex always uses instead of letting the item's own style win.

3. **CRITICAL — max-content width measurement was structurally wrong for
   block containers.** `measure_preferred_width` (used for `flex-basis:
   auto` + `width: auto` items, and for `inline-block`/absolute
   shrink-to-fit) tried to measure a box's natural width by laying it out
   at an enormous containing width and reading back the result — but a
   block box with `width: auto` *fills whatever width it's given* by
   definition, so this just measured the enormous width back, not the
   content's real size. `flex-grow` proportions on two auto-width text
   items came out as `392 / 392` (exactly half each) instead of anything
   related to their actual short text. Fixed by replacing the
   lay-out-and-measure trick with a direct recursive computation: an
   explicit `width` wins outright, otherwise a block's preferred width is
   the widest child it needs (children stack), a flex row's is the sum of
   its items' (they sit side by side).

4. **HIGH — flex-item horizontal margins were zero during every sizing/
   wrap/justify computation, only becoming correct afterward.**
   `_resolve_edges` *returns* left/right margin rather than assigning it
   (block layout needs to decide separately whether `auto` means
   centering), and the flex algorithm's setup loop called it and discarded
   the return value, so `item.dims.margin.left/right` stayed `0.0` through
   every basis/wrap/justify calculation and only got their real value once
   the final per-item `layout_block` call ran. A row of 3 items each with
   `margin: 5px; padding: 10px; border: 1px` inside a 684px container
   overflowed to 706px because the wrap decision (and the free-space
   distributed by `flex-grow`) never accounted for the missing margin.
   Found by rendering `examples/showcase.html` and noticing the third card
   visually touched the page edge instead of leaving a margin, then
   confirmed numerically. Fixed by assigning `margin.left`/`.right`
   immediately in that setup loop.

5. **HIGH — the same wrap/justify math undercounted border and padding,
   not just margin.** Even after fix #4, `outer_main_margin` (the
   function feeding the wrap-line-splitting and free-space distribution)
   only added margin, not border or padding, to an item's basis when
   deciding whether it fits on a line or how much extra space is left —
   so a bordered/padded flex row's wrap point and item positions were
   computed from a smaller "footprint" than the items actually occupy,
   letting the last item on a line overflow past the container instead of
   wrapping. Fixed by making the function (renamed `outer_main_extra` to
   describe what it now measures) sum margin + border + padding on both
   main-axis sides, and by fixing the position/advance formulas
   (`final_x`/`final_y` and the `pos +=` step) to add all three edges, not
   just margin — they had the identical gap.

6. **MEDIUM — text within a single multi-word text node rendered with no
   spaces at all** (`"Hello Casement"` painted as `"HELLOCASEMENT"`). The
   inline-flattening code inserted a space token between two *text nodes*
   (handling the boundary correctly) but never between two words produced
   by splitting the *same* text node's content, since `str.split()` already
   discards the whitespace that would have signaled where to put it back.
   Caught immediately by rendering the very first test page — a paragraph
   of running prose came out as one glued-together word per line. Fixed by
   inserting a space before every word after the first one from a given
   text node's split, in addition to the existing inter-node boundary
   logic.

7. **MEDIUM — `position: absolute` with no positioned ancestor resolved
   against `<body>`'s content box instead of the true viewport.** Every
   absolutely-positioned box was attached to its *immediate* DOM parent's
   `absolute_children` list regardless of whether that parent was actually
   positioned, so `top: 5px; left: 5px` with no `position: relative`
   anywhere above it landed at `(13, 13)` (offset by `<body>`'s default
   8px margin) instead of `(5, 5)`. Fixed by threading a
   `positioned_ancestor_box` reference through box-tree construction so
   each absolute box registers with its real nearest positioned ancestor
   (or a dedicated root-level list resolved against the viewport rectangle
   directly) at build time, rather than always assuming the immediate
   parent.

8. **MEDIUM — `position: relative`'s offset leaked into sibling flow
   positioning.** The offset was applied to a child immediately after
   laying it out, but *before* the parent used that child's (now-shifted)
   bottom edge to position the next sibling — so a `top: 20px` relative
   offset also pushed every following sibling down by 20px, which
   `position: relative` must never do (it's supposed to be purely visual).
   Fixed by moving the offset application to strictly after the flow
   bookkeeping (`flow_y`/`prev_margin_bottom`) that following siblings
   depend on.

9. **LOW — the `background` CSS shorthand did nothing.** Only
   `background-color` was recognized as a real property; `background: #9cf`
   (a very common way to set a color) matched no case in
   `expand_shorthands` and was silently dropped, so
   `examples/showcase.html`'s two-column percentage-width demo rendered
   with no visible color at all where one was clearly intended. Fixed by
   adding a `background` case that extracts the first color-shaped token
   (hex/`rgb()`/named color/`transparent`) as `background-color`; other
   `background-*` sub-properties (image, position, repeat) remain
   unsupported and are silently ignored rather than causing an error, since
   Casement never claimed to support background images.

10. **LOW — the CLI printed a raw Python traceback for ordinary bad input**
    (a missing input file, `--width 0` or negative). Fixed with a
    `CasementCLIError` for clean, single-line, non-zero-exit-code errors,
    and a `RecursionError` handler (see the deep-nesting scope note added
    to `PLAN.md`) that reports the actual limitation instead of dumping a
    1000-frame traceback.

## Verified, not just assumed

- Re-rendered `examples/showcase.html` after every fix above (not just
  re-run the unit suite) and visually confirmed: the flex grid wraps
  correctly and no card touches the page edge, the percentage-width halves
  are colored, the z-index stacking test (two overlapping absolutely
  positioned boxes) paints the higher `z-index` box on top, text-align
  `left`/`center`/`right` all read correctly, and a 60-character
  unbroken word overflows its 120px container without being hyphenated
  (documented default behavior, not a bug).
- Threw 19 deliberately adversarial HTML/CSS snippets at the pipeline
  (empty document, no `<html>`/`<body>` at all, 200 levels of nesting,
  a 300-character unbroken word, `width: 0`, negative margins, malformed
  CSS declarations, `<table>` markup Casement doesn't specially support,
  a comment-only document, unicode text, `box-sizing: border-box` with
  padding larger than the specified width) — all render without crashing;
  see `tests/test_edge_cases.py`.
- Confirmed the negative-margin and negative-collapsed-margin cases that
  looked alarming during manual testing (a box's content growing *wider*
  than its containing block, a following sibling rendering with a small
  negative offset) are *correct* CSS behavior for negative margins, not
  bugs — verified against the CSS2.1 margin-collapsing algorithm by hand
  rather than assumed innocent.

## Phase 4 addendum — what the Chromium oracle found

Building stretch feature #6 (`casement compare`, a real headless-Chromium
differential oracle) immediately paid for itself: pointed at
`examples/oracle_test.html` (a page of explicitly-sized boxes, chosen so
font-metric differences can't confound the comparison), it found three
more real bugs that 93 passing unit tests had missed, because every one of
them is invisible unless something *external* checks Casement's numbers
against an independent implementation of the same spec:

11. **CRITICAL — the cascade's own author-vs-user-agent ordering was
    broken.** `compute_styles` merges the UA stylesheet's rules with the
    page's own rules into one list for cascade sorting, computing
    `base_order = len(all_rules)` to offset the author rules' `.order`
    values above the UA ones -- and then never used it. Since each
    stylesheet is parsed independently (each starting its own rule
    ordering at 0), an author rule could carry a *lower* order number than
    a same-specificity UA rule appearing later in the UA sheet, so
    "later-wins" ties were sometimes decided in the UA stylesheet's favor
    instead of the author's. Concretely: `body { margin: 0; }`, a
    one-line reset every real stylesheet has, silently lost to the UA
    sheet's `body { margin: 8px; }` and rendered with the default margin
    anyway. First surfaced as a uniform, unexplained position offset
    across *every* element the oracle compared; the fix is one line
    (`r.order += base_order`).

12. **CRITICAL — the exact same "resolve, then discard the answer"
    bug as flex issue #4, in plain block flow.** `_resolve_edges` returns
    left/right margin rather than assigning it (block layout decides
    separately whether `auto` means centering); `layout_children_in_flow`
    called it and discarded the result before using `child.dims.margin.left`
    (still its `Dimensions()` default of `0.0`) to compute the child's `x`.
    Any block-level element with a non-auto, non-zero `margin-left` (or
    asymmetric `margin` shorthand) was positioned as if that margin were
    zero -- its `dims.margin.left` was still *reported* correctly (assigned
    for real a few lines later, inside `layout_block`), which is exactly
    why the existing test suite missed it: every margin test checked the
    final margin *value*, never the resulting `x` position it was supposed
    to produce. `margin-left: 50px` on an 800px-viewport page positioned
    the element at `x=8` (just the body margin) instead of `x=58`. Fixed
    the same way as #4: assign the provisional margin immediately. The
    `auto`-margin (centering) case needed the same placeholder-then-
    `translate_box_tree` pattern flex already uses, since the real value
    isn't known until `layout_block` resolves the child's width.

13. **MEDIUM — `box-sizing: border-box` was applied to `width` but not
    `height`.** An explicit `height` with `box-sizing: border-box` should
    have padding/border subtracted from it to get the content height,
    exactly like width already does two lines above it in the same
    function -- the height branch just never had the equivalent
    subtraction written. A 200×~54px nested bordered/padded box rendered
    70px tall instead of 54, an exact +16px error traced straight to the
    unadjusted 30px `height` on its `box-sizing: border-box` child eating
    its own padding and border on top of, rather than out of, that 30px.

## Verified against a genuine external oracle

After fixes #11-13, `casement compare examples/oracle_test.html` -- a page
of explicitly-sized boxes covering the box model, flexbox (row/wrap/
justify/align), percentage widths, `position: absolute`, and
`box-sizing: border-box` -- agrees with real headless Chromium exactly
(0.0px diff) on 14 of 17 compared elements, with the remaining 3 all
showing the same understood, disclosed ~3px inline-block baseline-strut
difference (see PLAN.md) and nothing else. This is meaningfully stronger
evidence than the unit suite alone: it's agreement with an independent
implementation of the CSS box model and flexbox algorithm, not just
self-consistency with Casement's own assumptions.

## Deliberately not fixed here (see PLAN.md's honesty note for the "why")

- Bottom/last-child margin collapsing and empty-block self-collapsing.
- Multi-level parent/first-child margin collapsing (only one level).
- `border-style` beyond a binary none/solid at paint time.
- The recursion-depth ceiling on extremely deep DOM trees (~800+ levels).
