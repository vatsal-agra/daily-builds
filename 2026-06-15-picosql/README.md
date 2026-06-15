# PicoSQL

A relational database engine written from scratch in pure Python 3 (stdlib only):
SQL text → tokenizer → parser → planner → executor over a **durable, paged B+tree**
on disk.

> Status: **Phase 2 (core build) complete.** The four required features work
> end-to-end: durable paged B+tree storage, the SQL tokenizer/parser, the SELECT
> executor (WHERE/ORDER BY/LIMIT/expressions), and aggregation + JOIN. Index
> selection, EXPLAIN, and transactions (BEGIN/COMMIT/ROLLBACK with a crash-safe
> rollback journal) are already in. See [PLAN.md](PLAN.md) for the design.

### What works so far
```python
from picosql import Database
db = Database("shop.picodb")          # durable single-file database
db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
db.execute("INSERT INTO users (name, age) VALUES ('Ada', 36), ('Bob', 40)")
r = db.execute("SELECT name, age FROM users WHERE age >= 18 ORDER BY age DESC")
print(r.columns, r.rows)
```
