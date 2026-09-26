# Skein

A from-scratch **property-graph database**: durable WAL-backed storage,
**SkeinQL** (a Cypher-inspired declarative query language with real
pattern matching), an index-aware query planner, a graph algorithms
library with independent correctness oracles, an interactive HTML graph
visualizer, and ACID transactions proven crash-safe against a real
`kill -9`.

**Status: shipped.** 4/4 required features + 2/2 stretch features. 9 real
bugs found and fixed across adversarial review and verification (see
[REVIEW.md](REVIEW.md)). 93/93 tests green, `demo.sh` green end-to-end.

## What it is

Every prior "from-scratch database" build in this repo's history picked
either the relational model (a SQL engine over a paged B+tree) or a plain
key-value model (an LSM-tree). Neither speaks the shape of data that's
naturally a graph -- social networks, org charts, dependency graphs, road
networks -- where the interesting question is "which *paths* connect these
things," not "which rows match." Skein is a **property graph**: nodes
carry labels and typed properties, directed edges carry their own type and
properties, and SkeinQL lets you write real multi-hop pattern queries like

```cypher
MATCH (a:Person)-[:KNOWS]->(b:Person)-[:KNOWS]->(c:Person)
WHERE a.age > 25
RETURN a.name, c.name
```

instead of a chain of self-joins. See [PLAN.md](PLAN.md) for the full
design rationale and architecture.

## How to run it

```bash
cd 2026-09-26-skein

# quickstart
python3 -m skein.cli init mydb
python3 -m skein.cli query mydb "CREATE (a:Person {name: 'Alice', age: 30})"
python3 -m skein.cli query mydb "CREATE (a:Person {name: 'Alice'}) CREATE (a)-[:KNOWS]->(b:Person {name: 'Bob'})"
python3 -m skein.cli query mydb "MATCH (a:Person)-[:KNOWS]->(b:Person) RETURN a.name, b.name"

python3 -m skein.cli shell mydb            # interactive REPL
python3 -m skein.cli viz mydb --query "MATCH (a)-[:KNOWS]->(b) RETURN a.name, b.name"  # HTML visualizer
python3 -m skein.cli demo                  # narrated showcase on a scratch DB
python3 -m skein.cli crash-demo mydb2      # real kill -9 crash-recovery proof

./demo.sh                                   # full test suite + every CLI feature, end to end
python3 -m unittest discover -s tests -v    # just the tests
```

No dependencies beyond the Python 3 standard library for the engine and
CLI; the visualizer is self-contained HTML/Canvas/vanilla JS (no CDN, no
build step). Node + a headless Chromium (both pre-installed in this
environment) are used only to smoke-test the generated visualizer -- the
visualizer itself needs nothing but a browser to open the file.

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

## Full feature list

**Required:**

1. **Durable property-graph storage** -- nodes/edges with labels, types,
   and typed properties; a CRC32-checked, fsynced write-ahead log plus
   snapshotting; recovery that survives a real `kill -9` mid-transaction
   with the all-or-nothing guarantee intact (`skein/storage.py`).
2. **SkeinQL** -- a lexer, recursive-descent parser, and executor for a
   Cypher-inspired language: pattern matching, `WHERE`, `RETURN`/`ORDER
   BY`/`LIMIT`, `CREATE`/`SET`/`DELETE`/`DETACH DELETE`
   (`skein/query/{lexer,parser,ast,executor}.py`).
3. **Index-aware query planner** -- label and per-(label, property)
   indexes; the planner picks the cheapest anchor (indexed equality >
   label scan > full scan) from anywhere in a pattern, not just its first
   node, and index-backed vs. scan-backed execution are proven to agree
   (`skein/index.py`, `skein/query/planner.py`).
4. **Graph algorithms with independent oracles** -- BFS shortest path
   (checked against Floyd-Warshall), Dijkstra (checked against
   Bellman-Ford), PageRank (checked against a direct linear solve via
   hand-rolled Gaussian elimination, not just power-iteration convergence),
   connected components (checked against a from-scratch DFS flood fill)
   (`skein/algorithms.py`, `tests/test_algorithms.py`).

**Stretch (both shipped):**

5. **Interactive HTML graph visualizer** -- force-directed Canvas layout,
   drag/zoom/pan, click a node to inspect its labels and properties, and
   highlight exactly what a SkeinQL query matched (`skein/viz.py`).
6. **Transactions with real crash recovery** -- `BEGIN`/`COMMIT`/
   `ROLLBACK` framing in the WAL, verified two ways: a synthetic
   torn-write test that truncates the WAL mid-record
   (`tests/test_storage.py`), and a live demo that spawns a worker
   process, sends it a real `SIGKILL` mid-transaction, and proves the
   node count stays an exact multiple of the transaction batch size
   across every round (`skein crash-demo`, `skein/crash_worker.py`).

## CLI reference

- `skein init <path>` -- create an empty database
- `skein query <path> "<SkeinQL>"` [`--explain`] -- run one statement
- `skein shell <path>` -- interactive REPL
- `skein import <path> --nodes nodes.csv [--edges edges.csv]` -- bulk load
- `skein algo pagerank|shortest-path|components <path> ...`
- `skein viz <path> [--out FILE] [--query "<SkeinQL>"]` -- HTML visualizer
- `skein crash-demo <path> [--rounds N] [--batch N]` -- real kill-9 proof
- `skein demo` -- narrated end-to-end showcase on a scratch database

## Known scope limits

SkeinQL matches a single connected path pattern per `MATCH` (no
comma-separated multi-pattern joins / cartesian products), and has no
variable-length hops (`-[:KNOWS*1..3]->`) or `GROUP BY` beyond a single
top-level `COUNT(*)`. CSV import's type-sniffing turns a leading-zero
numeric string like `"007"` into the integer `7` (the same behavior
`pandas.read_csv` has by default). These are documented boundaries, not
bugs -- see REVIEW.md and "where a human could take this next" below.

## Why this project, today

This repo's history is dense with from-scratch systems and language
runtimes, but every "database" entry so far picked the relational or
key-value model. A property graph is a different enough shape of storage
and query problem -- pattern matching instead of joins, traversal
algorithms instead of aggregate scans -- to be worth a dedicated build,
and it comes with unusually strong, cheap ground truth: BFS/Dijkstra/
PageRank/components each have a well-known brute-force or closed-form
check that shares no code with the real implementation, so correctness
claims are provable rather than "looked right on one example." Building
the query planner also surfaced the kind of subtle correctness bug this
repo's reviews specifically watch for: an index-backed lookup and a full
scan of the exact same filter silently disagreeing on a boolean-vs-integer
property (fixed; see REVIEW.md finding #5) -- exactly the class of bug a
"just make it work" build would ship without ever noticing.

## Where a human could take this next

- Multi-pattern `MATCH` (comma-separated patterns / cartesian products)
  and variable-length hops (`-[:KNOWS*1..3]->`).
- Real `GROUP BY` / aggregate functions beyond the single top-level
  `COUNT(*)` this build supports honestly rather than faking.
- A disk-backed B-tree index instead of the current in-memory sorted list
  (fine up to the scale a single process can hold, not built for a
  data set larger than RAM).
- A cost-based join-order optimizer for multi-hop patterns with several
  equally-indexed anchors, instead of picking the single best-scoring one.
- A Bolt-like binary wire protocol for a real client/server deployment,
  rather than the current in-process/CLI-only usage.
