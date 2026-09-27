# Phase 3 — Adversarial Review

Methodology: (1) re-read every module hunting for logic errors, (2) write
and run fuzz/property tests that specifically try to break the
incremental-vs-full-recompute invariant across every mutating operation
(not just plain edits), (3) drive the *actual* browser UI with headless
Chromium rather than trusting that "the engine is correct so the UI must
be fine," (4) deliberately feed the engine pathological/adversarial input
(malformed formulas, off-grid references, absurd nesting) rather than only
the happy path.

## Real bugs found and fixed

1. **Comparison cross-type ordering was backwards.** `_type_rank` ranked
   text below numbers, so `="abc">5"` evaluated to `FALSE`. Real
   spreadsheets rank text *above* numbers (`blank < number < text <
   boolean`), so `"abc" > 5` is `TRUE` — any text outranks any number.
   Caught by a precedence test's assertion failing, not by inspection.
   Fixed in `evaluator.py`.

2. **Literal-cell edits were never reported as "changed."** `set_cells`
   (and `undo`/`redo`) took their pre-edit "before" snapshot *after*
   `_set_raw` had already mutated the cell — harmless for formula cells
   (which stay stale until the recompute pass actually runs), but a
   **silent no-op for literal cells**, whose value `_set_raw` installs
   immediately. The practical effect: editing a plain number/text cell
   (the single most common spreadsheet action) would compute correctly
   internally but the diff the HTTP API reports back to the browser would
   omit that very cell, so the grid would appear not to update at all
   until some *other* cell change happened to touch it. Fixed by capturing
   each directly-edited cell's true pre-mutation display value before
   calling `_set_raw`, in all three of `set_cells`, `undo`, and `redo`.

3. **A reference pushed off the grid round-tripped into the wrong error.**
   Copy/paste and fill translate a formula's AST and re-serialize it to
   text (so the formula bar shows real, editable text). When a reference
   shifted off the sheet edge, the old code emitted the literal text
   `#REF!` into that formula string — but the tokenizer had no rule for
   `#`-prefixed tokens at all, so re-parsing that text raised a
   `TokenizeError`, which `_set_raw` catches generically into `#ERROR!`
   instead of the correct, informative `#REF!`. Fixed by making error
   values (`#REF!`, `#DIV/0!`, `#VALUE!`, `#NAME?`, `#N/A`, `#NUM!`,
   `#CYCLE!`) real, re-parseable literals in the formula grammar itself —
   which is also authentic: real spreadsheets do accept typing `=#REF!+1`
   directly into a cell.

4. **A pathologically nested formula crashed the process.** `=` followed
   by 2000 `(` characters raised a raw Python `RecursionError` — unlike
   `TokenizeError`/`ParseError`, nothing catches that, so it would have
   taken down the request that triggered it (and, run in-process rather
   than in a worker, potentially the whole server). Root-caused to every
   parenthesized group or function argument recursing back through
   `parse_expr`; fixed with an explicit depth counter in the parser that
   raises a clean `ParseError` well before Python's own stack limit —
   verified by sweeping nesting depth from 30 to 5000 and confirming the
   exact threshold where it flips from evaluating correctly to a clean
   `#ERROR!`, with no crash anywhere in between. Because the guard acts
   at parse time, the resulting AST can never be deep enough for
   `evaluate`/`translate`/`to_formula` to hit the same wall later either.

5. **Malformed API requests crashed the connection instead of erroring
   cleanly.** `do_POST`/`do_GET` read expected JSON keys directly
   (`body["col"]`, `body["src"][0]`, ...); a missing key or wrong shape
   raised `KeyError`/`TypeError`/`IndexError` that `http.server`'s default
   handling doesn't turn into any HTTP response — the client just saw a
   broken connection. Fixed by wrapping dispatch in a try/except that
   returns a clean `400 {"error": ...}`.

6. **Real browser bug: the first character typed to start editing a cell
   was inserted twice.** Typing `=` while a cell was selected (not yet
   editing) called `startEdit(col, row, "=")`, which set `#cell-editor`'s
   value to `"="` and moved focus to it *synchronously inside the same
   keydown handler*, without calling `e.preventDefault()`. The same
   keydown event's native default action then fired *after* the handler
   returned, inserting `"="` a second time into the now-focused editor —
   so typing `=A1*3` produced the raw formula `==A1*3`, which failed to
   parse. Found only by driving a real headless browser end-to-end (typed
   a formula, then asserted the *computed* cell value); no engine-level
   test could have caught it, since the engine itself never saw anything
   wrong — from its point of view, someone genuinely typed `==A1*3`.

7. **Real browser bug, more serious: pressing Enter to commit an edit
   could silently clear a *different* cell shortly after.** `#cell-editor`
   is a DOM child of `#grid-wrapper` (needed for absolute positioning over
   the cell being edited), so its own Enter/Tab/Escape keydown handling —
   which calls `commitEdit()` — bubbles up into `#grid-wrapper`'s own
   keydown listener afterward. That listener guards on `if (editing)
   return`, which looks safe, but `commitEdit` is `async`: its
   synchronous first half (read `editing`, then set `editing = null`)
   completes *before* the bubbled event reaches the parent listener, so
   the guard sees `editing === null` and falls through, calling
   `startEdit()` again on the *same cell* with an empty value — a second,
   phantom edit session nobody asked for. That phantom session sat
   "open" (in the `editing` variable's eyes) until the next click
   anywhere else in the grid, whose `mousedown` handler saw `editing`
   truthy and dutifully auto-committed it — POSTing an empty raw value
   and silently **erasing the cell the user had just typed into**, one
   click later, with no visible cause. Reproduced exactly via captured
   network requests (`{"col":1,"row":1,"raw":""}` firing right after a
   click on an unrelated cell) — invisible to any test that doesn't
   watch real request traffic from a real browser. Fixed with
   `e.stopPropagation()` on the editor's Enter/Tab/Escape handling.

## Phase 4 addendum: one more real bug, found by actually typing a row

While polishing the UI, filling in a small sample table by typing several
cells in a row (`Item` Tab `Price` Enter, `Widget` Tab `9.99` Enter, ...)
at normal typing speed produced silently wrong data: a value typed as
`19.99` landed in the cell as `9.99` — the leading `1` vanished. Root
cause: `commitEdit` deferred moving the selection and refocusing
`#grid-wrapper` until *after* `await`ing the `/api/cell` response, with
the actual `selectCell()` call living in a `.then()` on the caller's side.
Between hiding the just-committed cell's editor and that response coming
back, **no element in the grid had focus at all**, so any keys typed in
that window (which a fast typist reliably enters, since Tab-then-type is
the normal way to fill in a row) were dispatched nowhere and silently
lost — indistinguishable from the keystroke just not having happened.
Whichever character happened to be "in flight" when the response arrived
and focus returned defined where the *next* `startEdit` call picked up,
which is why the value quietly lost only its *first* digit rather than
failing in any more obvious way.

Fixed by moving the selection change and `gridWrapper.focus()` call to
happen synchronously, immediately after reading `cellEditor`'s value and
*before* the `await` — the value still saves asynchronously, but the grid
is never left without an active focus target. Also fixed in the same
pass: `commitEdit`'s own `moveDir` parameter was dead code (every call
site passed `null` and did its own separate, differently-timed
`selectCell` via a trailing `.then()`, and the `"right"` branch of that
dead code did not even move right) — calls now pass the real intended
direction and there is exactly one place selection changes after a
commit. `tests/browser_smoke.js` now types a whole row back-to-back with
no artificial pauses (check 7) to guard against this regressing.

## Verification added, not just fixes

- A combined fuzz test (`test_random_paste_fill_clear_fuzz`) drives
  `set_cell`, `copy_paste`, `fill`, and `clear` in random combination —
  the earlier fuzz tests only exercised plain single-cell edits — against
  formulas that frequently create and break reference cycles, diffing the
  incremental engine against a full from-scratch recompute after *every*
  single step (300 steps). Zero mismatches after the fixes above.
- A dedicated depth-guard test sweeps nesting from comfortably-fine (30)
  to absurd (5000), asserting a clean `ParseError`/`#ERROR!` throughout,
  never a crash.
- `tests/browser_smoke.js` now exercises the exact sequence that exposed
  bugs 6 and 7 (type a literal, type a dependent formula, assert the
  *computed* value, edit the precedent, assert the dependent recomputed)
  rather than only checking that elements exist on the page.

## Considered and deliberately not changed

- **No external oracle (e.g. LibreOffice) was available.** `soffice` is
  installed in this sandbox, but headless conversion of *any* input file
  (a hand-built minimal `.xlsx`, even a trivial `.csv`) fails with
  `Error: source file could not be loaded` regardless of content —
  confirmed by spiking it before committing to the plan, not assumed.
  The self-consistency oracle (incremental vs. full recompute) is the
  strongest verification actually available here, and it is exercised
  much harder than a one-shot external diff would be, since it re-checks
  after every single mutation across a long random session rather than
  once per test file.
- `COUNTIF(range, "")` does not count truly blank cells (a genuine, if
  obscure, Excel behavior). Left as a known, documented gap rather than
  chased, since it does not affect any of this build's demonstrated
  features.
- Large numbers format with a lowercase `e` (`1e+20`) rather than Excel's
  uppercase `1E+20`. Cosmetic; addressed in Phase 4 polish, not treated as
  a correctness bug.
- The browser grid is a fixed 26×50 cells. This is a stated scope
  decision (see PLAN.md), not a hidden limitation — the engine itself
  places no such bound on addressable cells (tested up to a 2000-row
  fill in `sheet.py`'s test suite).
