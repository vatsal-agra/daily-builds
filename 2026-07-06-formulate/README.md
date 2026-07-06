# Formulate

Status: **Phase 4 — stretch features + polish complete.** All 4 required
features plus all 3 planned stretch features (autofill, live charts,
multi-sheet workbooks) are implemented and verified (82 Python
unit/fuzz/server tests green + a headless-browser UI smoke test). A hostile
adversarial-review pass found and fixed 9 real bugs — see
[REVIEW.md](REVIEW.md). See [PLAN.md](PLAN.md) for the full design.

## What's built so far

- **Formula engine** (`engine/lexer.py`, `parser.py`, `evaluator.py`,
  `functions.py`) — full operator precedence, cell/range refs (relative +
  absolute), 30+ built-in functions, Excel-style error propagation.
- **Dependency graph & incremental recalculation** (`engine/workbook.py`) —
  live precedents/dependents graph, dirty-propagation recalculation,
  circular-reference detection, undo/redo, autofill (relative-ref shifting).
  Verified equivalent to a full recompute via randomized fuzz tests.
- **Server + UI** (`server.py`, `static/`) — an `http.server` JSON API in
  front of a real `Workbook`, and a browser spreadsheet UI (grid, formula
  bar, keyboard nav, drag-fill, multi-sheet tabs, a chart panel) that holds
  no formula logic of its own.
- **Persistence & CSV** (`engine/persistence.py`, `csvio.py`) — JSON
  workbook save/load and CSV import/export.

## Try it

```
python3 cli.py demo             # prints a demo budget workbook to the terminal
python3 cli.py serve            # http://127.0.0.1:8000 — the interactive UI
python3 cli.py test             # run the test suite
```
