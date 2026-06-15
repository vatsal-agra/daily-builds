# PicoSQL

A **relational database engine written from scratch in pure Python 3 (stdlib
only)**. Not a wrapper around `sqlite3`, not a dict pretending to be a table —
SQL text goes in one end, gets tokenized, parsed into an AST, planned into an
execution tree, and run against a **durable, paged B+tree stored in a single
file on disk**. Close the process, reopen it, your data is still there in the
same binary file format.

```
$ python3 -m picosql shop.picodb
PicoSQL 1.0.0 — type .help for commands, .exit to quit
picosql> CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER);
CREATE TABLE users
picosql> INSERT INTO users (name, age) VALUES ('Ada', 36), ('Bob', 40);
INSERT 2
picosql> SELECT name, age FROM users WHERE age >= 18 ORDER BY age DESC;
┌──────┬─────┐
│ name │ age │
├──────┼─────┤
│ Bob  │  40 │
│ Ada  │  36 │
└──────┴─────┘
(2 rows)
```

## What it is

A complete (if intentionally minimal) database stack, layer by layer:

| Layer | File | What it does |
|------|------|--------------|
| Storage | `pager.py` | 4 KB pages over a single file, write-back cache, page allocation, `fsync`, and a **crash-safe rollback journal** |
| Index/heap | `btree.py` | B+tree keyed by 64-bit rowid: search, range scan via leaf sibling pointers, insert with real **leaf & internal node splits**, delete |
| Encoding | `types.py` | type-tagged binary row (de)serialization (INTEGER/REAL/TEXT/NULL) |
| Catalog | `catalog.py` | table schemas stored *in their own B+tree* (durable DDL) |
| Lexer | `tokenizer.py` | hand-written SQL tokenizer with source positions |
| Parser | `parser.py` | recursive-descent parser → AST, with **positioned caret errors** |
| Planner | `planner.py` | AST → operator tree; **index selection** (seek/range vs scan) |
| Executor | `executor.py` | Volcano pull operators; expressions, joins, aggregates, sort |
| Engine | `database.py` | catalog, DML, transactions, autocommit |
| Shell | `repl.py` / `cli.py` | interactive REPL with pretty tables + dot-commands |

## How to run

No dependencies — Python 3.8+ only.

```bash
# interactive shell on a durable file (created if missing)
python3 -m picosql mydata.picodb

# run statements and exit
python3 -m picosql -c "CREATE TABLE t (id INTEGER PRIMARY KEY, v TEXT); \
                       INSERT INTO t (v) VALUES ('hi'); SELECT * FROM t;"

# in-memory (discarded on exit)
python3 -m picosql

# full feature tour
bash demo.sh

# test suite (22 tests incl. sqlite3 differential + crash recovery)
python3 -m unittest discover tests
```

As a library:

```python
from picosql import Database
db = Database("shop.picodb")
db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
db.execute("INSERT INTO users (name, age) VALUES ('Ada', 36)")
res = db.execute("SELECT name, age FROM users WHERE age > 18 ORDER BY age DESC")
print(res.columns, res.rows)   # ['name', 'age'] [('Ada', 36)]
db.close()
```

## Feature list

**Required (core)**
1. **Durable paged B+tree storage** — single-file DB, 4 KB pages, header page,
   page allocation, B+tree with real node splits and ordered leaf-linked range
   scans, write-back cache + `fsync`. Survives process restart.
2. **SQL front-end** — tokenizer + recursive-descent parser for `CREATE TABLE`,
   `INSERT`, `SELECT`, `UPDATE`, `DELETE`, `DROP TABLE`, with positioned,
   human-readable syntax errors.
3. **SELECT executor** — `*`/expression projection, `WHERE` with full
   boolean/comparison/arithmetic evaluation and 3-valued NULL logic, multi-key
   `ORDER BY` (ASC/DESC, positional, NULLs first), `LIMIT`/`OFFSET`, `DISTINCT`.
4. **Aggregation + JOIN** — `GROUP BY` with `COUNT/SUM/AVG/MIN/MAX`, `HAVING`,
   and inner `JOIN ... ON`.

**Stretch (all implemented)**
5. **Interactive REPL** — box-drawn result tables, multi-line entry, and
   dot-commands: `.tables`, `.schema`, `.import` (CSV), `.dump`, `.help`.
6. **Query planner with index selection + `EXPLAIN`** — turns `WHERE pk = c` /
   range predicates into B+tree IndexSeek/IndexRange, peeling those conjuncts
   out and leaving the rest as a residual Filter; `EXPLAIN` prints the plan.
7. **Transactions** — `BEGIN`/`COMMIT`/`ROLLBACK` with a page-level rollback
   journal; an interrupted commit is rolled back on the next open (verified by a
   simulated-crash test), and `ROLLBACK` leaves the file byte-for-byte identical.

Plus: scalar functions (`ABS`, `LENGTH`, `UPPER`, `LOWER`, `ROUND`, `COALESCE`),
`IN`/`NOT IN`, `LIKE`, `INTEGER PRIMARY KEY` rowid aliasing with autoincrement,
and statement-level atomicity (a failed multi-row INSERT changes nothing).

## Why I chose this today

The two previous daily builds (a procedural world generator and a regex engine)
both leaned on a single-file HTML visualizer. A database is a deliberately
different shape of project — a *storage-engine / language-implementation* stack
whose deliverable is a CLI — and it's one of the canonical "iceberg" programs:
the surface is `SELECT * FROM t`, but underneath sit a pager, a self-balancing
on-disk tree with node splits, a parser, a planner that chooses between an index
seek and a scan, and a journal that has to make a half-written commit vanish
cleanly on a crash. Getting all of those layers to agree — and proving it by
diffing 21 queries against real SQLite and simulating a crash mid-commit — is a
satisfyingly complete systems exercise to do in a day.

## Where a human could take this next
- **Secondary indexes** — generalize the catalog's one B+tree per table to
  user-defined `CREATE INDEX` trees keyed by arbitrary columns, and teach the
  planner to choose among them with simple statistics.
- **Overflow pages** so rows can exceed a single 4 KB page.
- **Node merging on delete** + a free-page list so the file reclaims space.
- **A WAL** (write-ahead log) instead of a rollback journal for better
  concurrency, plus reader/writer locks for multi-connection use.
- **Richer SQL** — subqueries, `LEFT/OUTER JOIN`, `CASE`, `ORDER BY` on
  expressions of aggregates, `COUNT(DISTINCT …)`, and prepared statements with
  bound parameters.
- A **cost-based optimizer** that reorders joins.

## Design notes & honest limits
- One index per table (the PK/rowid B+tree); no secondary indexes yet.
- Rows must fit in one 4 KB page; oversized values raise a clear error.
- Deletes free the cell but don't merge underfull nodes; dropped tables/pages
  aren't reclaimed.
- Single-threaded, single-connection.

See [PLAN.md](PLAN.md) for the original design and [REVIEW.md](REVIEW.md) for the
adversarial review (4 bugs found and fixed, including a silent `ORDER BY <int>`
mis-sort).
