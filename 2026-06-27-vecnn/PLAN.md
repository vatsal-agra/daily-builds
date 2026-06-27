# VecNN — From-Scratch Vector Search Engine

## Concept
VecNN is a from-scratch implementation of modern approximate nearest-neighbor
search algorithms, the core technology behind every production vector database
(Pinecone, Weaviate, Chroma, Qdrant). It implements HNSW (Hierarchical
Navigable Small World) — an elegant graph-based index with O(log n) search
time — plus LSH (Locality Sensitive Hashing) as an alternative approach,
benchmarks both against brute-force exact search, and ships an interactive
HTML visualization of the HNSW graph structure.

## Why It's Interesting
- HNSW is beautiful: skip-list meets navigable small world graph, layer
  selection via geometric distribution, greedy graph traversal with a
  beam, O(log n) query time with high practical recall
- Vector search is the infra layer of modern AI — RAG, semantic search,
  recommendation engines all run on this
- Nothing like it in the ledger: no graphs, no approximate algorithms,
  no similarity search
- Recall vs. speed tradeoff is a concrete, measurable demonstration

## Architecture

```
vecnn/
  distance.py     — cosine, euclidean, dot-product metrics
  hnsw.py         — HNSW index (Malkov & Yashunin 2018, Algorithms 1–5)
  lsh.py          — LSH index (random hyperplane projections)
  collection.py   — collection wrapper: metadata, persistence (JSON)
  bench.py        — brute-force oracle + recall@k + speed benchmarks
  viz.py          — self-contained HTML/JS/SVG graph visualizer
  cli.py          — CLI entry point (argparse, 7 subcommands)
```

## Feature List

### Required (4)
1. **HNSW Index** — full implementation of Malkov & Yashunin 2018:
   - Geometric layer assignment (ML = -ln(uniform()) * mL)
   - Algorithm 1: INSERT with layer-wise beam search + heuristic pruning
   - Algorithm 2: SEARCH-LAYER (core beam search)
   - Algorithm 3: SELECT-NEIGHBORS-HEURISTIC (distance-diversity)
   - Algorithm 4: K-NN-SEARCH (top-level entry, multi-layer descent)
   - DELETE via lazy tombstoning + neighbor re-linking
   - Configurable M (connections/layer), ef_construction, ef_search

2. **Distance Metrics** — pluggable metric system:
   - Cosine similarity (with L2-normalization cache)
   - L2 Euclidean distance
   - Inner product / dot-product
   - All metrics verified against scipy/numpy ground truth

3. **Persistence** — save/load collections to disk:
   - JSON format with version tag, metric, dimension, M, ef params
   - Exact round-trip: loaded index produces identical search results
   - Per-vector metadata dict (arbitrary key/value) preserved

4. **Recall Benchmarking** — quantitative evaluation:
   - Brute-force exact k-NN oracle (no approximation)
   - recall@k at multiple ef values (tradeoff curve)
   - QPS (queries per second) measurement
   - Side-by-side HNSW vs LSH vs exact comparison table

### Stretch (3)
5. **LSH Index** — random hyperplane projections for cosine similarity:
   - L random hyperplanes, H hash tables, Hamming distance lookup
   - Configurable tables (T) and bits (L) for precision/recall control
   - Compare recall@k and QPS vs HNSW on same dataset

6. **Interactive HTML Visualization** — self-contained single-file:
   - Render HNSW layer 0 graph (force-directed layout, edges = neighbors)
   - Highlight layer-1+ hub nodes in different colors
   - Animate nearest-neighbor search: entry → greedy descent → result
   - Pan/zoom, hover for vector id + layer count, toggle layers

7. **Metadata Filtering** — structured search:
   - Each vector carries a dict of metadata (label, category, timestamp)
   - `search(query, filter={"category": "news"})` restricts candidates
   - Post-filter with HNSW over-fetch (ef_search × filter_ratio) heuristic
