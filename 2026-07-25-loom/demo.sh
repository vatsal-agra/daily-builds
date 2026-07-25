#!/usr/bin/env bash
# Runs Loom end to end: gradient checks -> tokenizer/model/generation tests
# -> loads the shipped trained checkpoint -> generates real samples ->
# benchmarks KV-cache vs naive generation -> exports a visualizer trace.
#
# This does NOT retrain from scratch (that's `python3 -m loom.cli train`,
# ~10-15 minutes) — it verifies and demonstrates the checkpoint that ships
# in checkpoints/loom-small/, which was trained by this exact command.
set -euo pipefail
cd "$(dirname "$0")"

pass() { echo "  ✓ $1"; }

echo "== 1. Gradient checks (every layer, hand-derived backward vs finite difference) =="
python3 tests/test_gradcheck.py
pass "gradients verified"

echo
echo "== 2. Tokenizer tests (BPE round trip, determinism, UTF-8) =="
python3 tests/test_tokenizer.py
pass "tokenizer verified"

echo
echo "== 3. Model tests (shapes, causal-mask leakage, overfit sanity check) =="
python3 tests/test_model.py
pass "model verified"

echo
echo "== 4. Generation tests (sampling determinism, KV-cache/naive parity) =="
python3 tests/test_generate.py
pass "generation verified"

echo
echo "== 5. Loading shipped checkpoint and generating real samples =="
for prompt in "" "The clever fox" "Long before the river changed its course"; do
  echo "--- prompt: '$prompt' ---"
  python3 -m loom.cli generate --ckpt-dir checkpoints/loom-small --prompt "$prompt" \
    --max-new-tokens 120 --temperature 0.8 --top-k 40 --seed 3
  echo
done

echo "== 6. KV-cache vs naive generation: speed + exact output parity =="
python3 -m loom.cli bench --ckpt-dir checkpoints/loom-small --prompt "Not far from" --max-new-tokens 40
pass "bench complete (see identical_output above)"

echo
echo "== 7. Exporting an attention + generation trace for the HTML visualizer =="
python3 -m loom.cli viz --ckpt-dir checkpoints/loom-small \
  --text "The clever fox wanted a warm place to sleep" --out viz/trace.json
pass "wrote viz/trace.json — open viz/visualizer.html in a browser (file picker, no server needed)"

echo
echo "ALL DEMO STEPS PASSED"
