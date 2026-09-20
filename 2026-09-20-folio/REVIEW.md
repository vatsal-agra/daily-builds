# Phase 3 — Adversarial review

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
