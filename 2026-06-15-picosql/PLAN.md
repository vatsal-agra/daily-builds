# PicoSQL — Plan

## Concept
A **relational database engine written from scratch in pure Python 3 (stdlib only)**.
Not a wrapper around `sqlite3`, not an in-memory dict pretending to be a table — a
*real* database: SQL text goes in one end, gets tokenized, parsed into an AST,
planned into an execution tree, and run against a **durable, paged B+tree stored in
a single file on disk**. Close the process, reopen it, your data is still there,
laid out in the same binary file format.

## Why it's interesting
A database is one of the canonical "iceberg" programs: the API is `SELECT * FROM t`
but underneath sits a storage manager, a page cache, a self-balancing tree with node
splits, a recursive-descent parser, a query planner that decides between an index
seek and a full scan, and a transaction layer that has to make a half-finished
multi-row write disappear cleanly on rollback. Building all of those layers and
making them agree is a genuinely meaty systems exercise, and the result is a thing
you can actually *use* — a working SQL shell. It is also deliberately **different in
medium** from the two prior daily builds (procedural map generator, regex engine),
which both leaned on a single-file HTML visualizer; this one is a storage-engine /
language-implementation project whose deliverable is a CLI + REPL.

## Architecture
```
SQL text
  │
  ▼  tokenizer.py      hand-written lexer (keywords, idents, numbers, strings, ops)
tokens
  │
  ▼  parser.py         recursive-descent parser → AST (positioned errors)
AST  (CreateTable / Insert / Select / Update / Delete / Begin / Commit ...)
  │
  ▼  planner.py        AST → plan nodes; chooses SeqScan vs IndexSeek/IndexRange
plan tree (Scan → Filter → Join → Aggregate → Sort → Limit → Project)
  │
  ▼  executor.py       pull-based iterators ("Volcano" model) producing rows
rows
  │
  ▼  database.py       Database / Connection: catalog, txn boundaries, autocommit
  ▼
storage:  btree.py  (B+tree: search / insert-with-split / range-scan / delete)
          pager.py  (4 KB pages, write-back cache, header page, page allocation,
                     fsync on flush, rollback journal for transactions)
          types.py  (type-tagged binary row (de)serialization: INT/REAL/TEXT/NULL)
          catalog.py(persistent table catalog: schema, root page, next rowid)
```
Data model is **rowid tables** (à la SQLite): every table is a B+tree keyed by an
auto-incrementing 64-bit integer rowid; the leaf value is the serialized row.
`INTEGER PRIMARY KEY` aliases the rowid so primary-key lookups become O(log n)
B+tree seeks instead of full scans.

## Feature list

### Required (core)
1. **Durable paged B+tree storage** — single-file DB, 4 KB pages, header page, page
   allocation, a B+tree with real leaf/internal **node splits** and ordered
   range-scan via leaf sibling pointers, write-back page cache with `fsync`.
   Data survives process restart. (storage layer)
2. **SQL front-end** — tokenizer + recursive-descent parser for
   `CREATE TABLE`, `INSERT`, `SELECT`, `UPDATE`, `DELETE`, `DROP TABLE`,
   with **positioned, human-readable syntax errors** (caret under the bad token).
3. **SELECT executor** — projection (incl. `*` and expressions), `WHERE` with
   full boolean/comparison/arithmetic expression evaluation, `ORDER BY`
   (multi-key, ASC/DESC), `LIMIT`/`OFFSET`. Volcano pull iterators.
4. **Aggregation + JOIN** — `GROUP BY` with `COUNT/SUM/AVG/MIN/MAX` (and
   `HAVING`), and inner `JOIN ... ON` between tables.

### Stretch
5. **Interactive REPL** with dot-commands (`.tables`, `.schema`, `.import`,
   `.dump`, `.help`), pretty box-drawn result tables, and multi-line statement
   entry — a usable SQL shell.
6. **Query planner with index selection + `EXPLAIN`** — recognises
   `WHERE pk = c` / `pk < c` etc. and plans a B+tree **IndexSeek/IndexRange**
   instead of a SeqScan; `EXPLAIN <query>` prints the chosen plan tree.
7. **Transactions** — `BEGIN` / `COMMIT` / `ROLLBACK` with a page-level rollback
   journal so a failed or aborted multi-statement transaction leaves the file
   byte-identical to before it started.

## Verification plan
- Unit tests per layer: pager round-trip + restart durability; B+tree against a
  Python dict oracle over thousands of randomized insert/lookup/range ops to force
  many node splits; type serialization round-trip.
- End-to-end SQL tests whose **expected results are cross-checked against the
  stdlib `sqlite3` module** running the same queries (differential testing).
- Persistence test: write in one process, read back in a fresh `Database` object.
- Transaction test: rollback restores byte-identical file.
- `demo.sh` that drives the CLI/REPL through every feature.

## Known scoping decisions (honest limits)
- Single-column rowid B+tree per table (no user-defined secondary indexes); the
  one index is the primary-key/rowid tree. Documented, not hidden.
- Row must fit in a page (~4 KB); oversized values raise a clear error rather than
  silently truncating (no overflow-page chains).
- Deletes free the cell but do not merge/rebalance underfull nodes (tree stays
  correct, may be less compact). Documented.
