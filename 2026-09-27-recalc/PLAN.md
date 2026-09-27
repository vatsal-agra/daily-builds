# Recalc — a from-scratch spreadsheet engine

## Concept

Every prior "from scratch" build in this repo has modeled a language runtime
(Coil's VM, six SAT solvers, RegexLab, PicoSQL), a renderer (Prism, four
path tracers, Casement's HTML/CSS engine), a distributed system (Quorum,
Concord, Vein, Matchbook, Swarm), or a simulation (Tumble/Torque, Beacon,
Quantum, Silicon). None has modeled a **reactive dependency graph over
user-editable state** — the actual computational model underneath every
spreadsheet ever opened: a formula language evaluated over a 2D grid of
cells, where editing *one* cell must correctly and efficiently propagate
through however many other cells transitively depend on it, must detect
and report circular references instead of looping forever, and must
preserve *reference semantics* (relative vs. absolute) when formulas are
copied to new locations. This is a different kind of correctness problem
from anything in this repo's history: not "does this render the right
pixels" or "does this decide SAT/UNSAT" but "does this converged,
memoized, incrementally-recomputed graph always equal the answer you'd
get by throwing the whole thing away and recomputing from scratch."
That equivalence — incremental recalculation must always agree with full
recalculation, for every edit, forever — is the load-bearing invariant
this build is designed to prove, not just hope for.

## Why it's interesting

- It's a genuinely different shape of "correctness": a live, mutable,
  cyclic-graph-shaped problem instead of a one-shot pipeline (render a
  frame, solve a formula, compile a program). The engine must handle
  *edits over time*, not a single input.
- It has an unusually strong self-check available: for any given sheet
  state, "recompute every cell from a topological sort of the *entire*
  dependency graph" is a slow but obviously-correct oracle. The real
  (fast, incremental, dirty-propagating) engine can be fuzzed against
  that oracle after every random edit — the spreadsheet equivalent of
  Casement's Chromium diff or Vein's hashlib cross-check, but built
  in-house since no oracle binary was available in this sandbox
  (LibreOffice is installed but its headless CLI does not load any
  file in this container, confirmed by spiking it before committing to
  the plan — see REVIEW.md).
- Reference-frame translation on copy/paste (relative refs shift with
  the paste offset, `$`-locked refs don't) is a small, precise piece of
  semantics that's easy to get subtly wrong and easy to verify exactly.
- It ends in a real, usable tool: a browser spreadsheet backed by the
  actual Python engine (no reimplementation in JS), in the same
  "server-backed, one source of truth" style as Gambit's browser chess
  board and Vein's block explorer.

## Architecture

```
engine/
  tokenizer.py   formula string -> token stream (numbers, strings, bools,
                 cell refs, range refs, operators, function names, commas)
  refs.py        A1-notation parsing/formatting, absolute ($) vs relative
                 components, range expansion, offset translation for
                 copy/paste and fill
  parser.py      recursive-descent Pratt parser -> AST (BinOp, UnaryOp,
                 Number, Text, Bool, CellRef, RangeRef, FuncCall, Paren)
  values.py      typed runtime values (Number/Text/Bool/Blank/Error) with
                 Excel-style error codes and Excel-style coercion rules
  functions.py   built-in function library, each a pure fn over Values
  evaluator.py   AST -> Value given a cell-lookup callback
  sheet.py       Workbook/Sheet: cell store, dependency graph (edges both
                 directions), cycle detection, topological + incremental
                 (dirty-propagation) recalculation, copy/paste/fill with
                 reference translation, undo/redo command stack
  csvio.py       CSV import (values-only) and export (computed values)
server.py        stdlib http.server + a small JSON API: get sheet, set
                 cell, undo, redo, copy/paste, import/export CSV, save/load
                 workbook (a plain JSON file format)
static/          index.html + app.js + style.css — the grid UI: formula
                 bar, keyboard navigation, click/shift-click/drag select,
                 copy/paste, undo/redo, CSV import/export, chart panel —
                 talks to server.py over fetch(); zero spreadsheet logic
                 duplicated in JS, the browser only renders what the real
                 Python engine computed.
recalc.py        CLI: serve / run (batch-evaluate a sheet file and print
                 or export it) / demo
tests/           unit + property + oracle tests, run via unittest
```

## Feature list

**Required (core, must work end-to-end, no stubs):**

1. **Formula language** — tokenizer + parser + evaluator for a real
   Excel-like expression grammar: arithmetic (`+ - * / ^`) with correct
   precedence and unary minus, comparisons (`= <> < <= > >=`), string
   concatenation (`&`), parentheses, numeric/string/boolean literals,
   single-cell references (`A1`, `$A$1`, `A$1`, `$A1`), range references
   (`A1:B10`), and function calls with variadic and range arguments.
   Excel-style error values (`#DIV/0!`, `#VALUE!`, `#REF!`, `#NAME?`,
   `#N/A`, `#NUM!`) that propagate through expressions rather than
   raising Python exceptions to the user.

2. **Dependency graph + reactive recalculation** — every cell tracks
   which cells it reads (precedents) and which cells read it
   (dependents). Editing a cell dirties exactly its transitive dependents
   and recomputes only those, in topological order. Circular references
   are detected (not stack-overflowed or infinite-looped) and every cell
   in the cycle reports `#CYCLE!`. Proven correct by a fuzz harness that,
   after every random edit to a random sheet, diffs the incremental
   engine's cell values against a from-scratch full recompute.

3. **Built-in function library** — enough real functions to write real
   spreadsheets: `SUM AVERAGE MIN MAX COUNT COUNTA COUNTIF SUMIF IF AND OR
   NOT IFERROR CONCATENATE LEN UPPER LOWER TRIM ROUND ABS SQRT MOD INT
   VLOOKUP` at minimum, each matching Excel's documented semantics
   (including its error behavior, e.g. `VLOOKUP` with no match -> `#N/A`,
   division by zero -> `#DIV/0!`).

4. **Interactive grid UI backed by the real engine** — a browser
   spreadsheet (click/arrow-key navigation, a formula bar showing the raw
   formula of the selected cell and its computed value elsewhere, edit
   in place, Enter/Tab/Escape semantics) that is a thin client over
   `server.py`'s JSON API — every recalculation shown in the browser is
   the actual Python engine's output, not a JS reimplementation.

**Stretch (2+, at least 1 shipped, ideally both):**

5. **Copy/paste and fill with reference translation** — copying a
   formula and pasting it elsewhere shifts relative references by the
   paste offset while leaving `$`-locked components untouched (the exact
   rule real spreadsheets use), including drag-fill down/right.

6. **Undo/redo** — a command-stack history covering cell edits and
   paste/fill operations, multi-level, exposed in the UI.

7. **CSV import/export** and a simple **saved workbook format** (JSON) so
   a sheet survives a server restart.

8. **Minimal charting** — select a numeric range and render a bar or line
   chart (canvas, no charting library) from its live values.

If any required feature above proves infeasible during Phase 2, it will
be replaced with one of equal size and the substitution will be recorded
here and in REVIEW.md, not silently dropped.
