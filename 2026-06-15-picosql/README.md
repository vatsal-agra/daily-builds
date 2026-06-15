# PicoSQL

A relational database engine written from scratch in pure Python 3 (stdlib only):
SQL text → tokenizer → parser → planner → executor over a **durable, paged B+tree**
on disk.

> Status: **Phase 4 (stretch + polish) complete.** All 4 required features plus
> all 3 stretch features are in: interactive REPL, query planner with index
> selection + EXPLAIN, and transactions with a crash-safe rollback journal.

### Quick start
```bash
python3 -m picosql mydata.picodb       # interactive SQL shell (.help for commands)
python3 -m picosql -c "SELECT 1+1"     # run statements and exit
```
```python
from picosql import Database
db = Database("shop.picodb")           # durable single-file database
db.execute("CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER)")
db.execute("INSERT INTO users (name, age) VALUES ('Ada', 36), ('Bob', 40)")
r = db.execute("SELECT name, age FROM users WHERE age >= 18 ORDER BY age DESC")
print(r.columns, r.rows)
```
