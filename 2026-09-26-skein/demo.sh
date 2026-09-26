#!/usr/bin/env bash
# End-to-end walkthrough of every Skein feature. Exits non-zero on any
# failure so it can gate CI-style verification.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

pass() { echo "  [OK] $1"; }
section() { echo; echo "== $1 =="; }

TMPDIR=$(mktemp -d)
cleanup() { rm -rf "$TMPDIR"; }
trap cleanup EXIT
DB="$TMPDIR/demo_db"

section "1. Unit test suite (storage, query language, algorithms, CLI)"
python3 -m unittest discover -s tests -v
pass "full test suite green"

section "2. Narrated end-to-end demo (storage durability, SkeinQL, planner, algorithms)"
python3 -m skein.cli demo
pass "skein demo completed"

section "3. CLI walkthrough: init"
python3 -m skein.cli init "$DB"
test -f "$DB.snapshot.json"
test -f "$DB.wal"
pass "init created snapshot + WAL files"

section "4. CLI walkthrough: CREATE / MATCH / RETURN / ORDER BY"
python3 -m skein.cli query "$DB" "CREATE (a:Person {name: 'Ada', age: 36})"
python3 -m skein.cli query "$DB" "CREATE (b:Person {name: 'Grace', age: 44})"
python3 -m skein.cli query "$DB" "MATCH (a:Person) RETURN a.name ORDER BY a.name"
pass "CREATE + MATCH + RETURN + ORDER BY work over the CLI"

section "5. CLI walkthrough: relationships + chain patterns + --explain"
python3 -m skein.cli query "$DB" "MATCH (a:Person {name: 'Ada'}) CREATE (a)-[:KNOWS {since: 1843}]->(b:Person {name: 'Charles'})"
python3 -m skein.cli query "$DB" "MATCH (a:Person)-[r:KNOWS]->(b:Person) RETURN a.name, b.name, type(r)"
python3 -m skein.cli query "$DB" "MATCH (a:Person {name: 'Ada'}) RETURN a.name" --explain
pass "relationship creation, pattern matching, and --explain all work over the CLI"

section "6. CLI walkthrough: SET / DELETE / DETACH DELETE"
python3 -m skein.cli query "$DB" "MATCH (a:Person {name: 'Ada'}) SET a.age = 37"
python3 -m skein.cli query "$DB" "MATCH (a:Person {name: 'Ada'}) RETURN a.age"
if python3 -m skein.cli query "$DB" "MATCH (a:Person {name: 'Ada'}) DELETE a" 2>/dev/null; then
  echo "expected DELETE without DETACH to fail on a connected node"; exit 1
fi
python3 -m skein.cli query "$DB" "MATCH (a:Person {name: 'Charles'}) DETACH DELETE a"
python3 -m skein.cli query "$DB" "MATCH (a:Person) RETURN a.name ORDER BY a.name"
pass "SET, DELETE-without-DETACH rejection, and DETACH DELETE all behave correctly"

section "7. CLI walkthrough: bulk import + graph algorithms"
NODES_CSV="$TMPDIR/nodes.csv"
EDGES_CSV="$TMPDIR/edges.csv"
cat > "$NODES_CSV" <<'EOF'
id,labels,name
1,Person,Alice
2,Person,Bob
3,Person,Carol
4,Person,Dave
EOF
cat > "$EDGES_CSV" <<'EOF'
src,dst,type,weight
1,2,KNOWS,1
2,3,KNOWS,4
1,3,KNOWS,10
3,4,KNOWS,1
EOF
IMPORT_DB="$TMPDIR/import_db"
python3 -m skein.cli init "$IMPORT_DB"
python3 -m skein.cli import "$IMPORT_DB" --nodes "$NODES_CSV" --edges "$EDGES_CSV"
python3 -m skein.cli algo shortest-path "$IMPORT_DB" --src 1 --dst 4
python3 -m skein.cli algo shortest-path "$IMPORT_DB" --src 1 --dst 3 --weighted
python3 -m skein.cli algo pagerank "$IMPORT_DB" --top 4
python3 -m skein.cli algo components "$IMPORT_DB"
pass "import + BFS/Dijkstra/PageRank/components all run over the CLI"

echo
echo "=== demo.sh: all sections passed ==="
