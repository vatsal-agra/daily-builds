# Formulate — PLAN

## Concept

A spreadsheet, built from scratch: a real formula language (lexer →
recursive-descent parser → AST → evaluator), a dependency graph that
recalculates only what changed (not the whole sheet), and a live
browser UI backed by an actual Python engine running in an
`http.server` process — no JS reimplementation of the math, the
browser is just a terminal into the real engine (same pattern Gambit
used for chess: the server thinks, the browser just paints).

## Why this is interesting

Every daily build so far that touches "evaluate an expression" has
been a toy calculator or a SAT/regex engine operating on a closed,
static input. A spreadsheet is different in a way that's genuinely
hard to get right:

- The thing being evaluated is a **mutable graph**, not a static AST.
  Every cell edit can change what depends on what, and the dependency
  graph itself must be kept correct incrementally (add/remove edges as
  formulas change), not rebuilt from scratch each time.
- Correctness has a **precise, checkable oracle**: incremental
  (dirty-propagation) recalculation must produce byte-identical values
  to a full from-scratch recompute of the entire graph, for *any*
  sequence of edits. That's a strong, fuzzable invariant — exactly the
  kind of thing this project series has done well elsewhere (Myers
  diff vs brute-force LCS, CDCL vs brute-force SAT, HNSW vs exact
  k-NN) but applied to a new domain: reactive incremental computation,
  the same core idea behind Excel, spreadsheets-as-databases, and
  modern reactive/dataflow UI frameworks (signals, `useMemo` graphs).
- **Cycles are a first-class case, not an error path to paper over.**
  A real engine has to detect circular references across an arbitrary
  mutable graph and mark exactly the cells in the cycle as errors
  without crashing or looping forever.
- It's a genuinely useful, recognizable *product* (not just an
  algorithm demo), which raises the bar on the interactive-UI phase in
  a way pure-CLI projects don't: keyboard navigation, a formula bar,
  live error highlighting, undo/redo, drag-fill — the unglamorous UX
  details that separate "technically works" from "usable."

## Architecture

```
engine/
  lexer.py       tokenizer for the formula grammar
  parser.py      recursive-descent parser -> AST (ast_nodes.py)
  ast_nodes.py    AST node dataclasses + a formula "unparser" (AST -> text,
                  needed for autofill's reference-shifting)
  functions.py   built-in function library (30+ functions), range flattening
  evaluator.py   AST -> value, with Excel-style error propagation
  workbook.py    Cell / Sheet / Workbook, dependency graph (precedents /
                 dependents adjacency), topological incremental recalculation,
                 circular-reference detection, undo/redo command stack,
                 autofill (relative-reference shifting)
  csvio.py       CSV import (text -> grid of literals) / export (grid -> CSV)
  persistence.py JSON workbook save/load (formulas + computed cache)
server.py         stdlib http.server exposing a small JSON API over a
                  Workbook instance; serves static/index.html
static/index.html the spreadsheet UI: grid, formula bar, keyboard nav,
                   drag-fill handle, chart overlay — all talking to the
                   Python engine over fetch(), zero client-side formula logic
cli.py            `formulate serve|demo|import|export|test` entry point
tests/            unit + property/fuzz tests (see PHASE 5)
demo.sh           runs the full verification suite end-to-end
```

Design choice: **all formula logic lives in Python, once.** The
browser never re-implements evaluation — every keystroke that changes
a cell's formula is POSTed to the server, evaluated by the real
engine, and the server replies with exactly the set of cells that
changed value (the dirty set), which the UI patches into the DOM. This
sidesteps the classic "JS mirror of the engine, kept in sync by hand"
duplication risk this project series has hit before (regex, physics,
SAT visualizers all needed a parity test between two implementations
of the same logic). Here there is only one implementation.

## Feature list

**Required (4):**

1. **Formula language** — lexer + recursive-descent parser with real
   Excel-style operator precedence (`%` > `^` > unary `-` > `* /` >
   `+ -` > `&` > comparisons), cell refs (`A1`, absolute `$A$1`),
   ranges (`A1:B10`), 30+ built-in functions (SUM, AVERAGE, COUNT,
   COUNTA, MIN, MAX, IF, AND, OR, NOT, IFERROR, ROUND, ABS, SQRT,
   POWER, MOD, CONCAT, LEN, UPPER, LOWER, TRIM, LEFT, RIGHT, MID,
   VLOOKUP, INDEX, MATCH, SUMIF, COUNTIF, AVERAGEIF, ...), and
   Excel-style error propagation (`#DIV/0!`, `#VALUE!`, `#NAME?`,
   `#REF!`, `#N/A`).
2. **Incremental dependency-graph engine** — a live precedents/
   dependents graph maintained as formulas change, topological
   (Kahn's-algorithm) recalculation restricted to the dirty set after
   an edit, and circular-reference detection that marks exactly the
   cycle's cells `#CIRC!` instead of hanging. Verified equivalent to a
   full brute-force recompute via randomized fuzzing.
3. **Interactive browser spreadsheet UI**, server-backed by the real
   engine: scrollable grid, mouse + full keyboard navigation
   (arrows/Tab/Enter/Escape), a formula bar, live recalculation on
   edit, inline error highlighting, and multi-level undo/redo.
4. **Persistence & data interchange** — JSON workbook save/load
   (formulas, not just values, round-trip exactly) and CSV
   import/export.

**Stretch (3, ship at least 1):**

- **S1. Autofill / drag-fill** — fill a formula across a range with
  automatic relative-reference shifting (`$` refs stay pinned),
  matching Excel's fill-handle semantics.
- **S2. Live in-browser charts** — select a range, render a bar/line
  chart from its current values on an HTML canvas, redrawn whenever
  the underlying cells recalculate.
- **S3. Multi-sheet workbooks** — more than one sheet, cross-sheet
  references (`Sheet2!A1`), and a sheet-tab bar in the UI.

## Verification strategy

- Unit tests per module (lexer, parser round-trip via unparser, each
  function, error propagation).
- **Fuzz oracle**: generate random small workbooks + random edit
  sequences; assert the incremental engine's cell values exactly match
  a full from-scratch recompute after every edit, and that any
  formula that creates a real cycle is caught.
- End-to-end server test: spin up the real HTTP server on a thread,
  drive the JSON API with `urllib`, verify a realistic scripted
  session (enter formulas, edit a precedent, confirm dependents
  update, undo, redo, save/load, import/export CSV round-trip).
- Headless-browser (Playwright/Chromium, already available) smoke
  test of the actual UI: type into a cell, tab to the next, confirm
  the DOM shows the server-computed value, not a client-side guess.
