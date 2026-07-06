# Formulate

A spreadsheet, built from scratch: a real formula language (lexer →
recursive-descent parser → AST → evaluator), a dependency graph that
recalculates only what changed — not the whole sheet — and an interactive
browser UI backed by an actual Python engine running behind `http.server`.
The browser holds no formula logic at all; every edit is a network round
trip to the real engine, the same pattern this project series used for
Gambit's chess board: the server thinks, the browser just paints.

## What it is

- A **formula language**: tokenizer → recursive-descent parser → AST →
  evaluator, with real Excel-style operator precedence (`%` > `^` >
  unary `-` > `* /` > `+ -` > `&` > comparisons), relative and absolute
  cell/range references (`A1`, `$A$1`, `A1:B10`), cross-sheet references
  (`Sheet2!A1`), and 30+ built-in functions.
- A **live dependency graph**: every cell tracks its precedents and
  dependents. Editing a cell recalculates *only* the cells that could have
  changed (dirty-propagation via topological order), not the entire
  workbook — verified equivalent to a full from-scratch recompute via
  randomized fuzz testing on every edit.
- **Circular-reference detection** that marks exactly the cells in a cycle
  `#CIRC!` instead of hanging, no matter how the cycle was constructed
  (self-reference, mutual reference, or a self-referential range).
- An **interactive spreadsheet UI** — grid, keyboard navigation, a formula
  bar, drag-fill, multi-sheet tabs, live charts — that is a thin client
  over the real engine, not a reimplementation of it.

## How to run it

```bash
python3 cli.py demo             # build + print a demo budget workbook to the terminal
python3 cli.py serve            # http://127.0.0.1:8000 — the interactive UI
python3 cli.py serve --port 9000 --load workbooks/mysave.json
python3 cli.py export --out out.csv   # export the demo workbook to CSV
python3 cli.py test              # run the Python test suite
./demo.sh                        # full verification: tests + API walkthrough + UI smoke test
```

No dependencies beyond the Python 3 standard library. The UI is a single
static HTML/CSS/JS page with zero client-side formula logic — everything
lives in `engine/`.

## Full feature list

**Required:**

1. **Formula engine** — lexer, recursive-descent parser, evaluator; 30+
   functions (`SUM AVERAGE COUNT COUNTA MIN MAX IF AND OR NOT IFERROR
   ROUND ABS SQRT POWER MOD INT FLOOR CEILING SIGN CONCAT LEN UPPER LOWER
   TRIM LEFT RIGHT MID ISBLANK ISNUMBER ISTEXT ISERROR SUMIF COUNTIF
   AVERAGEIF INDEX MATCH VLOOKUP`); Excel-style error propagation
   (`#DIV/0! #VALUE! #NAME? #REF! #N/A #NUM! #CIRC!`).
2. **Incremental dependency-graph engine** — live precedents/dependents
   graph, Kahn's-algorithm recalculation restricted to the dirty set,
   circular-reference detection, fuzz-verified equivalence to full
   recompute.
3. **Interactive browser spreadsheet UI** — grid, full keyboard nav
   (arrows/Tab/Enter/Escape/F2/Delete), formula bar, multi-level undo/redo,
   inline error highlighting, an empty-workbook hint.
4. **Persistence & data interchange** — JSON workbook save/load (formulas
   round-trip exactly, values are recomputed on load) and CSV
   import/export.

**Stretch (all 3 shipped):**

5. **Autofill / drag-fill** with automatic relative-reference shifting
   (`$`-pinned refs stay fixed) — the fill handle drag matches Excel's
   semantics, verified against mixed absolute/relative formulas.
6. **Live in-browser charts** — select a range, render a bar/line chart on
   a canvas; the chart redraws automatically whenever the charted cells
   recalculate.
7. **Multi-sheet workbooks** with cross-sheet references (`Sheet2!A1`) and
   a sheet-tab bar, including forward references to sheets that don't
   exist yet (they start resolving the moment the sheet + cell are
   created).

## Why this one, today

Earlier builds in this series have "evaluate an expression" projects (SAT
solvers, a regex engine, a bytecode VM) but always over a **static, closed
input** — parse once, run once. A spreadsheet is a different, harder
problem: the thing being evaluated is a **mutable graph** that a user edits
one cell at a time, forever. That gives a genuinely strong, checkable
invariant to build the whole project around — incremental recalculation
must always agree with a full recompute, for *any* sequence of edits — and
it's the same core idea (a reactive dataflow graph) behind everything from
Excel to `useMemo` dependency arrays. It's also a recognizable, useful
*product*, which raises the bar on the interactive-UI phase in a way a
pure-CLI project doesn't: a formula bar, drag-fill, and keyboard navigation
either feel real or they don't.

The adversarial-review phase (see [REVIEW.md](REVIEW.md)) earned its keep
here: a hostile pass caught a `POWER(10,400)` overflow that could crash a
whole batch edit, a cross-sheet-reference bug that broke on almost any real
sheet name (case-sensitivity mismatch between the lexer and the sheet
dict), and two DOM-event-ordering bugs in the frontend that a Python test
suite structurally cannot see — only driving the real UI in a headless
browser caught them.

## Where a human could take this next

- **Bigger grids, real virtualization.** The grid renders every cell in a
  fixed viewport; a real spreadsheet needs windowed rendering and a sparse
  data model that scales to thousands of rows without re-rendering the
  whole table on every edit.
- **More of the function library**: date/time functions, `TEXT`/number
  formatting codes, array formulas, `OFFSET`/`INDIRECT`.
- **Multiplayer.** The server already centralizes all state in one
  `Workbook`; broadcasting diffs over WebSockets to multiple connected
  browsers would turn this into a real-time collaborative sheet with very
  little architectural change.
- **Undo for structural edits.** Undo/redo currently covers cell edits
  only (the required feature); extending the same history mechanism to
  sheet add/rename/delete would make it fully consistent.
- **Named ranges and cell formatting** (number formats, colors, bold) —
  natural next features once the core engine is in place.
- **A real formula-editing experience**: autocomplete for function names,
  inline range highlighting while typing a formula (like Excel's
  colored-range-borders), and blocking commit on a genuinely malformed
  formula instead of storing it as `#SYNTAX!`.

## Verification

`./demo.sh` runs, in order: the Python test suite (82 tests — lexer,
parser, function library, dependency-graph fuzz oracle, CSV, persistence,
and an HTTP server test suite), an 11-check end-to-end API walkthrough
covering every required and stretch feature over real HTTP, the CLI's
terminal demo, and a headless-Chromium/Playwright smoke test that types
into the real UI, drags the fill handle, forces a circular reference, and
adds a sheet — all against the actual server, not a mock.
