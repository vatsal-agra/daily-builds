# PicoSQL — Adversarial Review (Phase 3)

I attacked my own engine two ways: (a) **differential testing** — ran 22 SELECT
queries (joins, group-by, having, null handling, index paths, like, distinct,
limit/offset, empty-aggregate) against the stdlib `sqlite3` module on identical
data and diffed results; and (b) **edge-case probing** of error paths,
atomicity, oversized rows, PK collisions, and parser corner cases.

The differential suite passed 22/22 immediately. The probing found four real
issues, all fixed below. A fresh run of the same probes now hits none of them.

## Findings & fixes

### F1 — `ORDER BY <integer>` silently mis-sorts (correctness bug)
`SELECT name, n FROM t ORDER BY 2 DESC` returned rows in input order instead of
sorting by the 2nd output column. The integer literal was evaluated as a
constant, so every sort key was equal and the sort was a no-op — a *silent wrong
answer*, the worst kind. SQLite supports positional ORDER BY.
**Fix:** in ORDER BY resolution, a bare integer literal *N* now binds to the
*N*-th output column's expression (1-based), matching SQLite.

### F2 — `IN (...)` / `NOT IN` not implemented (missing feature, bad error)
`WHERE id IN (1,2)` failed with the misleading "unexpected trailing input"
because `IN` was a reserved keyword the parser never consumed.
**Fix:** added `expr IN (v1, v2, ...)` and `expr NOT IN (...)` to the parser
(new `InList` AST node) and a NULL-aware evaluator (unknown/3-valued logic, so
`x IN (1, NULL)` is NULL when `x` matches nothing).

### F3 — `RowTooLarge` leaked as a storage-layer exception (UX)
Inserting a value bigger than a page raised `picosql.btree.RowTooLarge`, breaking
the clean `DBError` contract callers rely on.
**Fix:** the INSERT path now catches `RowTooLarge` and re-raises it as a
`DBError` with a clear message; the database remains fully usable afterwards.

### F4 — INSERT was not statement-atomic inside an explicit transaction
In autocommit a failed multi-row INSERT rolled back fine (verified), but inside
`BEGIN … COMMIT` it wrote rows one at a time, so a value error on row 3 of 5
left rows 1–2 applied (the user would have to `ROLLBACK` the whole txn).
**Fix:** INSERT now does a full **validate + encode pass for every row first**
(arity, type coercion, PK collisions incl. duplicates *within the batch*) and
only writes to the tree once all rows are known-good. INSERT is now atomic in
both autocommit and explicit transactions. (UPDATE/DELETE already gathered all
changes before applying, so they were already statement-atomic.)

## Things I checked that were already correct
- Empty-table aggregates: `COUNT`→0, `SUM/AVG/MIN/MAX`→NULL (matches SQLite).
- NULLs in GROUP BY keys, WHERE, and ORDER BY (NULLs sort first).
- PK collision on INSERT and on UPDATE-that-moves-a-PK both rejected.
- Autocommit atomicity: a failed statement leaves the table count unchanged.
- Crash-safe rollback journal: ROLLBACK leaves the file byte-for-byte identical
  (verified by MD5); COMMIT persists across reopen.
- B+tree correctness under 5000 randomized ops vs a dict oracle, incl. many node
  splits, range scans, deletes, and durability across reopen.

## Known, documented limitations (not bugs)
- One index per table (the PK/rowid B+tree); no user-defined secondary indexes.
- Rows must fit in one 4 KB page (no overflow pages); oversized → clear error.
- Deletes don't merge underfull nodes; dropped tables/pages aren't reclaimed.
- `COUNT(DISTINCT x)` and correlated subqueries are out of scope.
