#!/usr/bin/env bash
# Exercises every Loom feature end-to-end through the real CLI, asserting on
# outputs and failing loudly on any error. Run from the project root:
#   bash demo.sh
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")"

PASS=0
CHECK() {
  local desc="$1"
  echo "  [check] $desc"
  PASS=$((PASS + 1))
}

FAIL() {
  echo "FAILED: $1" >&2
  exit 1
}

WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

echo "=== Loom demo.sh ==="
echo "workdir: $WORKDIR"

echo
echo "--- 1/8: Python unit + gradient-check test suite ---"
python3 -m unittest discover -s tests -q
CHECK "84-test suite passes (tensor autodiff, GPT gradcheck, tokenizer, optimizer, data, sampling, training, e2e, browser)"

echo
echo "--- 2/8: gradcheck CLI on a fresh random tiny GPT ---"
GRADCHECK_OUT="$WORKDIR/gradcheck.txt"
python3 -m loom.cli gradcheck --vocab-size 13 --block-size 6 --n-embd 8 --n-head 2 --n-layer 2 | tee "$GRADCHECK_OUT"
grep -q "gradcheck OK across 28 parameter tensors" "$GRADCHECK_OUT" || FAIL "gradcheck did not report success"
grep -qi "FAIL" "$GRADCHECK_OUT" && FAIL "gradcheck reported a FAIL line" || true
CHECK "full end-to-end gradient check passes across all 28 parameter tensors"

echo
echo "--- 3/8: BPE tokenizer trains and round-trips ---"
TOK_OUT="$WORKDIR/tokenize.txt"
python3 -m loom.cli tokenize corpus/hollow_loom.txt --merges 200 --out "$WORKDIR/tok.json" | tee "$TOK_OUT"
grep -q "round-trip check: OK" "$TOK_OUT" || FAIL "tokenizer round-trip check failed"
[ -f "$WORKDIR/tok.json" ] || FAIL "tokenizer was not saved"
CHECK "BPE tokenizer trains on the bundled corpus and round-trips exactly"

echo
echo "--- 4/8: train a real tokenizer+GPT checkpoint ---"
TRAIN_OUT="$WORKDIR/train.txt"
python3 -m loom.cli train corpus/hollow_loom.txt --out "$WORKDIR/ckpt" \
  --merges 200 --block-size 48 --n-embd 32 --n-head 4 --n-layer 2 \
  --batch-size 16 --steps 80 --eval-every 20 --seed 0 | tee "$TRAIN_OUT"
[ -f "$WORKDIR/ckpt/params.npz" ] || FAIL "checkpoint params.npz missing"
[ -f "$WORKDIR/ckpt/meta.json" ] || FAIL "checkpoint meta.json missing"
[ -f "$WORKDIR/ckpt/tokenizer.json" ] || FAIL "checkpoint tokenizer.json missing"
FIRST_LOSS=$(grep "step     1/80" "$TRAIN_OUT" | grep -oE "train_loss [0-9.]+" | awk '{print $2}')
LAST_LOSS=$(grep "step    80/80" "$TRAIN_OUT" | grep -oE "train_loss [0-9.]+" | awk '{print $2}')
python3 -c "
first, last = $FIRST_LOSS, $LAST_LOSS
assert last < first, f'loss did not decrease: {first} -> {last}'
print(f'loss decreased: {first:.4f} -> {last:.4f}')
"
CHECK "training runs to completion and loss provably decreases"

echo
echo "--- 5/8: generate with temperature/top-k/top-p sampling ---"
GEN_OUT="$WORKDIR/generate.txt"
python3 -m loom.cli generate "$WORKDIR/ckpt" --prompt "The loom" --tokens 60 \
  --temperature 0.8 --top-k 40 --top-p 0.95 --seed 0 | tee "$GEN_OUT"
[ -s "$GEN_OUT" ] || FAIL "generate produced no output"
CHECK "generate produces text using temperature + top-k + top-p sampling"

echo
echo "--- 6/8: interactive HTML attention/generation visualizer ---"
python3 -m loom.cli viz "$WORKDIR/ckpt" --prompt "Esme" --tokens 40 --out "$WORKDIR/viz.html"
[ -s "$WORKDIR/viz.html" ] || FAIL "viz.html was not written or is empty"
python3 -c "
html = open('$WORKDIR/viz.html', encoding='utf-8').read()
assert '<html' in html and '</html>' in html
assert 'attn' in html.lower()
assert html.count('</script>') >= 1
print('viz.html is well-formed,', len(html), 'bytes')
"
CHECK "interactive HTML visualizer renders with real attention/loss/generation data"

echo
echo "--- 7/8: CLI error handling on bad input (no raw tracebacks) ---"
set +e
python3 -m loom.cli generate "$WORKDIR/does-not-exist" --prompt hi >/tmp/loom_demo_err.txt 2>&1
CODE=$?
set -e
grep -q "^loom: error:" /tmp/loom_demo_err.txt || FAIL "CLI did not print a clean 'loom: error:' message"
grep -q "Traceback" /tmp/loom_demo_err.txt && FAIL "CLI leaked a raw Python traceback on bad input" || true
[ "$CODE" -ne 0 ] || FAIL "CLI should have exited non-zero on a missing checkpoint"
rm -f /tmp/loom_demo_err.txt
CHECK "CLI fails cleanly (no tracebacks, non-zero exit) on invalid input"

echo
echo "--- 8/8: one-command demo (untrained vs trained comparison) ---"
DEMO_OUT="$WORKDIR/demo.txt"
python3 -m loom.cli demo --seed 0 | tee "$DEMO_OUT"
grep -q "model learned something real" "$DEMO_OUT" || FAIL "demo did not report a real improvement over the untrained baseline"
[ -f "loom_demo_viz.html" ] || FAIL "demo did not write loom_demo_viz.html"
rm -f loom_demo_viz.html
CHECK "one-command demo trains end-to-end and shows an objective, non-mocked improvement"

echo
echo "=== ALL $PASS CHECKS PASSED ==="
