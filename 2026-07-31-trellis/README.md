# Trellis

A spreadsheet engine built entirely from scratch: a real formula parser,
a dependency-graph-based incremental recalculation engine, and an
interactive server-backed browser grid.

**Status: Phase 5 (verification) complete.** 140 Python unit/integration
tests (including a real HTTP server driven over a live socket) plus a
Playwright headless-Chromium UI test that re-verifies every REVIEW.md
finding against a running server all pass — run `./demo.sh` for the full
walkthrough (test suite → `trellis demo` → live curl API walkthrough →
real-browser UI test → CLI smoke checks → clean-error-handling checks).
See [PLAN.md](PLAN.md) for
the full architecture and feature list, and [REVIEW.md](REVIEW.md) for 9
real bugs found (by actually driving the UI in headless Chromium and
attacking the HTTP API directly, not just reading the code) and fixed —
including two data-loss/corruption bugs in the inline cell editor, a broken
sheet-rename that silently orphaned cross-sheet formulas, and two distinct
crash vectors (`RecursionError` from deeply nested and very long formulas)
that are now clean spreadsheet errors instead of hard crashes.

**All 3 planned stretch features are shipped and fully wired into the UI:**
undo/redo (`Ctrl+Z`/`Ctrl+Y` or the toolbar buttons), live SVG bar/line
charts, and multi-sheet workbooks with cross-sheet references (`Data!A1`)
— including sheet add/rename/delete, all exercised through the real tab
bar (double-click to rename, hover-× to delete), not just the backend API.

**Phase 4 polish:** fixed floating-point display noise (`0.1+0.2` now
shows `0.3`, not `0.30000000000000004`, matching how real spreadsheets
round their display precision without losing any calculation accuracy),
and CSV imports that exceed the visible grid now report exactly how many
cells were skipped instead of silently discarding them.

## Quickstart

```
python3 -m trellis repl                       # interactive cell-at-a-time REPL
python3 -m trellis csv-import data.csv         # import + print a CSV grid
python3 -m trellis serve                       # http://127.0.0.1:8765 — the real UI
python3 -m trellis demo                        # scripted walkthrough of every feature
```

## What's implemented so far (required features)

1. **Formula parser + evaluator** (`trellis/lexer.py`, `parser.py`,
   `evaluator.py`, `functions.py`) — arithmetic, comparisons, string
   concat, cell/range references, ~20 builtin functions (`SUM`, `IF`,
   `VLOOKUP`, ...), typed error values (`#DIV/0!`, `#VALUE!`, `#REF!`,
   `#NAME?`).
2. **Dependency graph + incremental recalculation** (`trellis/depgraph.py`,
   `sheet.py`) — editing a cell recomputes only its transitive dependents
   (verified: editing an unrelated cell in a 500-cell sheet triggers zero
   recomputation), and circular references are detected (Tarjan's SCC) and
   reported as `#CIRCULAR!` instead of hanging.
3. **Grid data model + CSV import/export** (`trellis/sheet.py`, `csvio.py`).
4. **Interactive server-backed browser UI** (`trellis/server.py`,
   `web/index.html`) — click/type/arrow-key grid editing, a formula bar,
   live recalculation over real HTTP, error highlighting. Verified in real
   headless Chromium, not just by reading the code.

Undo/redo, SVG charts, and multi-sheet workbooks with cross-sheet
references are also wired up already; formal stretch-feature polish lands
in a later phase. See PLAN.md for what's still ahead (adversarial review,
polish, verification, ship).
