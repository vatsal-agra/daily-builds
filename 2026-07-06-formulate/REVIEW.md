# Formulate — Adversarial Review (Phase 3)

Hostile pass over the Phase 2 build: fuzzing the engine, hand-crafting
pathological formulas, driving the real UI in a headless browser, and
poking at the HTTP surface directly with sockets/curl. Every issue below
was reproduced first, then fixed, then covered by a regression test.

## Bugs found and fixed

1. **Crash: non-finite/complex arithmetic escaped evaluation entirely.**
   `=1e400` (a literal that overflows float64), `=POWER(-8,0.5)` (Python's
   `**` silently returns a `complex` for a fractional power of a negative
   base — it doesn't raise), and `=POWER(10,400)` (`OverflowError` from
   `float ** float`) all either produced a value that later crashed
   `display_value()` (`int(inf)` raises `OverflowError`) or crashed the
   request outright. Fixed at three points: `evaluate()` now rejects any
   non-finite float or complex result and turns it into `#NUM!`;
   `parse_literal()` falls back to text instead of storing an overflowed
   float; `_eval_funccall()` now catches `OverflowError`/`ValueError`/
   `ZeroDivisionError`/`TypeError` from *any* library function and converts
   them to `#NUM!` instead of letting a single bad formula 500 an entire
   batch edit. `display_value()` also got a defensive non-finite check as
   a second line of defense.
2. **Correctness: cross-sheet references broke for almost any real sheet
   name.** The lexer force-uppercased every `NAME` token (needed for
   case-insensitive function names like `sum`/`SUM`), but `NAME` tokens are
   also sheet names before `!`, and sheet names are case-sensitive keys in
   `Workbook.sheets`. `=Sheet1!A2` parsed its ref as sheet `"SHEET1"`, which
   didn't match the sheet actually named `"Sheet1"`, evaluating to `#REF!`
   — this reproduced both live and after a JSON save/load round-trip. Fixed
   by preserving original case in the lexer and uppercasing only at
   function-dispatch time in the evaluator.
3. **Correctness: ref-shaped sheet/function names misclassified.** A sheet
   name ending in a digit (`Sheet2`) or a function name ending in a digit
   (`LOG10`) matches the cell-reference regex, so the lexer tokenized
   `Sheet2!A1` as `REF("SHEET2") BANG REF("A1")` instead of
   `NAME("Sheet2") BANG REF("A1")`, and the parser rejected it outright.
   Fixed by checking the character after the ref-shaped match: `(` or `!`
   means it's actually a name, not a reference.
4. **Correctness: unparse precedence table was backwards for unary minus.**
   `ast_nodes._PRECEDENCE` ranked unary `-` *above* `^`, the opposite of
   Excel's real order, so round-tripping `-2^2` (which evaluates correctly
   as `-(2^2) = -4`, since the actual recursive-descent parser doesn't
   consult this table) rendered back out as `-(2^2)` instead of `-2^2`.
   This would have corrupted autofilled formula text on any fill crossing a
   unary-minus-over-power expression. Fixed the table to the real order
   (`% > ^ > unary- > * / > + - > & > comparisons`).
5. **Frontend bug: the character that starts an inline edit got typed
   twice.** Pressing `=` on a selected cell synchronously creates and
   focuses an `<input>` inside the same keydown handler, but without
   `preventDefault()` the browser still ran its *default* action (character
   insertion) against whatever element ended up focused when the handler
   returned — the brand-new input. Typing `=A1*3` landed as `==A1*3`.
   Caught by the headless-browser smoke test, not the Python suite (this
   class of bug only exists in the DOM/event-loop interaction). Fixed with
   `e.preventDefault()`.
6. **Frontend bug: Enter/Tab/Escape fired twice.** The in-cell editor's
   keydown handler clears the shared `editing` flag *synchronously* as part
   of committing, but that handler runs (and returns) before the same
   keydown event finishes bubbling up to the document-level navigation
   handler — which checks `if (editing) return` and, by then, finds it
   already false. A single Tab press moved the selection two columns
   instead of one. Fixed with `e.stopPropagation()` in the editor handler.
7. **Frontend race: mutating requests weren't ordered.** `commitEdit()` is
   fired-and-forgotten (so typing stays responsive), so a fast
   Tab-then-immediately-type-a-formula sequence could dispatch two POSTs
   whose arrival order at the server wasn't guaranteed to match the order
   the user triggered them in. Reproduced by the UI smoke test running at
   full speed with no artificial waits. Fixed with a client-side FIFO
   mutation queue (`mutate()`) that all edit/undo/redo/autofill/import
   calls now go through.
8. **UX inconsistency: charting a single row produced a nonsensical
   chart.** `/api/chart` always treated the selection's first *column* as
   category labels and the rest as value series. For a horizontal selection
   like `A1:C1` that meant one label (from `A1`) and two size-1 series (`B1`,
   `C1`) instead of one three-bar chart. Added a dedicated single-row branch
   (mirrors the existing single-column branch, transposed).
9. **Confusing name:** `CircularRangeError` was raised for "this range
   expands to more than 20,000 cells," which has nothing to do with
   circularity. Renamed to `RangeTooLargeError`.

## Checked and confirmed *not* bugs

- **Path traversal.** Tried `GET /../server.py` (both via curl and a raw
  socket, bypassing any client-side normalization) against the static file
  server, and traversal-style workbook names (`../../etc/passwd`) against
  `/api/save` / `/api/load`. Both are rejected — `_serve_static` resolves
  and checks the path is still under `STATIC_DIR`, and `_safe_name` strips
  anything but alnum/`-`/`_` before touching the filesystem.
- **Forward references across edits.** `=Ghost!A1` before sheet `Ghost`
  even exists correctly shows `#REF!`, and starts resolving and
  recalculating automatically the moment `Ghost` is created and `Ghost!A1`
  is set — the dependency graph tracks the *key*, not whether the sheet
  existed yet when the edge was recorded. Also verified for JSON
  persistence: cells loaded in arbitrary dict order still converge to the
  correct values because loading is one batched `edit()` call.
- **SUMIF/COUNTIF/AVERAGEIF with an error cell inside the range.** An
  `ErrorValue` inside a criteria or sum range correctly propagates as that
  error (e.g. `#DIV/0!`) out of the whole formula rather than being
  silently skipped or crashing the aggregation.
- **Self-referential ranges** (`=SUM(A1:A5)` written into `A1`) are caught
  by the same cycle detector as direct self-references and marked
  `#CIRC!`.

## Accepted scope limitations (not bugs)

- **Sheet add/rename isn't undoable.** `Workbook.history` only tracks
  cell-level edits (the required undo/redo feature); structural sheet
  operations are a stretch-feature addition on top of that and were never
  scoped to participate in the same undo stack. Cell edits *within* a new
  sheet undo/redo normally.
- **Committing an unparseable formula stores `#SYNTAX!` instead of
  blocking the edit.** Real Excel pops a "there's a problem with this
  formula" dialog and keeps you in edit mode; this build lets the bad
  formula land as an error value you can then fix in place. Simpler, still
  never loses data or crashes, and consistent with how every other formula
  error in this build is surfaced.
- **CSV import treats a leading `=` as a live formula**, matching (not
  fixing) the same behavior real Excel/Sheets have — including the same
  formula-injection-on-import quirk that behavior is known for. Not
  something to silently "fix" without changing the documented feature (CSV
  import creating formulas is arguably a feature here, not a bug).

All fixes above are covered by regression tests added to `tests/` (now 81
Python tests, plus the headless-browser smoke test) — see the diff for
specifics per bug.
