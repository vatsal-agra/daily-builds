# Trellis

A spreadsheet engine built entirely from scratch: a real formula parser,
a dependency-graph-based incremental recalculation engine, and an
interactive server-backed browser grid.

**Status: Phase 2 (core build) complete.** See [PLAN.md](PLAN.md) for the
full architecture and feature list.

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
