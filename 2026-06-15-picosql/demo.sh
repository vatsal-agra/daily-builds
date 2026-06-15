#!/usr/bin/env bash
# PicoSQL end-to-end demo: drives the CLI through every feature.
set -euo pipefail
cd "$(dirname "$0")"

DB="$(mktemp -u).picodb"
CSV="$(mktemp -u).csv"
trap 'rm -f "$DB" "$DB-journal" "$CSV"' EXIT

PY="python3 -m picosql"

echo "============================================================"
echo " PicoSQL demo — a from-scratch SQL engine on a B+tree"
echo "============================================================"

cat > "$CSV" <<'CSV'
name,age,city
Ada,36,Paris
Bob,40,Rome
Cy,19,Paris
Di,,Rome
Ed,25,Paris
CSV

echo; echo "## 1. Schema + durable storage (writes to $DB)"
$PY "$DB" -c "
CREATE TABLE users (id INTEGER PRIMARY KEY, name TEXT, age INTEGER, city TEXT);
CREATE TABLE orders (id INTEGER PRIMARY KEY, uid INTEGER, total REAL, status TEXT);
"

echo; echo "## 2. CSV import via the REPL .import dot-command"
printf '.import %s users\n.exit\n' "$CSV" | $PY "$DB" >/dev/null
$PY "$DB" -c "SELECT * FROM users ORDER BY id;"

echo; echo "## 3. INSERT + SELECT with WHERE / ORDER BY / LIMIT"
$PY "$DB" -c "
INSERT INTO orders (uid,total,status) VALUES (1,9.5,'paid'),(1,3.0,'paid'),(2,100.0,'open'),(5,7.25,'paid'),(2,5.0,'open');
SELECT name, age FROM users WHERE age IS NOT NULL ORDER BY age DESC LIMIT 3;
"

echo; echo "## 4. Aggregation + GROUP BY + HAVING"
$PY "$DB" -c "
SELECT city, COUNT(*) people, AVG(age) avg_age
FROM users GROUP BY city HAVING COUNT(*) >= 2 ORDER BY people DESC;
"

echo; echo "## 5. JOIN across tables"
$PY "$DB" -c "
SELECT u.name, COUNT(*) n_orders, SUM(o.total) spent
FROM users u JOIN orders o ON u.id = o.uid
GROUP BY u.name ORDER BY spent DESC;
"

echo; echo "## 6. Query planner: index seek/range vs full scan (EXPLAIN)"
$PY "$DB" -c "EXPLAIN SELECT * FROM users WHERE id = 3;"
$PY "$DB" -c "EXPLAIN SELECT * FROM users WHERE id >= 2 AND id < 5;"
$PY "$DB" -c "EXPLAIN SELECT * FROM users WHERE city = 'Paris';"

echo; echo "## 7. IN / NOT IN, DISTINCT, positional ORDER BY"
$PY "$DB" -c "
SELECT name FROM users WHERE id IN (1,3,5) ORDER BY 1;
SELECT DISTINCT city FROM users ORDER BY city;
"

echo; echo "## 8. Transactions: ROLLBACK leaves data untouched, COMMIT persists"
printf '%s\n' \
  "BEGIN;" \
  "DELETE FROM users;" \
  "SELECT COUNT(*) AS during_txn FROM users;" \
  "ROLLBACK;" \
  "SELECT COUNT(*) AS after_rollback FROM users;" \
  ".exit" | $PY "$DB"

echo; echo "## 9. Friendly, positioned syntax errors"
$PY "$DB" -c "SELECT * FORM users;" || true

echo; echo "## 10. Persistence — reopen the file in a fresh process"
$PY "$DB" -c "SELECT COUNT(*) AS rows_still_here FROM users;"

echo; echo "Demo complete."
