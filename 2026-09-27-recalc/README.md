# Recalc

A from-scratch spreadsheet engine: formula language, dependency graph,
incremental recalculation, and a browser grid UI backed by the real
Python engine.

**Status: Phase 3 (adversarial review) complete.** All 4 required
features work end-to-end; 7 real bugs were found (2 of them only visible
by driving an actual headless browser, one a process-crashing
`RecursionError`) and fixed — see [REVIEW.md](REVIEW.md) for the full
writeup. See [PLAN.md](PLAN.md) for the architecture and feature list.

## What's implemented

- `engine/tokenizer.py`, `engine/parser.py`, `engine/evaluator.py` — a full
  Excel-like formula language: arithmetic, comparisons, string
  concatenation, cell/range references, function calls, and Excel's exact
  (slightly surprising) operator precedence, including unary minus binding
  *tighter* than `^`.
- `engine/values.py`, `engine/functions.py` — a typed value model
  (number/text/bool/blank/error) and 24 built-in functions (`SUM`,
  `AVERAGE`, `MIN`, `MAX`, `COUNT`, `COUNTA`, `COUNTIF`, `SUMIF`, `IF`,
  `AND`, `OR`, `NOT`, `IFERROR`, `ISERROR`, `CONCATENATE`, `LEN`, `UPPER`,
  `LOWER`, `TRIM`, `ROUND`, `ABS`, `SQRT`, `MOD`, `INT`, `VLOOKUP`).
- `engine/sheet.py` — the dependency graph: precedent/dependent edges,
  incremental (dirty-propagating) recalculation via Kahn's algorithm,
  cycle detection (`#CYCLE!`), copy/paste and fill with relative/absolute
  reference translation, and multi-level undo/redo.
- `engine/csvio.py` — CSV import/export and a JSON workbook save/load
  format.
- `server.py` + `static/` — a stdlib-only HTTP server and a browser grid
  UI (click/drag select, formula bar, keyboard nav, copy/paste, fill
  handle, undo/redo, CSV import/export, save/load, a bar/line chart
  panel) that renders only values the real Python engine computed.
- `recalc.py` — CLI (`serve`, `run`, `demo`).
- `demo.py` — a narrated, self-checking walkthrough of every feature.
- `tests/` — 79 unit tests (tokenizer/parser/precedence, the full
  function library, the dependency graph, copy/paste/fill translation,
  undo/redo, CSV I/O, a parser nesting-depth guard) plus a real
  headless-Chromium browser test (`tests/browser_smoke.js`), including
  fuzz harnesses that, after every random `set_cell`/`copy_paste`/
  `fill`/`clear` on a random sheet, diff the incremental engine's cell
  values against a from-scratch full recompute — the core correctness
  invariant this build is built around.

## Running it

```
cd 2026-09-27-recalc
python3 -m unittest discover -s tests -v   # engine unit tests
python3 recalc.py demo                     # narrated CLI walkthrough
python3 recalc.py serve                    # then open http://127.0.0.1:8765
node tests/browser_smoke.js                # headless-browser UI check (server must be running)
```
