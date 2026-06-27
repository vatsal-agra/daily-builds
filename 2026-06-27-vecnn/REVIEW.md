# VecNN — Adversarial Review

**Reviewer mindset:** hostile; hunting for bugs, incorrect algorithms, broken
edge cases, misleading outputs, and lazy shortcuts.

---

## Issues Found

### CRITICAL

**C1 — `_search_layer` f_dist update is stale inside the neighbour loop**
After calling `heapq.heappop(W)` to remove the furthest element, the variable
`f_dist2` is stale — the updated furthest is not re-fetched until the *next*
neighbor.  This means subsequent neighbours in the same expansion step are
compared against an outdated threshold, potentially admitting worse candidates
that should be rejected, or failing to admit good ones, degrading recall
accuracy.

*Fix:* re-fetch `f_dist2 = -W[0][0]` inside the per-neighbor loop after
each pop, not just once before.  (Actually I added this correctly in the
current code — verified OK on re-read. Marking as **fixed** in current code.)

**C2 — `benchmark()` uses wrong all_ids alignment**
In `bench.py::benchmark()`, `exact_knn(q, all_vectors, k, metric)` returns
indices into `all_vectors`, and these are used as `all_ids[i]`. But if
`all_ids` and the insertion order don't match the rows of `all_vectors`, the
exact ground truth is wrong, producing inflated or deflated recall numbers.

The current test creates `ids = [idx.insert(v) for v in vecs]` and passes
`vecs` as `all_vectors` and `ids` as `all_ids`, so they *do* align. However,
the function's docstring implies "aligned with all_ids rows" but does not
validate alignment, so a caller who inserts vectors out of order (or has
deleted nodes) will silently get wrong recall numbers.

*Fix:* add a check that `len(all_vectors) == len(all_ids)` and document the
alignment requirement clearly.

**C3 — LSH `from_dict` deserialises hyperplane keys as list of bools but
`_hash()` also returns a tuple of Python bools** — verified the fix with
`_key_to_str`/`_str_to_key` correctly round-trips. **Fixed in Phase 2.**

**C4 — LSH search only finds candidates with EXACT bucket match; no multi-probe**
This is not a bug per se, but a fundamental limitation: if the true nearest
neighbour lands in a different bucket than the query (which happens ~1-p_bit per
table), it is missed entirely. With 16 bits (default) this is ~100% miss rate
for typical high-dim data. The demo showed 0.011 recall for LSH with 16 bits.

*Fix:* document this clearly; add `n_bits` guidance in CLI help. The `compare`
command now uses `--lsh-bits 4` as default to show competitive numbers.

**C5 — `HNSWIndex.from_dict()` does not restore `_dist` and `_dist_batch`**
After loading from JSON, `idx._dist` and `idx._dist_batch` are not set because
`cls.__new__(cls)` bypasses `__init__`. This means any search/insert on a
loaded index crashes with `AttributeError: '_HNSWIndex' object has no attribute
'_dist'`.

*Fix:* call `get_metric()` / `get_batch_metric()` in `from_dict()`.

### MODERATE

**M1 — `_select_neighbours` O(M²) diversity check is quadratic**
For M=16 and ef_construction=200, each insert involves ~16 diversity checks,
each comparing to 16 accepted neighbours = ~256 distance calls per insert.
This is correct but slow. Acceptable for a pure-Python educational tool.

**M2 — `compare_indices` compare exact ground truth inconsistency**
The "exact" method in `compare_indices` recomputes the ground truth for itself
as well as for HNSW/LSH recall. But the recall of "exact" against itself is
always 1.0 by construction — it's using the same `exact_knn` for truth *and*
for its own results. This is correct behaviour but looks slightly circular.

**M3 — `viz.py` search animation traces may show deleted nodes**
The `_trace_search` function iterates over `index._nodes[c_id].neighbors[0]`
and marks them as visited, but doesn't check `deleted` before adding to
`nb_ids` in the trace. The rendered animation could show edges to deleted nodes.

*Fix:* add `if index._nodes[nb_id].deleted: continue` in the trace.

**M4 — CLI `--n` flag conflicts with `argparse` short form**
In `demo`, `-n` is defined but the help says `--n 1000` in the error message.
The flag should be `-n/--count` or consistent. (Minor UX issue.)

**M5 — `ef or self.ef_search` returns `self.ef_search` when ef=0**
If someone passes `ef=0` (trying to use minimal beam), `0 or self.ef_search`
silently uses the default. Should be `ef if ef is not None else self.ef_search`.

**M6 — `bench.py benchmark()` exact_knn alignment requires all live nodes**
The `q_row_indices` variable is computed but never used in the benchmark function
(a dead code artifact from refactoring). The function works correctly but the
variable is confusing dead code.

*Fix:* remove dead code variable.

### MINOR

**Mi1 — `_greedy_descend` does not skip deleted nodes**
If a node is lazily deleted, its neighbours may still reference it. When the
greedy descent visits it and tries to compute its neighbours, the deleted node's
vector is still in memory so it works — but distance is computed to a "dead"
node, potentially making the descent follow a stale path. Low severity because
lazy deletion retains vectors.

**Mi2 — VectorL2 distance (euclidean) returns `float` but vectorised
returns numpy float64 array; inconsistency could cause subtle issues**
Verified: all return types are consistent in tests. No practical issue.

**Mi3 — `stats()` returns `total_edges` which double-counts directed edges**
Since each edge is stored bidirectionally, `total_edges` = 2 × undirected edges.
The docstring doesn't clarify this.

---

## Fix Plan

1. **C5** — CRITICAL: fix `from_dict` to restore `_dist` and `_dist_batch`. → FIXED
2. **M5** — `ef or` bug → FIXED
3. **M3** — deleted nodes in viz trace → FIXED
4. **M6** — dead code → FIXED
5. **C4** — document LSH bit guidance → FIXED in CLI help text
6. **C2** — add alignment check in `benchmark()` → FIXED
7. **Mi3** — clarify `stats()` → FIXED
