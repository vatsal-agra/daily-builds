# Trellis — a spreadsheet engine built from scratch

## Concept

A real spreadsheet: a grid of cells, a formula language (`=SUM(A1:A10)*2`),
and a reactive engine that recomputes exactly the cells affected by an edit —
not the whole sheet — by tracking cell dependencies as a directed graph and
topologically recalculating only the dirty subgraph. Ships as a Python
library/CLI plus a real interactive browser grid backed by a stdlib HTTP
server (the browser holds zero spreadsheet logic — every keystroke's
recalculation happens server-side, same "server-backed, dumb browser"
pattern this repo has used for Gambit/Formulate/Faraday).

## Why this is interesting

Every spreadsheet app (Excel, Google Sheets, every clone) hides the same
three genuinely hard problems behind a friendly grid UI:

1. **Parsing a real expression language** with cell references, ranges,
   operator precedence, and a function-call syntax that has to coexist with
   normal arithmetic (`SUM(A1:A5)` vs `A1+A5`).
2. **Dependency-graph incremental recomputation.** A naive spreadsheet
   re-evaluates every cell on every edit; a real one builds a DAG of
   "cell X reads cell Y" edges and only recomputes the topologically-sorted
   subgraph downstream of what changed — the same incremental-computation
   problem behind build systems (make, Bazel) and reactive UI frameworks
   (React's dependency tracking, spreadsheets being the original example).
3. **Cycles are a first-class outcome, not a bug.** `A1=B1+1, B1=A1+1` must
   be *detected* and reported as `#CIRCULAR!`, not silently infinite-loop or
   stack-overflow the server.

This is a genuinely new domain for this repo: prior builds have covered
databases (PicoSQL), version control (Graft/Strata), search engines
(Glean/Trove), type inference (Unify), and plenty of "compile an expression
language" work (Coil, RegexLab, Backjump/Conflux/Crux/Resolvent's CNF
encoders) — but never the specific reactive dependency-graph-recalculation
problem that makes a spreadsheet a spreadsheet, and never a grid-shaped
interactive data application.

## Architecture

```
trellis/
  lexer.py        tokenizes formula text (numbers, strings, cell refs,
                   ranges, operators, function names, booleans)
  parser.py        recursive-descent / Pratt parser -> AST
  ast_nodes.py      Literal, CellRef, RangeRef, BinOp, UnaryOp, FuncCall, SheetRef
  functions.py     builtin function library (SUM/AVERAGE/COUNT/COUNTA/MIN/MAX/
                   IF/AND/OR/NOT/CONCAT/ROUND/ABS/SQRT/VLOOKUP/...)
  evaluator.py     AST -> value, given a cell-value lookup callback;
                   produces typed errors (#DIV/0!, #REF!, #VALUE!, #NAME?)
  depgraph.py      dependency DAG: add/remove edges on formula (re)parse,
                   topological dirty-set computation, Tarjan-based cycle
                   detection -> #CIRCULAR!
  sheet.py         Sheet (grid of Cells) + Workbook (named sheets, cross-
                   sheet refs like `Sheet2!A1`), the public recalculation API
  csvio.py         CSV import/export (values only, and formula-preserving)
  history.py       undo/redo command stack over sheet edits
  chart.py         SVG bar/line chart renderer over a selected range
  server.py        stdlib http.server JSON API + static file serving
  cli.py           `trellis` CLI: repl/open/csv-import/csv-export/serve/demo
web/
  index.html       single-file grid UI (HTML/CSS/vanilla JS, no build step,
                   no client-side formula logic — every edit is a POST)
tests/
  ...              unit + property + differential tests
demo.sh            end-to-end walkthrough
```

## Feature list

**Required (core, must work end-to-end):**

1. **Formula parser + evaluator** — full recursive-descent parser for a real
   formula grammar (arithmetic `+ - * / ^`, unary minus, `%`, string
   concatenation `&`, comparisons `= <> < <= > >=`, parenthesized grouping,
   cell refs `A1`, absolute refs `$A$1`, ranges `A1:B10`, function calls with
   variadic args) evaluating to typed values (number/string/bool/error), with
   real error values (`#DIV/0!`, `#VALUE!`, `#REF!`, `#NAME?`) rather than
   Python exceptions leaking out.

2. **Dependency graph + incremental recalculation** — every formula's cell
   reads become DAG edges; editing a cell recomputes only the topologically-
   sorted set of cells reachable from it (verified by an instrumented
   "how many cells actually recomputed" counter — an edit to a leaf cell in
   a 1,000-cell sheet must not re-run all 1,000 evaluators), and a genuine
   cycle (direct or indirect) is detected and reported as `#CIRCULAR!` on
   every cell in the cycle without crashing or hanging.

3. **Grid data model + CSV import/export** — a `Sheet` of typed cells
   (empty/number/string/bool/formula), CSV round-trip (import raw data,
   export computed values), and correct error propagation (a formula that
   reads an error-valued cell itself becomes an error, not a crash).

4. **Interactive server-backed browser spreadsheet UI** — a real grid you
   can click into, type a formula or value into, and see recalculate live;
   a formula bar showing the raw formula for the selected cell vs. its
   computed value; keyboard navigation (arrows/Enter/Tab); error cells
   visually flagged. Zero spreadsheet logic in the browser — every edit is
   a real HTTP round trip to the Python engine, mirroring this repo's
   Gambit/Formulate/Faraday server-backed pattern.

**Stretch:**

5. **Undo/redo** — a command-stack over cell edits (value/formula changes),
   `Ctrl+Z` / `Ctrl+Y` in the UI, verified to restore not just the edited
   cell's raw content but the full recomputed downstream state.

6. **Charts** — an SVG bar/line chart rendered from a selected range,
   embedded live in the UI, updating when the underlying data changes.

7. **Multi-sheet workbooks** — named sheets inside one workbook with cross-
   sheet references (`Sheet2!A1`, `Sheet2!A1:B5`), sheet add/rename/delete,
   and dependency tracking that correctly spans sheet boundaries (including
   cross-sheet cycles).

Required features 1–4 are the floor for "this is an actual spreadsheet, not
a toy expression evaluator." If any required feature proves infeasible in
scope, REVIEW.md will document the substitution — none are expected to be.
