#!/usr/bin/env bash
# Runs the full test suite, then walks through every Loom feature end-to-end
# against the shipped Tiny Shakespeare checkpoint.
set -euo pipefail
cd "$(dirname "$0")"

echo "== 1/6: unit + gradient-check test suite =="
python3 -m pytest tests/ -q

echo
echo "== 2/6: tokenizer round-trip on arbitrary text =="
python3 -m loom.cli tokenizer encode --tokenizer checkpoints/shakespeare/tokenizer.json \
  "To be, or not to be, that is the question:" | tee /tmp/loom_demo_ids.txt
python3 -m loom.cli tokenizer decode --tokenizer checkpoints/shakespeare/tokenizer.json \
  "$(cat /tmp/loom_demo_ids.txt)"

echo
echo "== 3/6: greedy completion from the trained checkpoint =="
python3 -m loom.cli generate --checkpoint checkpoints/shakespeare \
  --prompt "ROMEO:" --max-new-tokens 120 --greedy

echo
echo "== 4/6: temperature + top-k + top-p sampling =="
python3 -m loom.cli generate --checkpoint checkpoints/shakespeare \
  --prompt "KING RICHARD:" --max-new-tokens 120 --temperature 0.8 --top-k 40 --seed 0

echo
echo "== 5/6: nucleus (top-p) sampling =="
python3 -m loom.cli generate --checkpoint checkpoints/shakespeare \
  --prompt "First Citizen:" --max-new-tokens 120 --temperature 1.0 --top-p 0.9 --seed 1

echo
echo "== 6/6: render the interactive HTML visualizer =="
python3 -m loom.cli viz --checkpoint checkpoints/shakespeare \
  --out loom_viz.html --prompt "ROMEO:"
echo "wrote loom_viz.html"

echo
echo "demo complete."
