# Trellis

A spreadsheet engine built entirely from scratch: a real formula parser
(recursive-descent, ~20 builtin functions, typed error values), a
dependency-graph-based incremental recalculation engine (edit one cell,
only its actual dependents recompute — verified, not just claimed), CSV
import/export, undo/redo, SVG charts, and multi-sheet workbooks with
cross-sheet references — all driven live from a real interactive browser
grid backed by a stdlib-only HTTP server.

## What it is

Every spreadsheet app hides three genuinely hard problems behind a
friendly grid: parsing an expression language that mixes arithmetic with
cell references and function calls, incrementally recomputing only what
actually changed (the same problem behind build systems and reactive UI
frameworks — spreadsheets are the original example), and treating cycles
as a first-class, detectable outcome instead of an infinite loop. Trellis
implements all three from first principles, in pure Python.

## How to run it

```bash
python3 -m trellis serve              # http://127.0.0.1:8765 — the real UI
python3 -m trellis repl               # interactive cell-at-a-time REPL
python3 -m trellis csv-import data.csv --out computed.csv
python3 -m trellis demo               # scripted walkthrough of every feature
./demo.sh                             # full verification: tests + demo + live
                                       # HTTP walkthrough + real-browser UI test
```

No dependencies to install — the engine, CLI, and server are pure Python 3
stdlib, and the browser UI is a single self-contained HTML/CSS/JS file with
no build step. (Verifying the UI in a real headless browser during
development used Playwright/Chromium, which is not required to run Trellis
itself.)

## Feature list

**Core:**

- **Formula parser + evaluator** — arithmetic (`+ - * / ^ %`), comparisons,
  string concatenation (`&`), cell refs (`A1`, `$A$1`), ranges (`A1:B10`),
  cross-sheet refs (`Sheet2!A1`), and ~20 builtin functions (`SUM`,
  `AVERAGE`, `COUNT`/`COUNTA`, `MIN`/`MAX`, `IF` (short-circuiting),
  `IFERROR`, `AND`/`OR`/`NOT`, `ROUND`/`ABS`/`SQRT`/`POWER`/`MOD`,
  `LEN`/`UPPER`/`LOWER`/`TRIM`/`CONCAT`, `VLOOKUP`). Errors are typed
  values (`#DIV/0!`, `#VALUE!`, `#REF!`, `#NAME?`, `#N/A`, `#NUM!`) that
  propagate through formulas instead of raising Python exceptions out of
  the engine.
- **Dependency graph + incremental recalculation** — a real DAG of "cell X
  reads cell Y" edges (Kahn's-algorithm topological recompute of just the
  affected subgraph) and Tarjan's-SCC cycle detection reporting
  `#CIRCULAR!` on every cell in a cycle instead of hanging.
- **Grid data model + CSV import/export**, with clean error propagation
  (a formula reading an error-valued cell becomes that error, not a
  crash) and honest reporting when an import exceeds the visible grid
  instead of silently discarding rows.
- **Interactive server-backed browser UI** — click/type/arrow-key grid
  editing, a formula bar, live recalculation over real HTTP, error cells
  visually flagged. Zero spreadsheet logic in the browser; every edit is
  a real request to the Python engine.

**Stretch (all 3 shipped and fully wired into the UI, not just the
backend):**

- **Undo/redo** (`Ctrl+Z`/`Ctrl+Y` or toolbar buttons) — a command stack
  that replays edits through the real engine, so undoing restores the
  full recomputed downstream state, not just one cell's raw text.
- **Charts** — a from-scratch SVG bar/line chart renderer over any
  selected range, live in the UI.
- **Multi-sheet workbooks** — add/rename/delete sheets from the real tab
  bar (double-click to rename, hover-× to delete), with cross-sheet
  formula references that survive a rename and correctly become `#REF!`
  when a referenced sheet is actually deleted.

## Why this today

Every prior build in this repo's history has been a database, a search
engine, a VCS, a compiler/VM/interpreter, a physics/rendering/audio
engine, or (repeatedly) a from-scratch transformer — but never the
specific reactive dependency-graph problem that makes a spreadsheet a
spreadsheet, and never a grid-shaped interactive data application. It's
also unusually well-suited to genuine adversarial testing: dependency
graphs have sharp, checkable correctness properties (exact recompute
counts, cycle detection, error propagation) that either hold or don't —
and driving the actual browser UI in headless Chromium (not just reading
the JS) surfaced real, reproducible bugs a code read alone would have
missed. See [REVIEW.md](REVIEW.md) for the 9 found and fixed.

## Where a human could take this next

- **Cell fill/copy-paste with relative-reference adjustment** (drag-fill
  `=A1*2` down a column and have it become `=A2*2`, `=A3*2`, ...) — the
  parser already tracks `$`-absolute vs. relative refs per axis
  (`CellRef.row_abs`/`col_abs`), but nothing consumes that yet.
  addr.parse_addr already exposes what's needed.
- **A real on-disk file format** (the engine is entirely in-memory today;
  CSV is the only persistence path, and it can't round-trip multiple
  sheets or formatting).
- **More functions** (`INDEX`/`MATCH`, date/time, statistical functions)
  and array formulas.
- **Conditional formatting and cell number formats** (currency, percent,
  dates) — today every number displays with one fixed rounding rule.
- **An auto-expanding grid** instead of a fixed visible size — CSV import
  already reports skipped-cell counts honestly, but a real spreadsheet
  would just grow.
- **Collaborative editing** — the dependency graph and recalculation
  engine are already the hard part of operational-transform-free
  multi-user editing; the server would need to broadcast diffs instead of
  only answering the requesting client.

## Verification

`./demo.sh` runs, in order: the 140-test Python suite (engine unit tests
plus a real HTTP server driven over a live socket, not mocked), the
scripted `trellis demo` walkthrough, a `curl`-driven live HTTP API
walkthrough against a real running server instance, a Playwright
headless-Chromium test that re-verifies every bug in REVIEW.md against a
second fresh server instance, CLI smoke checks, and clean-error-handling
checks. All green.
