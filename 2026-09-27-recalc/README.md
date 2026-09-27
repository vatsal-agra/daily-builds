# Recalc

A from-scratch spreadsheet engine: formula language, dependency graph,
incremental recalculation, and (coming next) a browser grid UI backed by
the real Python engine.

**Status: Phase 2 (core build) complete for the engine layer.** See
[PLAN.md](PLAN.md) for the full architecture and feature list.

## What's implemented so far

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
- `tests/` — 75 unit tests, including a fuzz harness that, after every
  random edit to a random sheet, diffs the incremental engine's cell
  values against a from-scratch full recompute (the core correctness
  invariant this build is built around).

## Not yet built

The browser grid UI and `server.py` backing it (required feature 4), plus
the stretch features (charting) and the CLI entry point. Coming in the
rest of Phase 2 and Phase 4.

## Running the tests

```
cd 2026-09-27-recalc
python3 -m unittest discover -s tests -v
```
