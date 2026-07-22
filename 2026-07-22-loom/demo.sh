#!/bin/bash
# End-to-end verification: exercises every feature in PLAN.md with zero
# manual steps. Any failure aborts the script (set -e) with a nonzero exit.
set -euo pipefail
cd "$(dirname "$0")"

DEMO_CKPT="/tmp/loom_demo_ckpt_$$"
SERVER_PORT=8917
SERVER_PID=""

cleanup() {
    rm -f "${DEMO_CKPT}.npz" "${DEMO_CKPT}.json"
    if [ -n "$SERVER_PID" ]; then
        kill "$SERVER_PID" 2>/dev/null || true
    fi
}
trap cleanup EXIT

step() { echo; echo "=== $1 ==="; }

step "1/8  Autograd gradient checks (every op vs. finite differences)"
python3 tests/test_autograd.py

step "2/8  BPE tokenizer tests (round-trip, compression, save/load, edge cases)"
python3 tests/test_tokenizer.py

step "3/8  Model tests (causal masking, KV-cache parity, weight tying, checkpoints, sampling)"
python3 tests/test_model.py

step "4/8  Train a fresh tiny model end-to-end (proves the full pipeline, not just the shipped checkpoint)"
python3 train.py --out "$DEMO_CKPT" \
    --vocab-size 300 --dim 32 --n-layers 2 --n-heads 2 \
    --block-size 32 --batch-size 16 --steps 150 \
    --log-every 50 --eval-every 150 --sample-every 0 --seed 0

step "5/8  Sample from the freshly trained checkpoint"
python3 sample.py --checkpoint "$DEMO_CKPT" --prompt "The" --tokens 30 --seed 1

step "6/8  Confirm KV-cache and full-recompute generation agree exactly (greedy decoding)"
python3 - "$DEMO_CKPT" <<'PYEOF'
import sys
import numpy as np
from loom.checkpoint import load_checkpoint
from loom.generate import generate

model, tok, config, extra = load_checkpoint(sys.argv[1])
_, ids_cached = generate(model, tok, "The weaver", 25, temperature=1.0, top_k=1,
                          rng=np.random.default_rng(0), use_cache=True)
_, ids_full = generate(model, tok, "The weaver", 25, temperature=1.0, top_k=1,
                        rng=np.random.default_rng(0), use_cache=False)
assert ids_cached == ids_full, "KV-cache diverged from full recompute!"
print(f"OK: {len(ids_cached)} tokens, cached == full-recompute, byte for byte")
PYEOF

step "7/8  KV-cache benchmark (shipped checkpoint)"
python3 benchmark.py --checkpoint checkpoints/loom --tokens 40 --repeats 2

step "8/8  Playground server: boot, hit every API route, verify responses, shut down"
python3 server.py --checkpoint checkpoints/loom --port "$SERVER_PORT" > /tmp/loom_demo_server.log 2>&1 &
SERVER_PID=$!
for i in $(seq 1 20); do
    if curl -s -o /dev/null "http://127.0.0.1:${SERVER_PORT}/api/info"; then break; fi
    sleep 0.3
done

python3 - "$SERVER_PORT" <<'PYEOF'
import json
import sys
import urllib.error
import urllib.request

port = sys.argv[1]
base = f"http://127.0.0.1:{port}"

def post(path, payload):
    req = urllib.request.Request(f"{base}{path}", data=json.dumps(payload).encode(),
                                  headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(req, timeout=10) as r:
        return json.loads(r.read())

# GET /  (the playground page itself)
with urllib.request.urlopen(f"{base}/", timeout=10) as r:
    html = r.read().decode()
    assert "Loom" in html and "<script>" in html, "playground.html didn't serve correctly"
print("OK: GET / serves the playground page")

# GET /api/info
with urllib.request.urlopen(f"{base}/api/info", timeout=10) as r:
    info = json.loads(r.read())
    assert info["num_params"] > 0 and info["vocab_size"] > 0
print(f"OK: GET /api/info -> {info['num_params']:,} params, vocab {info['vocab_size']}")

# POST /api/generate
gen = post("/api/generate", {"prompt": "The weaver", "max_new_tokens": 40, "temperature": 0.8, "top_k": 40, "seed": 3})
assert "text" in gen and gen["text"].startswith("The weaver") and gen["num_tokens"] > 0
print(f"OK: POST /api/generate -> {gen['num_tokens']} tokens in {gen['elapsed_sec']}s")

# POST /api/attention
attn = post("/api/attention", {"text": gen["text"]})
assert len(attn["tokens"]) > 0 and len(attn["layers"]) == 3 and len(attn["layers"][0]) == 4
print(f"OK: POST /api/attention -> {len(attn['layers'])} layers x {len(attn['layers'][0])} heads")

# error handling: empty attention text -> clean 400, not a crash
try:
    post("/api/attention", {"text": ""})
    raise SystemExit("expected an HTTPError for empty text")
except urllib.error.HTTPError as e:
    assert e.code == 400
print("OK: empty /api/attention text returns a clean 400, not a crash")
PYEOF

echo
echo "================================================"
echo "ALL 8 VERIFICATION STEPS PASSED"
echo "================================================"
