#!/usr/bin/env bash
# Loom demo/verification script: runs the full test suite, then exercises
# the trained checkpoint end-to-end (CLI generation, attention CLI, and a
# real HTTP server round trip), same as tests/test_integration.py but as a
# human-readable walkthrough anyone can run.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

pass() { echo "  [ok] $1"; }
step() { echo; echo "== $1 =="; }

step "Checking dependencies"
python3 -c "import numpy" 2>/dev/null || { echo "installing numpy..."; pip install -q numpy; }
pass "numpy available: $(python3 -c 'import numpy; print(numpy.__version__)')"

step "Autodiff engine gradient checks (tests/test_engine.py)"
python3 tests/test_engine.py
pass "engine gradient checks"

step "Tokenizer tests (tests/test_tokenizer.py)"
python3 tests/test_tokenizer.py
pass "tokenizer tests"

step "Model + generation tests (tests/test_model.py)"
python3 tests/test_model.py
pass "model tests"

step "Integration tests: tiny end-to-end train + real HTTP server (tests/test_integration.py)"
python3 tests/test_integration.py
pass "integration tests"

CKPT="checkpoints/loom-shakespeare"
if [ ! -f "$CKPT/weights.npz" ]; then
  echo
  echo "No trained checkpoint at $CKPT -- run:"
  echo "  python3 -m loom.train --max-steps 3000"
  echo "before continuing the live demo. Skipping the live-model steps."
  exit 0
fi

step "Checkpoint info"
python3 -c "
import json
meta = json.load(open('$CKPT/meta.json'))
print(f\"  step {meta['step']}/{meta['max_steps']}, params {meta['num_params']:,}\")
if meta['history']:
    h = meta['history'][-1]
    print(f\"  latest eval: train_loss={h['train_loss']:.4f} val_loss={h['val_loss']:.4f}\")
"

step "CLI generation from the trained checkpoint"
python3 -m loom.cli generate "ROMEO:" --checkpoint "$CKPT" --max-new-tokens 150 --temperature 0.8 --top-k 40 --seed 42
pass "CLI generation"

step "CLI attention inspection"
python3 -m loom.cli attention "To be, or not to be" --checkpoint "$CKPT"
pass "CLI attention"

step "Live HTTP server round trip"
PORT=8497
python3 -m loom.server --checkpoint "$CKPT" --port $PORT > /tmp/loom-demo-server.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT

for i in $(seq 1 30); do
  if curl -sf "http://127.0.0.1:$PORT/api/status" > /dev/null 2>&1; then
    break
  fi
  sleep 0.3
done

echo "-- GET /api/status --"
# Trim + print in Python rather than piping json.tool through `head`: under
# `set -o pipefail`, head closing its read end early sends json.tool a
# SIGPIPE, which fails the pipeline and (with `set -e`) kills the whole
# script -- a real bug this exact script tripped over during Phase 4.
curl -sf "http://127.0.0.1:$PORT/api/status" | python3 -c "
import json, sys
d = json.load(sys.stdin)
d['history'] = d['history'][-3:] + (['...'] if len(d['history']) > 3 else [])
print(json.dumps(d, indent=2))
"
pass "status endpoint"

echo "-- POST /api/generate --"
curl -sf -X POST "http://127.0.0.1:$PORT/api/generate" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "JULIET:", "max_new_tokens": 100, "temperature": 0.8, "top_k": 40}' \
  | python3 -m json.tool
pass "generate endpoint"

echo "-- POST /api/attention --"
curl -sf -X POST "http://127.0.0.1:$PORT/api/attention" \
  -H "Content-Type: application/json" \
  -d '{"prompt": "O Romeo"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); print('tokens:', d['tokens']); print('layers x heads:', len(d['layers']), 'x', len(d['layers'][0]))"
pass "attention endpoint"

kill $SERVER_PID 2>/dev/null || true
trap - EXIT

step "All checks passed"
echo "Run 'python3 -m loom.cli serve' and open http://127.0.0.1:8420 for the interactive UI."
