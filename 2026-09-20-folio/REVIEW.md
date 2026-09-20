# Phase 3 — Adversarial review

(Findings 8-9 were caught during Phase 4's float-layout stretch feature
work, not the original Phase 3 pass — logged here rather than left out,
since this file is meant to be the project's honest bug log, not a record
of exactly which phase happened to be running when a bug was found.)

Methodology: instead of only re-reading the code, every finding below was
reproduced by actually running the pipeline (`folio.engine.render_html`)
against a hostile or unusual input and inspecting either the raised
exception, the resulting layout-tree geometry, or the rendered PNG — the
same "watch a real run, don't trust that it didn't throw" standard past
builds in this repo (e.g. Beacon, 2026-09-02) have used.

## Findings and fixes

### 1. CRITICAL — tokenizer infinite loop on a malformed `<...>` sequence

`tokenize()` fell through to a "plain text run up to the next `<`" branch
whenever a `<` wasn't the start of a comment, doctype, start tag, or end
tag (e.g. `<3d>`, `< span>`, a lone trailing `<`). That branch searched for
the *next* `<` starting at the current position — which is the very `<`
already sitting at `i`, since it was never consumed. `next_lt` came back
equal to `i`, the emitted text was `""`, and `i` never advanced: the
generator looped on the same offset forever.

Reproduced: `parse_html('<div>hi <3d> there</div>')` hung indefinitely
(confirmed by running it under a 3-second `timeout`, exit code 124).
This is a real security/robustness concern beyond just a wrong render — a
single malformed tag anywhere in an input HTML file wedges the whole
process with no error, no output, and no way to recover.

Fix: when a `<` doesn't match any of the tag/comment/doctype shapes above,
emit it as one literal text character and advance `i` by exactly 1 before
falling back to the normal text-scanning branch, guaranteeing forward
progress every iteration. Verified the same input now parses instantly and
produces a reasonable (if not byte-perfect) DOM: the stray `<` becomes
literal text, exactly like a real browser's tokenizer would do with an
unrecognized `<`.

### 2. CRITICAL — multi-root HTML fragments silently dropped all but the first element

`layout_document()` picked "the html element" by grabbing the *first*
top-level `Element` child of `Document`, with no check that it was
actually `<html>`. Real-world test snippets very often skip the
`<html>`/`<body>` boilerplate entirely (`<div>...</div><div>...</div>`),
which is common enough that Folio's own examples/tests were going to hit
it. With no `<html>` wrapper, every top-level element *after* the first was
silently never laid out, never painted, and never visible in the output —
with no error of any kind.

Reproduced: `render_html('<div>First root div</div><div>Second root div should not be dropped</div>')`
rendered a page exactly one line tall, containing only "First root div".

Fix: `layout_document()` now specifically looks for a top-level element
whose tag is `html`. When none exists, it builds one synthetic block-level
root (a plain `ComputedStyle` with UA-initial values, `display: block`)
whose children are literally `document.children` — i.e. every top-level
node, not just the first — so multi-root fragments render in full. Added
`build_tree_node(node, styles, style=None)`'s optional `style` override to
support this without needing a synthetic node to already have an entry in
the `styles` map. Verified: the same two-`<div>` input now renders both
lines.

### 3. CRITICAL — `height: <percentage>` silently collapsed content to nothing

`parse_length()` resolved a percentage against `percent_base or 0` whenever
the base was `None` — and every call site that resolves a box's `height`
passes `containing_block_height=None` (this engine never threads a
definite ancestor height through layout, only width). So *any* percentage
height, e.g. `height: 50%`, resolved to a hard `0`, instead of the CSS2.1
§10.5-mandated behavior of falling back to `auto` when the containing
block's height is indefinite. The box's content still painted at its
*text-flow* position (paint has no clipping), but the box's own height
being 0 fed into the page's total computed height, so the generated PNG
canvas was sized too short and the real, lower content was cut clean off
the bottom of the image — a genuine, silent data-loss bug in the shipped
render, not just an internal number being slightly off.

Reproduced: a `<div style="height:50%">` containing three lines of text
rendered a 16px-tall canvas showing a sliver of the first line only.

Fix: `parse_length()` now returns the string `"auto"` (not `0`) when
asked to resolve a percentage against a `None` base, matching spec. Height
resolution already has an `if height == "auto": ...` fallback path that
computes height from the box's real laid-out content, so this one change
fixes it correctly rather than papering over the symptom. Verified: the
same input now renders all three lines and the canvas is exactly tall
enough to hold them (73px, not 16px). This is also documented as a stated
scope boundary in PLAN.md/README, since it means percentage heights behave
like `auto` universally in this engine (no two-pass "know my parent's real
height first" layout) rather than being silently wrong.

### 4. Real bug — over-constrained block margins double-counted the original margin-right

In `layout_block`'s explicit-width branch, when both `margin-left` and
`margin-right` were specified (not `auto`) and the box was over-constrained
(margins + border + padding + width doesn't exactly fill the containing
block), the code computed `used_right = remaining - used_left + used_right`
— which adds the *original* specified margin-right back in on top of the
correctly-solved value, silently making the box up to `used_right` pixels
too narrow (in practice, position too far right / total width too wide
for its containing block).

Reproduced numerically: containing block 380px, a 200px-wide box with
padding+border 7px per side and `margin: 8px` on all sides. Correct
over-constrained resolution (CSS2.1 §10.3.3: ignore the specified
margin-right and solve for it) gives `margin-right = 158px` (8 + 7 + 200 +
7 + 158 = 380, exactly filling the containing block). The buggy formula
produced `margin-right = 166px`, i.e. a box 8px too wide for its
container.

Fix: changed the over-constrained branch to `used_right = remaining -
used_left`, discarding the specified margin-right entirely, per spec.
Verified against the same numeric example (166 → 158, sums exactly to the
containing block width).

### 5. Minor — `currentColor` keyword matched by exact string equality

`ComputedStyle.resolved_color()` special-cased the literal strings
`"currentColor"` and `"currentcolor"` only. A stylesheet author writing
`border-color: CURRENTCOLOR` or any other casing would silently fail to
resolve to the element's `color`, instead being treated as an unrecognized
color value (falling back to black in `paint.parse_color`). CSS keywords
are case-insensitive.

Fix: compare `value.lower() == "currentcolor"` instead of two fixed-case
string literals.

### 6. Dead / misleading code removed

- `TreeBuildState`'s whitespace-skip check in `build_tree_node()` was
  written as `if <condition>: pass` immediately followed by an
  unconditional call to the exact function the `pass` branch looked like
  it was supposed to skip — so the condition had no effect at all (the
  whitespace-only-text filtering that actually matters happens later, in
  `TreeBuildState.finish()`). The dead conditional was removed; a comment
  now points at the real filtering logic instead of a comment implying
  work that wasn't happening.
- `_default_anon_style()` in `layout.py` was defined and never called
  anywhere (`grep` confirmed zero call sites). Removed.
- An unreachable `if idx >= n: break` immediately following an `idx += 1;
  continue` inside the same `while idx < n:` loop (the outer loop condition
  already re-checks `idx < n` before the body can run again, so this line
  could never execute). Removed.
- An unused `max_line_height` variable in `layout_inline_children` that was
  assigned every line iteration but never read. Removed.

### 7. Verified correct (not a bug) — negative margins can push content off-canvas

`<div style="margin: -9999px">` legitimately pulls the box far above/left
of its normal position, per real CSS semantics for negative margins — this
engine does not special-case or clamp negative margins, so an extreme
enough negative value pulls content outside the visible viewport, and the
page's auto-computed height is defensively clamped to a minimum of 0
rather than going negative. This matches how a real browser would treat
the same extreme, synthetic input (it is not a realistic page in the first
place), so no fix was made; documented as a scope note rather than "fixed"
so it isn't confused with the actual defects above.

### 8. CRITICAL — `margin-left` was computed but never actually used to position a box

Found while building the float stretch feature (a shared float context
needs boxes to actually be where their margins say they are). `layout_block`
resolved `box.margin["left"]` to a correct pixel value for every case
(explicit, auto-fill, auto-centered) but then set `box.x = x` — the
containing block's own content edge, completely ignoring the just-computed
margin-left. Vertical positioning threads each child's top margin through
the sibling-stacking cursor correctly; the horizontal equivalent was
simply never wired up. The result: **every block-level box with a nonzero
`margin-left` rendered flush against its container's left edge instead of
indented**, and `margin: 0 auto` centering — which computes a correct,
non-zero `margin-left` to center the box — silently had no visual effect
at all, always rendering flush left.

Reproduced two ways: `<div style="margin-left:50px; width:100px">` rendered
with its left edge at x=0, not x=50; `<div style="margin:0 auto;
width:100px">` in a 300px viewport rendered flush left instead of centered
(expected x=100 for a 100px box in a 300px container).

This is a significant finding precisely because it passed Phase 2's manual
smoke tests and Phase 3's adversarial review undetected: every example
tested through Phase 3 happened to use `margin: <n>px 0` (top/bottom only)
or symmetric margins on already-flush-left content, so the missing
horizontal offset was never visually exercised. It was only caught because
building float layout (stretch feature 5) required reasoning precisely
about absolute box edges, which made the discrepancy between "the margin
number is right" and "the box is in the right place" impossible to miss.
Logged here as a reminder that Phase 5's regression suite (below) needs to
specifically assert `box.x`, not just `box.margin["left"]`, for exactly
this reason.

Fix: `box.x = x + box.margin["left"]` (previously `box.x = x`), with a
comment explaining why horizontal margin needs this explicit application
where vertical margin gets it "for free" from the sibling cursor. Verified
both reproductions above now position correctly (x=50 and x=100
respectively).

### 9. CRITICAL — floats never affected any sibling's inline content, only their own

`layout_block` created a brand-new `FloatContext` at the top of *every*
single call, including for perfectly ordinary block boxes like `<p>`. Per
CSS2.1 9.4.1, an ordinary block does not establish a new block formatting
context (BFC) — it shares its ancestor's — which is exactly what makes a
floated image affect a paragraph of text several containers away. Because
this engine gave every block its own private float context, a float
placed as one sibling was invisible to any other sibling's own
`layout_block` call: floats only ever narrowed line boxes *inside the
same block* that contained them, never a sibling's.

Reproduced: two floats (`float:left`/`float:right`) followed by a sibling
`<p>` in the same `<body>` — instrumented `FloatContext.place()` and
`layout_inline_children()` with object-identity logging and confirmed the
`<p>`'s own `layout_block` call constructed a fresh, empty `FloatContext`
rather than reusing the one the two floats had just populated; the
paragraph's lines all reported the full container width, uninset by
either float.

Fix: `FloatContext` no longer stores fixed containing-block edges at
construction; `place()`/`available_range()` now take the caller's own
content-box edges as explicit arguments instead, so one shared instance
can correctly serve boxes of different widths/positions at different
nesting depths. `layout_block()` now takes `float_ctx` as a required
parameter — the *only* place a fresh `FloatContext()` is constructed is
`layout_document()`'s root call and `_layout_float_child()`'s `inner_ctx`
(a float genuinely does establish its own new BFC per spec, so its own
descendants correctly get an independent context that doesn't leak into,
or see, the page's ambient floats). Every ordinary block-to-block-child
`layout_block` call now threads the same ambient `float_ctx` through.
Verified with the two-float-plus-paragraph reproduction above: the
paragraph's first three lines (overlapping the floats' vertical span) now
correctly report `x=90, width=120` (exactly the gap between the two 80px
floats in a 280px content area), and subsequent lines below both floats'
bottom edge correctly report the full container width again.

## Verification after fixes

All four numbered examples above were re-run after their fixes and now
produce the expected geometry/output; the full example page
(`examples/basic.html`) and every other manual smoke test exercised
earlier in Phase 2 (percentages, `box-sizing: border-box`, malformed/
unclosed tags, nested inline styling, `<br>`, `text-align`, inline `<img>`
placeholders, deep nesting, an empty document) were re-rendered after all
fixes landed and show no regressions. A dedicated automated regression
test per finding above is added in Phase 5's test suite rather than left
as only a manual reproduction here.
