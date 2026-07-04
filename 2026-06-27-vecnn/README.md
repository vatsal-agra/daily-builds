# VecNN — From-Scratch Vector Search Engine

A pure-Python approximate nearest-neighbour (ANN) library built from scratch,
implementing the full HNSW paper (Malkov & Yashunin 2018) plus LSH with
multi-probe, three distance metrics, a recall benchmarking harness, JSON
persistence, metadata filtering, and a self-contained HTML visualizer.

## Why this?

Vector search is the backbone of modern RAG pipelines, recommender systems,
and semantic search — yet it's treated as a black box.  Building it from
scratch forces every design decision to be made consciously: how levels are
assigned, how the greedy graph search works, why `ef_construction` trades
speed for recall, what multi-probe LSH actually does to recall curves.

## Quick start

```bash
cd 2026-06-27-vecnn
pip install numpy          # only dependency

# Run the full demo (exercises every feature end-to-end, ~1 min)
bash demo.sh

# Run unit tests (85 tests)
python -m pytest tests/ -q
```

## CLI usage

```bash
VECNN="python -m vecnn.cli"

# Insert vectors from a JSONL file
$VECNN insert my_coll.json vectors.jsonl --dim 128 --metric cosine

# Search
$VECNN search my_coll.json query.json -k 10

# Recall benchmark (sweeps ef values)
$VECNN bench my_coll.json -k 10 --n-queries 50

# Head-to-head: HNSW vs LSH vs exact
$VECNN compare my_coll.json -k 10 --n-queries 50

# Collection info
$VECNN info my_coll.json

# Generate self-contained HTML visualizer
$VECNN viz my_coll.json --out graph.html
```

## Feature tour

### 1. HNSW index (`vecnn/hnsw.py`)

Full implementation of all 5 algorithms from the paper:

- **Algorithm 1** — `insert()`: geometric level assignment, greedy search per
  layer, bidirectional edge linking, heuristic neighbour selection (Algorithm 3)
- **Algorithm 2** — `_search_layer()`: beam-search with dynamic candidate set,
  batched numpy distance computation for speed
- **Algorithm 4** — `search()`: multi-layer descending search with configurable
  `ef` parameter
- Lazy deletion (`delete()` marks nodes as tombstoned without rebuilding)
- Parameters: `M` (max edges/layer), `M0=2M` (layer 0), `ef_construction`,
  `ef_search`

```python
from vecnn.hnsw import HNSWIndex

idx = HNSWIndex(dim=128, metric="cosine", M=16, ef_construction=200)
idx.insert(vector, metadata={"source": "doc42"})
results = idx.search(query, k=10, ef=50)  # [(id, distance, metadata), ...]
```

### 2. Distance metrics (`vecnn/distance.py`)

Three metrics, each with a scalar and a batched (vectorised) variant:

| Metric | Formula | Use case |
|---|---|---|
| `cosine` | `1 - cos(a, b)` | Text / normalised embeddings |
| `euclidean` | `‖a - b‖₂` | Image features |
| `inner_product` | `-(a · b)` | Unnormalised embeddings |

The batch variants (`cosine_distance_batch`, etc.) are used internally in
`_search_layer()` to avoid per-vector Python overhead.

### 3. Persistence (`vecnn/collection.py`)

```python
from vecnn.collection import Collection

coll = Collection("my_index", dim=128, metric="cosine")
coll.add_from_jsonl("vectors.jsonl")   # {"vector": [...], "metadata": {...}}
coll.save("index.json")

loaded = Collection.load("index.json")
loaded.search(query, k=5)
```

Both HNSW and LSH indexes round-trip through JSON without losing state.
Delete operations persist correctly: deleted IDs are absent after reload.

### 4. Recall benchmarking (`vecnn/bench.py`)

```python
from vecnn.bench import benchmark, exact_knn, recall_at_k

# Sweep ef values, measuring recall@k and QPS
results = benchmark(idx, query_vecs, all_vecs, all_ids, k=10,
                    ef_values=[10, 50, 100, 200, 400])
```

`exact_knn` uses `np.argpartition` for O(n) oracle answers.
`recall_at_k` measures |approx ∩ true| / k.

### 5. LSH multi-probe (`vecnn/lsh.py`)

SimHash (random hyperplane projections) with configurable tables and bits.
Multi-probe LSH checks neighbouring buckets by flipping bits of the hash code:

| n_probes | Buckets checked per table | Effect |
|---|---|---|
| 1 | 1 (exact) | Low recall, fastest |
| 2 | 1 + n_bits | Moderate recall |
| 3 | 1 + n_bits + C(n_bits,2) | High recall |

Demo result at n_bits=8, n_tables=10 on 300 dim-32 vectors:

```
lsh (1-probe)  recall@10 = 0.19
lsh (2-probe)  recall@10 = 0.75
lsh (3-probe)  recall@10 = 0.99
```

### 6. HTML visualizer (`vecnn/viz.py`)

`generate_html(idx, query=q, query_k=10)` returns a single self-contained
HTML file (~250 KB) with:

- Layer selector (click to see each HNSW layer)
- PCA-projected node positions (2-component SVD)
- Animated search walk (step through beam-search decisions)
- Pan / zoom
- Hover tooltips showing node ID, layer, distance to query

### 7. Metadata filtering

Any dict can be attached to a vector at insert time.  Filtering is an AND
match on key-value pairs:

```python
coll.search(query, k=10, filter_expr={"category": "science", "lang": "en"})
```

## Architecture

```
vecnn/
  distance.py   # scalar + batch distance functions
  hnsw.py       # HNSW index (Algorithms 1-5)
  lsh.py        # SimHash index with multi-probe
  bench.py      # exact oracle + recall + QPS sweep
  collection.py # high-level wrapper (add/search/save/load/delete/filter)
  viz.py        # self-contained HTML graph visualizer
  cli.py        # 7 CLI subcommands
tests/
  test_hnsw.py          # 30+ HNSW tests
  test_lsh.py           # 20+ LSH tests
  test_collection.py    # collection + persistence tests
  test_bench.py         # benchmarking harness tests
demo.sh                 # end-to-end demo (D1–D9)
```

## Verification

```
85 tests passing
All demo checks (D1–D9) passing
```

Key recall numbers at runtime:
- HNSW recall@10 at ef=40: **1.000** (300 dim-32 vectors)
- LSH (3-probe) recall@10:  **0.988** (same dataset)
- HNSW recall@5 at ef=200:  **≥ 0.9** (300 vectors, any seed)

## Where a human could take this next

- **SIMD/Cython acceleration** — the inner loops of `_search_layer` and
  `cosine_distance_batch` are the hot path; Cython or `numba.jit` would give
  5–20× speedup with minimal API changes
- **Disk-backed index** — memory-mapped numpy arrays + a small B-tree for
  the node table would support billion-scale datasets
- **Filtered HNSW** — integrate the filter predicate into the beam-search
  expansion instead of post-filtering; avoids recall loss when the filter
  is selective
- **Product quantisation** — compress stored vectors from float64 to 8 bytes
  with PQ codes; dramatically reduces memory while keeping recall high
- **gRPC server** — wrap the Collection API in a gRPC service for
  language-agnostic access and concurrent clients
- **Persistent WAL** — write-ahead log for crash-safe incremental updates
  without full index rewrite
