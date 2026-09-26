# Skein — a from-scratch property-graph database

## Concept

A genuinely new domain for this repo. Prior "from scratch database" builds
picked the relational model (PicoSQL: SQL over a paged B+tree) or a plain
key-value model (Strata: an LSM-tree). Neither speaks the shape of data that
is *naturally a graph* — social networks, dependency graphs, road networks,
recommendation graphs, org charts — where the interesting queries are
multi-hop traversals ("friends of friends who also like X") that are
brutally awkward as SQL joins and pointless as key-value lookups. Skein is a
**property graph database**: nodes with labels and key/value properties,
directed typed edges with their own properties, a small Cypher-inspired
declarative query language with real pattern matching, a cost-aware query
planner that chooses indexes over full scans, classic graph algorithms
(BFS, Dijkstra, PageRank, connected components) with real convergence/
correctness properties to verify against, and durable ACID-ish storage with
crash recovery — the same "actually durable, actually crash-tested" bar
PicoSQL and Strata set for this repo's storage-engine lineage.

## Why it's interesting

- **New shape of query.** Every prior "engine" in this repo (PicoSQL's
  relational planner, the four full-text search engines, VecNN's vector
  index) answers "which rows/documents match." Skein answers "which
  *paths* connect these things" — a structurally different query shape
  (graph pattern matching + traversal) that needs its own execution model,
  not a join planner in disguise.
- **Strong, cheap ground truth.** Every algorithm here has a well-known
  brute-force or closed-form check: BFS shortest path can be verified
  against exhaustive all-pairs search on small graphs; PageRank's fixed
  point can be verified by direct linear-algebra solve (I turn the power
  iteration into a linear system and Gauss-Seidel-solve it independently);
  connected components against a naive O(V+E) flood fill written a
  completely different way. That means bugs are *provable*, not just
  "looked right on one example" — the same discipline this repo's SAT
  solvers and CDCL builds have used to good effect.
- **A real declarative query language, not just an API.** Parsing pattern
  syntax like `(a:Person)-[:KNOWS]->(b:Person)` into a graph-matching plan
  is a genuinely different parsing/execution problem than the SQL
  planner PicoSQL built, or the boolean/phrase query languages the search
  engines built — patterns bind variables across multiple graph elements
  simultaneously, and the planner has to decide which anchor to start
  matching from.

## Architecture

```
skein/
  storage.py    — Graph: nodes/edges as dicts of dataclasses, in-memory
                  authoritative state + an on-disk WAL (CRC32-checked,
                  fsynced) of every mutation, transaction begin/commit/
                  rollback framing, snapshot + WAL-replay recovery.
  index.py      — label index (label -> set[node_id]) and property
                  indexes (label, prop) -> sorted (value, id) list for
                  equality + range lookups, kept in sync with every write.
  query/
    lexer.py    — tokenizer for SkeinQL (Cypher-subset).
    parser.py   — recursive-descent parser -> AST (MatchClause, Pattern,
                  WhereExpr, ReturnClause, Create/Set/Delete clauses).
    planner.py  — turns a MATCH pattern into an ordered plan: pick the
                  cheapest anchor (indexed label/property beats full
                  scan), then expand edges hop by hop.
    executor.py — runs the plan against Graph + indexes, evaluates WHERE
                  predicates and RETURN projections, applies CREATE/SET/
                  DELETE mutations inside a transaction.
  algorithms.py — BFS shortest path, Dijkstra (weighted), PageRank (power
                  iteration to convergence), connected components
                  (union-find), each with an independent brute-force/
                  closed-form oracle used in tests.
  cli.py        — `skein` command: init/shell/query/import/algo/viz/demo.
viz/            — self-contained HTML/Canvas force-directed graph
                  visualizer (no build step, no CDN), fed a JSON export;
                  can highlight a query's matched subgraph.
tests/          — unit + property/oracle tests for every module above.
demo.sh         — end-to-end walkthrough exercising every feature.
```

## Feature list

### Required (4)

1. **Durable property-graph storage engine.** Nodes (labels + typed
   properties) and directed typed edges (own properties) with a real
   on-disk format: an append-only, CRC32-checked, fsynced write-ahead log
   of every mutation plus periodic snapshotting, and recovery that
   replays the WAL from the last snapshot — demonstrated by killing the
   process mid-write and reopening to find exactly the committed state.

2. **SkeinQL: a Cypher-inspired declarative query language.** Real pattern
   matching (`MATCH (a:Label)-[:TYPE]->(b:Label2)`), `WHERE` predicates
   over node/edge properties, `RETURN` projections with `ORDER BY`/`LIMIT`,
   and mutation clauses (`CREATE`, `SET`, `DELETE`/`DETACH DELETE`) — a
   lexer, recursive-descent parser, and a real executor, not a thin
   wrapper over Python dict comprehensions.

3. **Query planner with real indexes.** A label index and per-(label,
   property) indexes (sorted for range queries, hash for equality) that
   the planner consults to pick the cheapest starting point for a MATCH
   instead of always scanning every node; measurably faster than a full
   scan on a graph large enough for the difference to show, with a
   fallback path proven to return identical results either way.

4. **Graph algorithms library with independent correctness oracles.** BFS
   unweighted shortest path, Dijkstra weighted shortest path, PageRank
   (power iteration), and connected components — each cross-checked
   against a brute-force or closed-form oracle written with no shared
   code, the same standard this repo's SAT solvers hold UNSAT proofs to.

### Stretch (2+)

5. **Interactive HTML graph visualizer.** A self-contained force-directed
   Canvas graph view (no server logic needed once exported, but can also
   be served live) that renders the real graph, lets you click a node for
   its labels/properties, and highlights the exact subgraph a SkeinQL
   query matched.

6. **Transactions with crash recovery.** `BEGIN`/`COMMIT`/`ROLLBACK`
   framing around groups of mutations in the WAL, so an aborted or
   never-committed transaction is provably invisible after a simulated
   crash-and-reopen, the same crash-safety bar PicoSQL's rollback journal
   and Strata's WAL set.

## Where a human could take this next

Multi-database transactions, a cost-based join-order optimizer for
multi-hop patterns, variable-length path patterns (`-[:KNOWS*1..3]->`),
a real B-tree-backed disk index instead of in-memory sorted lists, or a
Bolt-like binary wire protocol for a real client/server deployment.
