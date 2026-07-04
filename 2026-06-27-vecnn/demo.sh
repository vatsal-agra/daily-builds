#!/usr/bin/env bash
# VecNN demo.sh — exercises every feature end-to-end
# Run from the project root: bash demo.sh

set -euo pipefail
cd "$(dirname "$0")"

PYTHON=python
VECNN="$PYTHON -m vecnn.cli"
export TMP_DIR
TMP_DIR=$(mktemp -d)
trap "rm -rf $TMP_DIR" EXIT

RED='\033[0;31m'
GREEN='\033[0;32m'
BLUE='\033[0;34m'
NC='\033[0m'

pass() { echo -e "${GREEN}✓ PASS${NC}  $1"; }
fail() { echo -e "${RED}✗ FAIL${NC}  $1"; exit 1; }
section() { echo -e "\n${BLUE}── $1 ──${NC}"; }

# ---------------------------------------------------------------------------
# D1: Unit tests
# ---------------------------------------------------------------------------
section "D1: Unit test suite"
$PYTHON -m pytest tests/ -q --tb=short 2>&1 | tail -5
pass "Unit test suite"

# ---------------------------------------------------------------------------
# D2: HNSW demo command (REQUIRED features 1+4)
# ---------------------------------------------------------------------------
section "D2: HNSW demo — recall sweep at multiple ef values"
$VECNN demo -n 300 --dim 32 -k 10 --lsh-bits 8 --lsh-tables 10 \
  --out-viz "$TMP_DIR/viz.html" > "$TMP_DIR/demo.out" 2>&1
cat "$TMP_DIR/demo.out"
grep -q "recall@10" "$TMP_DIR/demo.out" || fail "recall@10 header not found in demo output"
grep -q "✓ Filter correct" "$TMP_DIR/demo.out" || fail "metadata filter verification failed"
grep -q "lsh (3-probe)" "$TMP_DIR/demo.out" || fail "multi-probe LSH not shown"
[ -f "$TMP_DIR/viz.html" ] || fail "HTML visualizer not generated"
VIZSIZE=$(wc -c < "$TMP_DIR/viz.html")
[ "$VIZSIZE" -gt 50000 ] || fail "HTML visualizer too small: $VIZSIZE bytes"
pass "HNSW demo with recall sweep, metadata filter, multi-probe LSH, HTML viz"

# ---------------------------------------------------------------------------
# D3: Distance metrics (REQUIRED feature 2)
# ---------------------------------------------------------------------------
section "D3: Distance metrics — correctness verification"
$PYTHON - << 'PYEOF'
import sys; sys.path.insert(0, '.')
import numpy as np
from vecnn.distance import cosine_distance, euclidean_distance, inner_product_distance, cosine_distance_batch

a = np.array([1.0, 0.0, 0.0])
assert abs(cosine_distance(a, a)) < 1e-12, "cosine(a,a) != 0"

b = np.array([0.0, 1.0, 0.0])
assert abs(cosine_distance(a, b) - 1.0) < 1e-12, "cosine(a,b) != 1 for orthogonal"

c = -a
assert abs(cosine_distance(a, c) - 2.0) < 1e-12, "cosine(a,-a) != 2"

p = np.array([0.0, 0.0]); q = np.array([3.0, 4.0])
assert abs(euclidean_distance(p, q) - 5.0) < 1e-12, "euclidean dist != 5"

u = np.array([1.0, 2.0]); v = np.array([3.0, 4.0])
assert abs(inner_product_distance(u, v) - (-11.0)) < 1e-12, "inner product dist != -11"

rng = np.random.default_rng(0)
q2 = rng.standard_normal(16)
mat = rng.standard_normal((50, 16))
batch = cosine_distance_batch(q2, mat)
for i in range(len(mat)):
    scalar = cosine_distance(q2, mat[i])
    assert abs(batch[i] - scalar) < 1e-10, f"batch/scalar mismatch at {i}"

print("All distance metric checks passed")
PYEOF
pass "Distance metrics — all 3 metrics + batch verified"

# ---------------------------------------------------------------------------
# D4: Persistence — save/load round-trip (REQUIRED feature 3)
# ---------------------------------------------------------------------------
section "D4: Persistence — save/load round-trip"
$PYTHON - << 'PYEOF'
import json, sys, os; sys.path.insert(0, '.')
import numpy as np
tmp = os.environ["TMP_DIR"]

rng = np.random.default_rng(42)
vecs = rng.standard_normal((50, 16))
vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
jl_path = f"{tmp}/data.jsonl"
with open(jl_path, 'w') as f:
    for i, v in enumerate(vecs):
        f.write(json.dumps({"vector": v.tolist(), "id": i, "metadata": {"group": str(i % 5)}}) + "\n")

from vecnn.collection import Collection
coll = Collection("test_persist", dim=16, metric="cosine")
count = coll.add_from_jsonl(jl_path)
assert count == 50, f"Expected 50, got {count}"

save_path = f"{tmp}/collection.json"
coll.save(save_path)
assert os.path.exists(save_path)

loaded = Collection.load(save_path)
assert loaded.size == 50, f"Loaded size {loaded.size} != 50"
assert loaded.name == "test_persist"

q = vecs[0]
r1 = [x[0] for x in coll.search(q, k=5)]
r2 = [x[0] for x in loaded.search(q, k=5)]
assert r1 == r2, f"Search results differ after load: {r1} vs {r2}"

coll.delete(5)
coll.save(save_path)
loaded2 = Collection.load(save_path)
assert loaded2.size == 49, f"After delete, loaded size {loaded2.size} != 49"
assert 5 not in loaded2.all_ids(), "Deleted node still in loaded collection"

print("All persistence checks passed")
PYEOF
pass "Persistence — JSONL insert, save, load, search equality, delete persists"

# ---------------------------------------------------------------------------
# D5: Recall benchmarking (REQUIRED feature 4)
# ---------------------------------------------------------------------------
section "D5: Recall benchmarking — brute-force vs HNSW"
$PYTHON - << 'PYEOF'
import sys; sys.path.insert(0, '.')
import numpy as np
from vecnn.hnsw import HNSWIndex
from vecnn.bench import exact_knn, recall_at_k, benchmark
from vecnn.distance import cosine_distance

rng = np.random.default_rng(7)
n, dim = 300, 16
vecs = rng.standard_normal((n, dim))
vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)

idx = HNSWIndex(dim=dim, metric="cosine", M=16, ef_construction=200, seed=7)
ids = [idx.insert(v) for v in vecs]

query_vecs = rng.standard_normal((20, dim))
query_vecs /= np.linalg.norm(query_vecs, axis=1, keepdims=True)

for q in query_vecs[:3]:
    top3 = exact_knn(q, vecs, 3, "cosine")
    assert len(top3) == 3
    dists = [cosine_distance(q, vecs[i]) for i in top3]
    assert dists == sorted(dists), "exact_knn not sorted"

results = benchmark(idx, query_vecs, vecs, ids, k=5, ef_values=[10, 50, 200])
assert len(results) == 3
recalls = [r["recall_at_k"] for r in results]
assert recalls[-1] >= recalls[0], f"Recall not monotone: {recalls}"
assert recalls[-1] >= 0.9, f"recall@5 at ef=200 = {recalls[-1]:.3f} < 0.9"

print(f"Recall sweep: {[f'{r:.3f}' for r in recalls]}")
print("All benchmark checks passed")
PYEOF
pass "Recall benchmarking — exact oracle, recall@k sweep, monotone property"

# ---------------------------------------------------------------------------
# D6: LSH multi-probe (STRETCH feature 5)
# ---------------------------------------------------------------------------
section "D6: LSH multi-probe — recall improves with more probes"
$PYTHON - << 'PYEOF'
import sys; sys.path.insert(0, '.')
import numpy as np
from vecnn.lsh import LSHIndex
from vecnn.bench import exact_knn, recall_at_k

rng = np.random.default_rng(10)
n, dim = 200, 16
vecs = rng.standard_normal((n, dim))
vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)

idx = LSHIndex(dim=dim, n_tables=10, n_bits=8, seed=10)
ids = [idx.insert(v) for v in vecs]

q = vecs[0]
true_top = {ids[i] for i in exact_knn(q, vecs, 5, "cosine")}

r1 = recall_at_k(true_top, [x[0] for x in idx.search(q, k=5, n_probes=1)])
r2 = recall_at_k(true_top, [x[0] for x in idx.search(q, k=5, n_probes=2)])
r3 = recall_at_k(true_top, [x[0] for x in idx.search(q, k=5, n_probes=3)])
print(f"  recall@5: 1-probe={r1:.2f}, 2-probe={r2:.2f}, 3-probe={r3:.2f}")
assert r3 >= r1, f"3-probe recall {r3} < 1-probe recall {r1}"

d = idx.to_dict()
idx2 = LSHIndex.from_dict(d)
r_loaded = recall_at_k(true_top, [x[0] for x in idx2.search(q, k=5, n_probes=3)])
assert r_loaded == r3, f"Loaded LSH recall differs: {r_loaded} vs {r3}"

print("All LSH multi-probe checks passed")
PYEOF
pass "LSH multi-probe — recall increases with probes, serialisation preserves results"

# ---------------------------------------------------------------------------
# D7: HTML visualizer (STRETCH feature 6)
# ---------------------------------------------------------------------------
section "D7: HTML visualizer — content check"
$PYTHON - << 'PYEOF'
import sys, json; sys.path.insert(0, '.')
import numpy as np
from vecnn.hnsw import HNSWIndex
from vecnn.viz import generate_html

rng = np.random.default_rng(20)
vecs = rng.standard_normal((30, 4))
vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)

idx = HNSWIndex(dim=4, metric="cosine", M=4, ef_construction=50, seed=20)
for v in vecs:
    idx.insert(v)

query = vecs[0]
html = generate_html(idx, query=query, query_k=3, title="Test Viz")
assert "VecNN" in html
assert "__PAYLOAD__" not in html
assert "search_steps" in html
assert "layers" in html
assert len(html) > 25000, f"HTML too small: {len(html)}"

payload_start = html.index("const DATA = ") + len("const DATA = ")
payload_end = html.index(";\n\n//", payload_start)
payload = json.loads(html[payload_start:payload_end])
assert payload["n_nodes"] == 30
assert len(payload["layers"]) >= 1
assert len(payload["search_steps"]) > 0

print("All HTML visualizer checks passed")
PYEOF
pass "HTML visualizer — payload embedded, search steps present"

# ---------------------------------------------------------------------------
# D8: Metadata filtering (STRETCH feature 7)
# ---------------------------------------------------------------------------
section "D8: Metadata filtering"
$PYTHON - << 'PYEOF'
import sys; sys.path.insert(0, '.')
import numpy as np
from vecnn.collection import Collection

rng = np.random.default_rng(30)
coll = Collection("meta_test", dim=8, metric="cosine",
                  index_params={"M": 4, "ef_construction": 50})
vecs = rng.standard_normal((100, 8))
vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)

for i, v in enumerate(vecs):
    coll.add(v, metadata={"category": chr(65 + (i % 4)), "score": i})

q = vecs[0]
results_a = coll.search(q, k=10, filter_expr={"category": "A"})
for _, _, meta in results_a:
    assert meta["category"] == "A", f"Filter broken: got {meta['category']}"

results_b = coll.search(q, k=10, filter_expr={"category": "B"})
for _, _, meta in results_b:
    assert meta["category"] == "B", f"Filter broken: got {meta['category']}"

results_z = coll.search(q, k=10, filter_expr={"category": "Z"})
assert results_z == [], f"Non-existent filter returned results: {results_z}"

print("All metadata filter checks passed")
PYEOF
pass "Metadata filtering — category filter works, empty result for non-existent"

# ---------------------------------------------------------------------------
# D9: CLI subcommands
# ---------------------------------------------------------------------------
section "D9: CLI subcommands — insert, search, bench, compare, viz, info"

$PYTHON - << 'PYEOF'
import sys, json, os; sys.path.insert(0, '.')
import numpy as np
tmp = os.environ["TMP_DIR"]
rng = np.random.default_rng(50)
vecs = rng.standard_normal((80, 16))
vecs /= np.linalg.norm(vecs, axis=1, keepdims=True)
with open(f"{tmp}/vectors.jsonl", "w") as f:
    for i, v in enumerate(vecs):
        f.write(json.dumps({"vector": v.tolist(), "metadata": {"i": i}}) + "\n")
with open(f"{tmp}/query.json", "w") as f:
    json.dump({"vector": vecs[0].tolist()}, f)
print("Test data written")
PYEOF

$VECNN insert "$TMP_DIR/coll.json" "$TMP_DIR/vectors.jsonl" --dim 16 --metric cosine > "$TMP_DIR/insert.out" 2>&1
grep -q "Inserted 80" "$TMP_DIR/insert.out" || { cat "$TMP_DIR/insert.out"; fail "insert failed"; }
pass "CLI insert"

$VECNN search "$TMP_DIR/coll.json" "$TMP_DIR/query.json" -k 5 > "$TMP_DIR/search.out" 2>&1
grep -q "id=" "$TMP_DIR/search.out" || { cat "$TMP_DIR/search.out"; fail "search output missing"; }
pass "CLI search"

$VECNN bench "$TMP_DIR/coll.json" -k 5 --n-queries 10 > "$TMP_DIR/bench.out" 2>&1
grep -q "recall@5" "$TMP_DIR/bench.out" || { cat "$TMP_DIR/bench.out"; fail "bench output missing"; }
pass "CLI bench"

$VECNN compare "$TMP_DIR/coll.json" -k 5 --n-queries 10 --lsh-bits 6 > "$TMP_DIR/compare.out" 2>&1
grep -q "hnsw" "$TMP_DIR/compare.out" || { cat "$TMP_DIR/compare.out"; fail "compare output missing"; }
pass "CLI compare"

$VECNN info "$TMP_DIR/coll.json" > "$TMP_DIR/info.out" 2>&1
grep -q "size" "$TMP_DIR/info.out" || { cat "$TMP_DIR/info.out"; fail "info output missing"; }
pass "CLI info"

$VECNN viz "$TMP_DIR/coll.json" --out "$TMP_DIR/coll_viz.html" > "$TMP_DIR/viz.out" 2>&1
grep -q "Saved" "$TMP_DIR/viz.out" || { cat "$TMP_DIR/viz.out"; fail "viz failed"; }
[ -f "$TMP_DIR/coll_viz.html" ] && pass "CLI viz" || fail "viz file not created"

# ---------------------------------------------------------------------------
# Summary
# ---------------------------------------------------------------------------
echo ""
echo -e "${GREEN}All demo checks passed.${NC}"
