# Recalc

A from-scratch spreadsheet engine: a real Excel-like formula language, a
dependency graph with incremental (dirty-propagating) recalculation, and
a browser grid UI backed entirely by the real Python engine — no formula
logic is ever duplicated in JavaScript.

## What it is

Type a number or a formula (`=SUM(A1:A10)`, `=IF(B2>0,"ok","bad")`,
`=VLOOKUP(...)`) into any cell of a 26×50 grid in your browser. Every
value on screen was computed by the actual Python engine, sent over a
small JSON API — the browser never re-implements evaluation itself.
Editing a cell recomputes exactly the cells that transitively depend on
it (not the whole sheet), circular references are detected and reported
as `#CYCLE!` rather than hanging, and copy/paste/fill correctly translate
relative references while respecting `$`-locked ones — the same rules a
real spreadsheet uses.

## How to run it

```
cd 2026-09-27-recalc
python3 recalc.py serve            # then open http://127.0.0.1:8765
```

Other entry points:

```
python3 recalc.py demo             # narrated CLI walkthrough of every feature
python3 recalc.py run sheet.csv --export out.csv   # batch-evaluate a CSV
python3 -m unittest discover -s tests -v           # 80 unit/property/fuzz tests
node tests/browser_smoke.js        # headless-Chromium UI check (server must be running)
bash demo.sh                       # everything above, in one shot, exits non-zero on failure
```

No third-party dependencies anywhere in the engine, server, or CLI — pure
Python 3 stdlib. The static frontend is vanilla HTML/CSS/JS, no build
step. `demo.sh` and the browser test use the Playwright/Chromium already
present in this environment.

## Full feature list

**Formula language** (`engine/tokenizer.py`, `parser.py`, `evaluator.py`)
- Arithmetic (`+ - * / ^`) with correct precedence, including the
  authentic (if surprising) spreadsheet rule that unary minus binds
  *tighter* than `^` (`-2^2` is `4`, not `-4`).
- Comparisons (`= <> < <= > >=`) with Excel's cross-type ordering (blank
  < number < text < boolean) and case-insensitive text comparison.
- String concatenation (`&`).
- Single-cell (`A1`, `$A$1`, `A$1`, `$A1`) and range (`A1:B10`)
  references, in any corner order.
- Excel-style error values (`#DIV/0!`, `#VALUE!`, `#REF!`, `#NAME?`,
  `#N/A`, `#NUM!`, `#CYCLE!`) that propagate through expressions and are
  themselves valid literals you can type directly into a formula.
- A leading apostrophe (`'5`, `'TRUE`) forces text, like a real
  spreadsheet.

**24 built-in functions**: `SUM AVERAGE MIN MAX COUNT COUNTA COUNTIF
SUMIF IF AND OR NOT IFERROR ISERROR CONCATENATE LEN UPPER LOWER TRIM
ROUND ABS SQRT MOD INT VLOOKUP` — each matching Excel's real semantics,
including its error behavior (e.g. `SUM` silently skips text found via a
range but errors on a non-numeric direct argument; `VLOOKUP` with no
match is `#N/A`).

**Dependency graph + incremental recalculation** (`engine/sheet.py`)
- Precedent/dependent edges maintained on every edit; a change dirties
  exactly its transitive dependents, recomputed via Kahn's algorithm.
- Circular references detected and reported as `#CYCLE!` on every cell in
  the cycle (direct self-reference, indirect chains, and self-referential
  ranges all handled); recovers cleanly once the cycle is broken.
- Verified by fuzz tests that, after every random `set_cell`/
  `copy_paste`/`fill`/`clear` on a random sheet (including edits that
  create and break cycles), diff the incremental engine against a full
  from-scratch recompute — 600+ steps with zero mismatches.

**Copy/paste and fill** with relative-reference translation (shifts by
the paste/fill offset) and `$`-locked absolute references (untouched); a
reference pushed off the grid edge becomes `#REF!`, not a crash.

**Undo/redo**: a command-stack history covering every mutating operation
(edits, paste, fill, clear) as one transaction each, multi-level, wired
into the UI's buttons and Ctrl+Z/Ctrl+Y.

**CSV import/export** and a JSON workbook save/load format, both in the
UI and via the CLI.

**Minimal charting**: select a range, choose bar or line, rendered on a
plain `<canvas>` (no charting library) from the live computed values.

**Browser grid UI** (`server.py`, `static/`): click/shift-click/drag
selection, a formula bar, full keyboard navigation (arrows, Enter, Tab,
Escape, Delete), a drag fill handle, active row/column header
highlighting, and a dark, custom-styled theme (not default browser
widgets) — verified with a real headless-Chromium pass, not just visual
inspection.

## Why this, today

Every prior "from scratch" build in this repo modeled a language runtime,
a renderer, a distributed system, or a simulation — a one-shot pipeline
(render a frame, solve a formula, compile a program) or a system with a
single, controlled evolution over time (a Raft cluster, a blockchain, a
CPU pipeline). None had modeled a **live, mutable, cyclic-graph-shaped**
problem: a dependency graph that a user edits by hand, forever, where the
central correctness question isn't "is this one output right" but "does
this incrementally-maintained graph *always* agree with what you'd get by
throwing it away and recomputing everything." That invariant — proven, not
assumed, via the fuzz harness above — is the spine this build is built
around, and it's a genuinely different kind of bug surface than anything
this repo had exercised before.

## Where a human could take this next

- **Bigger grid / virtualized rendering.** The UI is a fixed 26×50 table
  by design (see PLAN.md); the engine itself has no such limit (tested to
  a 2000-row fill). A virtualized/windowed renderer would let the UI scale
  to a real spreadsheet's size.
- **More functions**: date/time arithmetic, `INDEX`/`MATCH`, array
  formulas, `SUMPRODUCT`, text functions like `LEFT`/`RIGHT`/`MID`/`FIND`.
- **Multi-sheet workbooks** with cross-sheet references (`Sheet2!A1`) —
  the dependency graph model extends naturally; the main change is
  namespacing cell keys by sheet.
- **Real-time multi-user collaboration** — this repo already has the
  building block (Concord's RGA CRDT, 2026-09-09) that could sit
  underneath a shared Recalc workbook.
- **A real named-range and cell-formatting layer** (number formats,
  colors, borders) for visual/semantic richness beyond raw values.

## Development notes

See [PLAN.md](PLAN.md) for the original architecture and feature plan,
and [REVIEW.md](REVIEW.md) for the Phase 3/4 adversarial review — 8 real
bugs found and fixed, including a process-crashing `RecursionError` on
pathological input and, found only by actually typing a row of data at
normal speed in a live browser, a focus race that silently dropped the
first keystroke after Tab/Enter.
