# Phase 3 — Adversarial Review

Attacking Cascade as a hostile reviewer: deliberately constructing inputs
designed to break each stage (percentages, currentcolor, `:not()`,
malformed/missing files, pathological nesting) rather than just re-running
the happy-path examples from Phase 2. For a complete and honest record,
this also includes bugs caught earlier than a strict phase boundary would
suggest: two caught by dogfooding the example renders during Phase 2
development itself (findings #3 and #5, fixed *before* the Phase 2 commit
— they never shipped broken, but they were real defects this build
produced and are recorded here rather than quietly left out), and two
caught the moment Phase 2's own unit tests were first run (finding #7).
Every item below is followed by its fix and, further down, by how it was
re-verified.

## Findings, worst first

### 1. CRITICAL — percentage `height` always resolved to 0px

**Repro:** `<div style="height:300px"><div style="height:50%"></div></div>`
— the inner div's `50%` should resolve to 150px. It measured **0px**,
every time, for every page, regardless of the parent's actual size.

**Root cause:** `layout_block_box` resolved `height: 50%` via
`height_len.resolve(0)` — a **hardcoded base of `0`** instead of the
containing block's actual content height. Worse, the containing block's
own height is normally only known *after* laying out its children (its
height is usually content-driven), so naively "just pass the real height"
isn't available at the point a child needs it — this is the real reason
the bug existed, not an oversight in a single line.

**Fix:** restructured the whole call chain (`build_root` →
`layout_block_box` → `layout_block_children_into` → `layout_inline_run` →
inline-block items) to thread a `cbh` (containing-block height) parameter:
each box resolves its *own* definite height (`_resolve_definite_height`)
*before* laying out its children, using the `cbh` it was handed by its
parent, and passes that resolved value down as `cbh` for its own children.
When a containing block's height is itself indefinite (auto), `cbh` is
`None` and a percentage height on a descendant correctly falls back to
`auto` (computed from content) instead of silently becoming 0 — this
matches the real CSS 2.1 §10.5 rule ("a percentage height against an
indefinite containing block computes to auto"), not just patching the one
symptom. `flexbox.py`'s row-cross-size / column-main-size also used the
same `resolve(0)` bug against the flex container's own `height`; fixed by
reusing the same already-resolved `cbh` value instead of re-deriving it.

Regression tests: `test_layout.py::RegressionTests.
test_percentage_height_resolves_against_definite_containing_block` and
`test_percentage_height_falls_back_to_auto_against_indefinite_container`.

### 2. `:not()` silently matched nothing, dropping the whole rule

**Repro:** `li:not(.special) { color: red; }` — every `li` (correctly)
should get red text except `.special` ones. Instead, **no** `li` did.

**Root cause:** `:not()` wasn't in `_match_pseudo`'s recognized list, so
it fell through to the safe-default `return False` used for genuinely
unknown/unsupported pseudo-classes — meaning any element with a `:not()`
in its selector could never match, silently dropping a real-world-common
selector pattern rather than erroring loudly.

**Fix:** implemented `:not(<compound selector>)` by parsing the argument
with the existing compound-selector parser and negating a normal
`_simple_matches` check. Selector-list/combinator arguments inside
`:not()` (e.g. `:not(div > p)`) are a documented, much rarer scope cut —
they now vacuously match (never exclude) rather than silently killing the
whole rule, which was the actual bug.

Regression tests: `test_css.py::MatchingTests.test_not_pseudo_class`,
`test_not_pseudo_with_nth_child_arg`.

### 3. `inline-block` with auto width filled the entire line instead of hugging its content

*(caught by dogfooding, before the Phase 2 commit — see the note above)*

**Repro:** a `<span style="display:inline-block">DONE</span>` "badge"
inside a 230px-wide card rendered as a bar stretching the full card width
instead of a small pill around the word "DONE" — visible immediately in
the Phase 2 `cards.html` example render.

**Root cause:** `_collect_inline_tokens` laid inline-block elements out
via the same `layout_block_box` used for ordinary block boxes, whose
auto-width behavior is "fill the containing block" — correct for a real
block box, wrong for `inline-block`, whose auto width should *shrink to
fit its content* (CSS's shrink-to-fit/fit-content algorithm).

**Fix:** for a text-only leaf inline-block with an auto width, override
the resolved width to an estimate of its own text-run width (the same
technique `flexbox.py` already used for its own fit-content items) before
laying it out, instead of letting it default to the full line width.
Nested-block inline-block content (rarer) still falls back to filling
available width, documented as a remaining scope cut.

Regression test: `test_layout.py::RegressionTests.
test_inline_block_auto_width_shrinks_to_fit_text_content`.

### 4. Border color's initial value was a hardcoded black instead of `currentcolor`

**Repro:** `<div style="color:blue; border:2px solid; ...">` — real CSS's
`border-color` initial value is `currentcolor` (the element's own text
color), so an unspecified border color should render **blue**. It
rendered black.

**Root cause:** `INITIAL_VALUES["border-*-color"]` was hardcoded to
`"#000000"` rather than the spec's actual initial value.

**Fix:** changed the initial value to the symbolic `"currentcolor"` and
resolved it in `layout.set_visual_props` against the box's own
already-computed `color`, once that's known — a real border with no
explicit color now correctly follows the text color, and an explicitly
set `border-color`/`border: ... <color>` still overrides it as before.

Regression tests: `test_layout.py::RegressionTests.
test_border_defaults_to_currentcolor_not_black`,
`test_explicit_border_color_still_overrides_currentcolor`.

### 5. List markers were invisible (no glyph for the bullet character)

*(also caught by dogfooding, before the Phase 2 commit)*

**Repro:** every `<li>` correctly got a `"• "` marker prepended by the
layout engine (verified structurally by a Phase 2 test) but the rendered
PNG showed **no dot at all** in front of list items — visible immediately
in the `article.html` example render.

**Root cause:** the hand-rolled bitmap font's glyph table had no entry for
`•`; `draw_text` silently skips drawing (but still advances the cursor)
for any character it has no glyph for, so the marker occupied space but
painted nothing.

**Fix:** added a bullet glyph (plus a few other missing common
punctuation: `; $ < >`) to `font.py`'s glyph table.

### 6. Missing/unreadable files and pathological input crashed with raw Python tracebacks

**Repro:** `cascade render no-such-file.html`, a non-UTF-8 HTML file, and
a synthetically generated 50,000-deep nested `<div>` chain all crashed
with a raw traceback (`FileNotFoundError`, `UnicodeDecodeError`, or
`RecursionError`) instead of a clean, actionable CLI error.

**Fix:** `cli.py` now validates the input path and decodes explicitly
inside `_read()`, raising a small `CascadeCLIError` the top-level `main()`
catches and reports as `cascade: error: ...` with exit code 1; `--width 0`
or negative is rejected the same way before any layout work starts; the
Python recursion limit is raised (to comfortably cover real, if deep,
markup) and `RecursionError` is caught with a clear message naming the
actual cause instead of a wall of frames.

Regression tests: new `tests/test_cli.py` (spawns the real CLI as a
subprocess and asserts on exit code + stderr, the same way a user would
hit these paths).

### 7. Two structural HTML-parser bugs (caught by Phase 2's own first test run)

Recorded here for a complete history, not because they survived to
Phase 3: (a) the parser's element-insertion stack started at `<body>`
instead of `<head>`, so every head-only element (`<title>`, `<style>`, …)
was misparented into `<body>`; (b) the auto-close logic for constructs
like `<tr><td>a<td>b<tr><td>c` only ever popped *one* level of the open-
element stack, so a new `<tr>` closed a dangling `<td>` but not the
previous `<tr>` itself, nesting rows instead of making them siblings.
Both were caught the moment `tests/test_html.py` was first run (2 of 25
tests failed) and fixed by (a) starting the stack at `<head>` and (b)
turning the single `if` into a `while` loop that keeps closing implied
elements until the top of the stack no longer triggers auto-close for the
incoming tag. Also caught the same way, in `flexbox.py`: an item's own
`margin-left`/`margin-right` was silently dropped from main-axis
positioning (`box.x` was overwritten by the flex algorithm without adding
the item's margin back in) — fixed by tracking "outer" (margin-inclusive)
main/cross sizes throughout the flex algorithm.

## What Phase 3 deliberately did NOT change

Documented scope cuts that are simplifications, not bugs, so they're
recorded here rather than "fixed": parent/child margin collapsing and
negative margins (only adjoining-sibling, non-negative margins collapse);
`@media` conditions are never evaluated (block contents are always
inlined); `calc()` and CSS custom properties aren't parsed (silently
treated as `auto`/unset rather than crashing); `flex-wrap` only supports
the spec default `nowrap`; combinator/selector-list arguments inside
`:not()`; a self-closing `/>` on a non-void HTML element is honored (real
browsers ignore it) instead of being ignored as the HTML5 spec requires;
and the bitmap font covers uppercase glyphs only (lowercase renders as its
uppercase form) since a full-weight bitmap type face with a genuine
lowercase alphabet was out of scope for a one-day build.

## Verification after fixes

- Full suite: **133/133 tests green** (121 from Phase 2 + 12 new
  regression tests covering every finding above), including the new
  `tests/test_cli.py` which drives the real CLI as a subprocess.
- All three Phase 2 example pages (`article.html`, `cards.html`,
  `boxmodel.html`) were re-rendered after every fix and visually inspected
  — the `cards.html` badge-stretching bug and `article.html`'s invisible
  bullets are both visibly fixed in the current renders under `renders/`.
- A fresh run-through targeting each of the 6 fixed issues above (not just
  the original repro) hits zero remaining instances of any of them.
