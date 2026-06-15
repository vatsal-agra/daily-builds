# PicoSQL

A relational database engine written from scratch in pure Python 3 (stdlib only):
SQL text → tokenizer → parser → planner → executor over a **durable, paged B+tree**
on disk.

> Status: **Phase 5 (verification) complete.** 22-test suite green — including a
> 4000-op B+tree oracle, crash-recovery of the rollback journal, and a 21-query
> differential suite cross-checked against the stdlib `sqlite3`. Run the suite
> with `python3 -m unittest discover tests` or the full feature tour with
> `bash demo.sh`. All 4 required + 3 stretch features are in.

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
