#!/usr/bin/env bash
# Loom demo/verification script: exercises every feature end-to-end through
# the real CLI (not internal function calls) and asserts on the output at
# each step. Run from the project root: ./demo.sh
set -uo pipefail
cd "$(dirname "$0")"

PASS=0
FAIL=0
RUN_DIR="$(mktemp -d)"
trap 'rm -rf "$RUN_DIR"' EXIT

check() {
  local desc="$1"
  local status="$2"
  if [ "$status" -eq 0 ]; then
    echo "  [PASS] $desc"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $desc"
    FAIL=$((FAIL + 1))
  fi
}

grep_check() {
  local desc="$1" pattern="$2" file="$3"
  if grep -qF "$pattern" "$file"; then
    check "$desc" 0
  else
    check "$desc" 1
  fi
}

echo "== D1. unit test suite (55 tests) =="
python3 -m unittest discover -s tests > "$RUN_DIR/unittest.log" 2>&1
check "all unit tests pass" $?
tail -3 "$RUN_DIR/unittest.log" | sed 's/^/    /'

echo
echo "== D2. gradient check (proves hand-written backprop is analytically correct) =="
python3 cli.py gradcheck > "$RUN_DIR/gradcheck.log" 2>&1
check "gradcheck CLI exits 0" $?
grep_check "gradcheck reports PASSED" "PASSED" "$RUN_DIR/gradcheck.log"
cat "$RUN_DIR/gradcheck.log" | sed 's/^/    /'

echo
echo "== D3. tokenizer: train from scratch + round-trip on real text =="
head -c 40000 loom/data/corpus.txt > "$RUN_DIR/tiny_corpus.txt"
python3 cli.py tokenizer-train --corpus "$RUN_DIR/tiny_corpus.txt" \
  --vocab-size 320 --out "$RUN_DIR/tokenizer.json" > "$RUN_DIR/tok.log" 2>&1
check "tokenizer-train CLI exits 0" $?
grep_check "tokenizer round-trip OK" "round-trip check on first 2000 chars: OK" "$RUN_DIR/tok.log"
[ -f "$RUN_DIR/tokenizer.json" ]
check "tokenizer.json written" $?

echo
echo "== D4. train: real loss decrease on the bundled corpus (fast settings) =="
python3 cli.py train --out "$RUN_DIR/model" --vocab-size 384 --d-model 64 \
  --n-heads 4 --n-layers 2 --seq-len 64 --batch-size 24 --steps 300 --lr 3e-3 \
  --warmup 30 --log-every 50 --ckpt-every 300 > "$RUN_DIR/train.log" 2>&1
check "train CLI exits 0" $?
cat "$RUN_DIR/train.log" | sed 's/^/    /'
FIRST_LOSS=$(python3 -c "import json; print(json.loads(open('$RUN_DIR/model/train_log.jsonl').readline())['loss'])")
LAST_LOSS=$(python3 -c "
import json
with open('$RUN_DIR/model/train_log.jsonl') as f:
    lines = [json.loads(l) for l in f if l.strip()]
print(lines[-1]['loss'])
")
python3 -c "import sys; sys.exit(0 if float('$LAST_LOSS') < float('$FIRST_LOSS') * 0.8 else 1)"
check "loss dropped >20% (first=$FIRST_LOSS last=$LAST_LOSS)" $?
for f in model.npz config.json tokenizer.json train_log.jsonl; do
  [ -f "$RUN_DIR/model/$f" ]
  check "checkpoint artifact $f exists" $?
done

echo
echo "== D5. sample: autoregressive generation from the trained checkpoint =="
python3 cli.py sample --run "$RUN_DIR/model" --prompt "ROMEO:" --max-new-tokens 80 \
  --temperature 0.8 --top-k 40 --seed 0 > "$RUN_DIR/sample.log" 2>&1
check "sample CLI exits 0" $?
SAMPLE_LEN=$(wc -c < "$RUN_DIR/sample.log")
[ "$SAMPLE_LEN" -gt 20 ]
check "sample produced non-trivial output ($SAMPLE_LEN bytes)" $?
echo "    output: $(head -c 150 "$RUN_DIR/sample.log" | tr '\n' ' ')..."

echo "  -- determinism: same seed reproduces the same output --"
python3 cli.py sample --run "$RUN_DIR/model" --prompt "ROMEO:" --max-new-tokens 80 \
  --temperature 0.8 --top-k 40 --seed 0 > "$RUN_DIR/sample2.log" 2>&1
diff -q "$RUN_DIR/sample.log" "$RUN_DIR/sample2.log" > /dev/null
check "same seed -> byte-identical output" $?

echo
echo "== D6. viz: render the self-contained attention/loss HTML visualizer =="
python3 cli.py viz --run "$RUN_DIR/model" --prompt "ROMEO: what light" \
  --out "$RUN_DIR/viz.html" > "$RUN_DIR/viz.log" 2>&1
check "viz CLI exits 0" $?
[ -f "$RUN_DIR/viz.html" ]
check "viz.html written" $?
grep_check "viz.html contains attention data" '"attn"' "$RUN_DIR/viz.html"
grep_check "viz.html contains loss data" '"loss"' "$RUN_DIR/viz.html"
grep_check "viz.html contains no unescaped </script> from token data" \
  "const DATA" "$RUN_DIR/viz.html"

echo
echo "== D7. clean CLI errors on bad input (no raw tracebacks) =="
python3 cli.py train --steps 0 --out "$RUN_DIR/bad1" > "$RUN_DIR/bad1.log" 2>&1
BAD1_EXIT=$?
[ "$BAD1_EXIT" -eq 1 ] && ! grep -q "Traceback" "$RUN_DIR/bad1.log"
check "steps=0 -> clean exit 1, no traceback" $?

python3 cli.py tokenizer-train --vocab-size 100 > "$RUN_DIR/bad2.log" 2>&1
BAD2_EXIT=$?
[ "$BAD2_EXIT" -eq 1 ] && ! grep -q "Traceback" "$RUN_DIR/bad2.log"
check "vocab_size<256 -> clean exit 1, no traceback" $?

python3 cli.py sample --run "$RUN_DIR/does_not_exist" --prompt "hi" > "$RUN_DIR/bad3.log" 2>&1
BAD3_EXIT=$?
[ "$BAD3_EXIT" -eq 1 ] && ! grep -q "Traceback" "$RUN_DIR/bad3.log"
check "missing checkpoint -> clean exit 1, no traceback" $?

echo
echo "============================================"
echo "  $PASS passed, $FAIL failed"
echo "============================================"
[ "$FAIL" -eq 0 ]
