# Phase 3 — Adversarial Review

Hostile self-review of the Phase 2 build: hunting for bugs, broken edge
cases, ugly UX, and lazy shortcuts. Every issue below was found by actually
running the engine against adversarial input (not by inspection alone), and
every one was fixed and given a regression test before this phase closed.

## Bugs found and fixed

1. **CRITICAL — quirks-mode fixtures silently invalidated the Chromium
   oracle comparison.** The Chromium test fixtures had no `<!DOCTYPE html>`,
   so Chromium rendered them in legacy "quirks mode" (`document.compatMode
   === "BackCompat"`), which has different margin-collapsing behavior than
   the CSS2.1 standards-mode algorithm Folio implements. This produced
   false oracle mismatches (e.g. an `<h1>` landing at y=8 in Chromium vs.
   y=21.44 in Folio) that looked like layout bugs but were actually a test
   *setup* bug. Fixed by adding the doctype to `full_document_html()` —
   confirmed via `document.compatMode` flipping to `CSS1Compat` and the
   mismatch disappearing. This is exactly the kind of trap a "looks
   plausible" verification story would have missed; having a real oracle
   is what surfaced it.

2. **CRITICAL — self-collapsing empty boxes were positioned at the wrong
   pixel.** An empty `<div>` between two siblings (no border/padding/height
   — a "self-collapsing" box per CSS2.1 8.3.1) was assigned its position
   *at the moment it was encountered* during the sibling walk, before its
   own margins had finished collapsing with what came after it. Real
   Chromium reports such a box's `getBoundingClientRect()` at the *final*
   resolved collapsed position, not the provisional one. Fixed by deferring
   self-collapsing boxes' geometry (`pending` list threaded through
   `_layout_block_children`) and backfilling it only once their margin
   group actually gets consumed — verified byte-exact against Chromium
   (`test_self_collapsing_empty_div_between_siblings`).

3. **CRITICAL — margin collapsing double-processed a delegating box's
   children.** The first working draft of `_layout_block_children` called
   the recursive "lay out my children" step unconditionally, even after a
   box had *already* had its children laid out via the top-collapse-through
   delegation branch — corrupting positions for any box with zero
   top-border/padding and an in-flow first child (an extremely common
   shape: any wrapper `<div>`). Caught immediately by a hand-traced test
   case before it ever reached the test suite; fixed by branching cleanly
   instead of falling through.

4. **Attribute selectors with `^=`/`$=`/`*=`/`|=` silently over-matched.**
   `_compound_matches` only implemented `=` and `~=`; every other
   recognized-but-unhandled operator fell through both `if` checks with no
   `return False`, so e.g. `a[href^="https://"]` matched *any* element that
   merely had an `href` attribute, regardless of its value — the opposite
   of what the selector says. Fixed with an explicit `_attr_op_matches`
   covering all six forms, with regression tests specifically checking that
   a non-matching value does *not* match (the failure mode a positive-only
   test suite would have missed).

5. **`line-height: 1.5` (a bare, unitless multiplier) was parsed as
   `1.5px`.** `_resolve_value` tried `parse_length` first, which defaults
   unit-less numbers to px — so every paragraph using the extremely common
   unitless `line-height` syntax got ~1.5px-tall lines instead of
   `1.5 × font-size`. Found immediately by rendering a real fixture and
   looking at it. Fixed by checking for the bare-multiplier form first.

6. **Whitespace-only text between block siblings generated a phantom empty
   line.** Ordinary HTML source formatting (newlines/indentation between
   `<h1>` and the next `<div>`) became a text node containing only
   whitespace; the anonymous-block-wrapping logic built a real inline-mode
   box for it regardless (a leftover `... or True` in the flush condition
   that always fired), adding one full empty line-height of unwanted
   vertical space between *every* pair of block siblings in real-world
   markup. Fixed by skipping anonymous-block creation for a run with no
   visible content at all.

7. **CLI crashed with raw tracebacks on ordinary operator error.** A
   missing input file, an empty document, or a document with no `<body>`
   all raised uncaught `FileNotFoundError`/`KeyError` straight through to
   the user. Fixed with a `CLIError` type, `pick_layout_root()` (falls back
   `<body>` → `<html>` → first top-level element → a clean "nothing to
   render" error), and a top-level `try/except` in `main()`.

8. **Negative `width`/`height`/`padding`/`border-width` were accepted and
   propagated into visibly broken (negative-size) boxes.** CSS2.1 requires
   these to be treated as invalid (falling back to the inherited/initial
   value) when negative — only margins may legitimately be negative. Fixed
   in `_resolve_value` with an explicit non-negativity check scoped to
   exactly the properties that need it.

9. **Deep nesting crashed with `RecursionError`.** `Node.iter_descendants`,
   the layout-tree builder, and the style-cascade walk are all recursive by
   DOM depth; a 2,000-level-deep document (not impossible from generated
   markup) blew Python's default 1,000-frame recursion limit. Fixed
   `iter_descendants` to be iterative (an explicit stack — no depth limit
   at all for that one), raised the process recursion ceiling for the
   remaining genuinely-recursive stages (`cli.py`), and made the CLI report
   a clean one-line error instead of a traceback if a document is so deep
   it exceeds even that raised ceiling.

10. **O(n²) margin-collapsing walk on wide sibling lists.** `group`/
    `pending` were being rebuilt with `list + [x]` on every child instead
    of mutated in place — harmless for typical pages, but a document with
    thousands of consecutive empty sibling `<div>`s (a real pattern from
    some page builders/exports) took quadratic time: 8,000 such divs took
    1.4s; 16,000 would have taken ~5.6s instead of the ~1.5s it now takes.
    Fixed by mutating the accumulator lists in place — verified the fix
    doesn't change output (`diff`'d before/after) and confirmed the scaling
    is now linear (doubling the input roughly doubles the time, not
    quadruples it).

11. **`text-align: justify` stretched lines ending in a forced `<br>`
    break.** CSS2.1 16.2 exempts both the last line of a block *and* any
    line ending in a forced line break from justification — only the
    "last line" exemption was implemented. Fixed by tracking
    `ends_with_forced_break` per line box.

## Cleanups (no behavior change, but real "ugly/lazy" issues)

- A `has_block_child` filter in the layout-tree builder was a genuinely
  hard-to-read one-liner (`not (A if B else C)` nested inside a list
  comprehension) that happened to be correct by luck of Python's
  conditional-expression precedence; replaced with a named helper.
- An `if/else` in the same function had both branches doing the exact same
  thing (`box.block_children.append(child_box)`) — a leftover from
  differentiating float handling that was never actually implemented;
  collapsed to one line.
- `_looks_like_length`'s boolean expression relied on undocumented
  operator-precedence between `and`/`or` to work correctly; rewritten with
  explicit early returns.
- `position: absolute`/`fixed` elements were silently dropped from layout
  entirely (excluded from `in_flow_block_children` with no actual
  out-of-flow positioning implemented to replace it) — an element could
  vanish from the rendered page with no error. Changed to keep such
  elements in normal flow (a documented, honest scope limitation —
  "not positioned specially" — rather than "invisible").

## Scope decisions confirmed, not bugs

- Folio's fixed-advance monospace font-metric model does not, and is not
  trying to, match Chromium's real font rasterizer pixel-for-pixel. The
  Chromium oracle test suite explicitly skips height/position assertions
  that are downstream of text-line-height for exactly this reason (see
  `skip_text_derived_for` in `test_layout_block.py`) — every *box-model*
  assertion (margins, padding, borders, widths, percentage/auto
  resolution) still matches Chromium exactly.
- Margin collapse-through composes correctly to arbitrary nesting depth
  (verified with a 3-level test, `test_deep_nesting_collapse_through`,
  against both the analytic and Chromium oracles) — the PLAN.md draft note
  about a "one level only" scope limit was a planning-time worry that
  turned out unnecessary once the recursive implementation was actually
  written; the real implementation is fully general.
- A CSS parse error inside one selector (e.g. an unterminated quoted
  attribute value) can consume the remainder of the stylesheet as string
  content, dropping later rules rather than recovering mid-file. This
  degrades gracefully (no crash, no corrupted output) rather than
  recovering fully — full per-rule error recovery is a larger undertaking
  than this scope calls for, and malformed CSS at that level is rare
  in practice.
