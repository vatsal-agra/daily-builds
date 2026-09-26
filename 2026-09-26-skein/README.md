# Skein

A from-scratch property-graph database: durable WAL-backed storage,
**SkeinQL** (a Cypher-inspired declarative query language with real
pattern matching), an index-aware query planner, and a graph algorithms
library (BFS, Dijkstra, PageRank, connected components) with independent
correctness oracles. See [PLAN.md](PLAN.md) for the full design rationale.

**Status: Phase 3 (adversarial review) complete — 8 real bugs found and
fixed (see [REVIEW.md](REVIEW.md)), 84/84 tests green, `demo.sh` green.**
Stretch features (visualizer, crash-recovery demo) come next.

## Quickstart

```bash
cd 2026-09-26-skein
python3 -m skein.cli init mydb
python3 -m skein.cli query mydb "CREATE (a:Person {name: 'Alice', age: 30})"
python3 -m skein.cli query mydb "CREATE (a:Person {name: 'Alice'}) CREATE (a)-[:KNOWS]->(b:Person {name: 'Bob'})"
python3 -m skein.cli query mydb "MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN a.name, b.name"
python3 -m skein.cli shell mydb          # interactive REPL
python3 -m skein.cli demo                # narrated showcase, scratch DB
./demo.sh                                 # full test suite + CLI walkthrough
```

## SkeinQL at a glance

```cypher
MATCH (a:Person)-[:KNOWS]->(b:Person)
WHERE a.age > 25 AND b.city = 'NYC'
RETURN a.name, b.name
ORDER BY a.name
LIMIT 10

CREATE (a:Person {name: 'Grace'})-[:WORKS_AT]->(c:Company {name: 'Acme'})

MATCH (a:Person {name: 'Grace'}) SET a.age = 34

MATCH (a:Person {name: 'Grace'}) DETACH DELETE a
```

## CLI

- `skein init <path>` -- create an empty database
- `skein query <path> "<SkeinQL>"` [`--explain`] -- run one statement
- `skein shell <path>` -- interactive REPL
- `skein import <path> --nodes nodes.csv [--edges edges.csv]` -- bulk load
- `skein algo pagerank|shortest-path|components <path> ...`
- `skein demo` -- narrated end-to-end showcase on a scratch database

## Known scope limits

SkeinQL matches a single connected path pattern per `MATCH` (no
comma-separated multi-pattern joins / cartesian products), and has no
variable-length hops (`-[:KNOWS*1..3]->`) or `GROUP BY` beyond a
single top-level `COUNT(*)`. These are documented boundaries of the MVP
query language, not bugs -- see PLAN.md's "where a human could take this
next."

## Feature list

See [PLAN.md](PLAN.md) for the full required/stretch breakdown.

## Why this project

See [PLAN.md](PLAN.md#why-its-interesting).
