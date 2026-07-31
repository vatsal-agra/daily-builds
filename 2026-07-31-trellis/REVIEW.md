# Adversarial review

Methodology: attacked the engine (parser/evaluator/dependency graph/CSV) with
a battery of ad-hoc edge-case scripts, attacked the server's HTTP API with
`curl` (malformed JSON, out-of-range coordinates, missing fields, path
traversal), and attacked the browser UI by actually driving it in headless
Chromium (Playwright) — clicking, typing, undoing, charting — rather than
just reading the JS and assuming it worked. Every finding below was
reproduced with a concrete script/repro before being fixed, and re-verified
after.

## Findings and fixes

### 1. CRITICAL (UI): first keystroke of a new cell entry silently duplicated

**Repro:** click an empty cell, type `=A1*10`, press Enter → the cell showed
`#VALUE!` instead of the correct result.

**Root cause:** the very first character typed is handled by a
document-level keydown listener that synchronously creates and focuses a new
per-cell `<input>`. Because that keydown's default action wasn't prevented,
the browser's normal "insert this character" behavior still fired afterward
— against whatever element ended up focused by then, i.e. the brand-new
input. The first character was inserted *twice* (`=A1*10` became
`==A1*10`), which fails to parse as a formula.

**Fix:** `web/index.html` — call `ev.preventDefault()` before creating the
inline editor for a printable-character keydown.

### 2. CRITICAL (UI): pressing Enter/Tab re-submitted the same edit a second time

**Repro:** instrumented the browser to count `POST /api/cell` calls; a
single Enter-to-commit sent **two** identical requests.

**Root cause:** the inline `<input>`'s own Enter/Tab handler committed the
edit and moved the selection, but never stopped the keydown event from
*also* bubbling up to the document-level grid-navigation handler. That
handler, seeing the same Enter/Tab keydown, opened a **second** editor on
the newly-selected cell — which stole focus and blurred the first editor.
The first editor's `blur` handler then re-committed its (unchanged) value a
second time. This is what produced finding #1's `#VALUE!` symptom in one of
the two test runs, and would silently double-write history entries on every
single edit (see finding #3's interaction with undo).

**Fix:** `input.addEventListener("keydown", ...)` now calls
`ev.stopPropagation()` for Enter/Tab/Escape, so the document-level handler
never sees a keystroke the inline editor already handled.

### 3. CRITICAL (UI, data loss): clicking inside the cell being edited discarded the in-progress edit

**Repro:** double-click a cell to start editing, type text, click again
*inside that same cell* (e.g. to reposition the cursor) — the typed text
vanished and the cell reverted to its old (or blank) value.

**Root cause:** `selectCell()` flushed any in-progress edit by reading
`formulaInput.value` — the *top formula bar*, which is only synced to a
cell's content at selection time and is never updated while a separate
per-cell inline `<input>` is being typed into. A click landing inside the
cell being edited doesn't blur that inline input (clicking an
already-focused element just moves the caret), so it still reached
`selectCell`, which then "flushed" using the stale, usually-empty formula
bar value — silently discarding whatever had actually been typed.

**Fix:** replaced the `state.editing` boolean with an explicit
`editingCell`/`editingInput` pair that always points at the *live* inline
editor. `selectCell` now flushes from `editingInput.value` (not the formula
bar) and only when the target cell actually differs from the one being
edited; a click landing inside the cell currently being edited is a no-op
navigation-wise (the click handler returns early) so it doesn't touch
`selectCell` at all.

### 4. CRITICAL (engine): renaming a sheet broke every formula that referenced it

**Repro:** `Sheet1!A1 = Data!A1*2` (evaluates correctly) →
`workbook.rename_sheet("Data", "Source")` → `Sheet1!A1` becomes `#REF!`
permanently, even though `Source!A1` still exists with the right value.

**Root cause:** `rename_sheet` moved the `Sheet` object and patched the
dependency graph's *keys*, but never touched the formula ASTs themselves.
Every `CellRef`/`RangeRef` node stores the literal sheet name it was parsed
with (e.g. `sheet="Data"`); after the rename, `Data` no longer existed in
`workbook.sheets`, so evaluation correctly (but uselessly) raised `#REF!`
for a sheet that Trellis itself had just deleted out from under the
formula.

**Fix:** `rename_sheet` now walks every formula cell in the *entire*
workbook, rewrites any `CellRef`/`RangeRef` whose sheet qualifier matches
the old name (via a new `_rename_sheet_in_ast`), regenerates the cell's
displayed formula text from the patched AST (`_formula_text`, a small
AST-to-text unparser), and rebuilds the dependency graph from scratch
(`_rebuild_graph_from_formulas`) rather than trying to surgically patch
graph keys. `remove_sheet` was simplified to use the same rebuild helper —
formulas that referenced the now-gone sheet correctly become `#REF!`, which
*is* the right behavior there (the sheet is actually gone).

### 5. CRITICAL (engine, crash): deeply nested formulas crashed the whole recalculation with an unhandled `RecursionError`

**Repro:** `"=" + "("*500 + "1" + ")"*500` → uncaught `RecursionError`
propagating out of `Workbook.set_cell`, not a spreadsheet error value.
Also reproduced with a long unary chain and a long right-associative `^`
chain.

**Root cause:** the parser's parenthesized-group, function-call-argument,
repeated-unary, and right-associative-power productions all recurse with no
depth limit; nothing stood between "user-supplied formula text" and Python's
real call stack.

**Fix:** added an explicit, documented nesting-depth cap
(`parser.MAX_NEST_DEPTH = 60`) enforced by a `Parser._recurse()` wrapper
around every one of those four recursive re-entry points, raising a clean
`ParseError` (→ `#VALUE!`, same as any other malformed formula) with a
message naming the limit, instead of letting Python's interpreter crash the
request.

### 6. CRITICAL (engine, crash): a very long *flat* operator chain also crashed via `RecursionError`, past the parser

**Repro:** `"=" + "+".join(["1"] * 3000)` — parses fine (the `+`/`-`
grammar production is an iterative loop, not recursive), but building a
3000-deep left-leaning `BinOp` tree and then walking it — first in
`_extract_refs` (called synchronously inside `set_cell`, on every edit) and
again in the recursive-descent evaluator — blew the stack both times.

**Root cause:** finding #5's parser-side cap only bounds *nesting*
(parens/calls/unary/power); it can't bound a flat chain's *length*, and
that AST gets walked recursively in two separate places that had no
guard at all.

**Fix:** added `except RecursionError` backstops at both real recursive-walk
boundaries — reference extraction in `Workbook.set_cell` and formula
evaluation in `Workbook._recalculate` — converting to a clean `#VALUE!`
instead of crashing. This is intentionally a backstop, not a "fix" for the
formula itself: a real spreadsheet would reject something this long at
entry, and the actual right way to add 3000 numbers is `SUM()` over a
range, not a hand-written chain.

### 7. MEDIUM (UI, dark mode): chart images were nearly unreadable in dark mode

**Repro:** opened the chart panel with the browser's dark color scheme
emulated and screenshotted it — axis labels and gridlines were barely
visible against the panel's dark background.

**Root cause:** the SVG chart used `fill="currentColor"` and
`fill="var(--chart-bg,#fff)"`, written as if it would inherit the host
page's CSS custom properties and dark/light theming. But the chart is
embedded via `<img src="/api/chart?...">`, which renders the SVG in a
completely isolated context — `currentColor` and CSS variables from
`web/index.html` never reach in there at all. In practice `currentColor`
resolved to the SVG's own black default, invisible against a dark panel.

**Fix:** gave the chart its own explicit, fixed, always-legible palette
(white background, dark text, light gridlines, blue bars/lines) instead of
trying to inherit a theme it structurally cannot see. Verified via a real
headless-Chromium dark-mode screenshot.

### 8. LOW (robustness): server input gaps that would have leaked raw tracebacks

Found while attacking the HTTP API directly: creating a sheet named with a
literal `!` in it succeeded silently, even though such a sheet could never
actually be referenced from a formula (the parser reads `!` as the
sheet-qualifier delimiter, so `My!Sheet!A1` parses as sheet `My`, then fails
to find a valid cell address in `Sheet`). Also, no request handler had a
last-resort exception guard — any *future* bug in a handler would have
produced `http.server`'s default ugly failure mode (a dropped connection or
an unstyled traceback page) instead of a clean JSON error.

**Fix:** added `_validate_sheet_name` (rejects blank names and names
containing `!`, called from both `add_sheet` and `rename_sheet`, surfaced
by the server as a clean `400`), and wrapped `do_GET`/`do_POST` in a
catch-all that converts any unexpected exception into a clean `500` JSON
error instead of letting it escape to the client.

### 9. LOW (cleanliness): dead code

- `evaluator._compare` had `isinstance(x, TrellisError)` guards that can
  never actually trigger: every path that could hand it an error-valued
  cell (`Context.get_value` reading a `CellRef`) already `raise`s that error
  immediately instead of returning it as a plain value, so it always
  propagates *before* reaching `_compare`. Removed, with a comment
  explaining why the check isn't needed rather than silently deleting
  something that looked load-bearing.
- `functions.fn_vlookup` computed a `best` row inside its main loop for the
  approximate-match case and then never used it — the actual
  approximate-match logic was a completely separate pass after the loop.
  Rewrote as a single, clearer two-phase function (exact-match pass, then
  approximate fallback) with no dead assignment. Also fixed the *default*
  for the omitted 4th argument to be exact-match rather than mirroring real
  Excel's approximate-by-default (a well-known Excel footgun where an
  unsorted lookup column silently returns a wrong row) — documented as a
  deliberate deviation, not a bug.

## What was checked and found *not* to be a bug

- Lowercase cell references (`=a1+1`) parse and resolve correctly.
- A truly empty/never-set cell reads as `0` in arithmetic and as `""` in
  string concatenation, matching normal spreadsheet semantics.
- `TRUE`/`FALSE` literals coerce to `1`/`0` in arithmetic contexts.
- CSV import correctly round-trips quoted fields containing commas and
  embedded newlines (via Python's `csv` module, not hand-rolled splitting).
- `IF()` given a range reference as its condition produces a clean
  `#VALUE!` rather than crashing.
- `VLOOKUP` with no matching key returns `#N/A`, not a crash or a wrong
  value.
- A direct single-cell self-reference (`A1 = A1+1`) is caught by the same
  cycle detector as a multi-cell cycle and reported as `#CIRCULAR!`.
- Editing a cell that nothing else depends on triggers **zero** formula
  re-evaluations in a 500-cell sheet (verified via the `eval_count`
  instrumentation used throughout this review and in the test suite) —
  the incremental-recalculation claim in PLAN.md actually holds.
- The static-file server correctly rejects `../` path-traversal attempts
  (`/static/../../etc/passwd` → 404) including a double-slash variant meant
  to defeat a naive check.
- Malformed JSON bodies, missing fields, out-of-range row/col, and
  nonexistent-sheet requests all return clean 4xx JSON errors, not
  tracebacks.

All nine findings above were fixed and re-verified (engine-level findings
with ad-hoc repro scripts turned into regression tests in Phase 5; UI
findings by re-running the exact Playwright repro that first caught them).
