#!/usr/bin/env bash
# Loom demo/verification script — exercises every feature end-to-end.
set -uo pipefail
cd "$(dirname "$0")"

PASS=0
FAIL=0
WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

check() {
    local desc="$1"
    shift
    if "$@" >"$WORKDIR/out.log" 2>&1; then
        echo "  OK   $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL $desc"
        echo "       -- last 15 lines of output --"
        tail -15 "$WORKDIR/out.log" | sed 's/^/       /'
        FAIL=$((FAIL + 1))
    fi
}

check_grep() {
    # check_grep <desc> <pattern> <logfile>
    local desc="$1" pattern="$2" file="$3"
    if grep -q "$pattern" "$file"; then
        echo "  OK   $desc"
        PASS=$((PASS + 1))
    else
        echo "  FAIL $desc (pattern '$pattern' not found in $file)"
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Loom demo/verification ==="
echo

echo "[1/9] Unit test suite"
check "32 unit tests pass" python3 -m unittest tests.test_loom -v

echo
echo "[2/9] Gradient check suite (17 ops incl. full transformer block)"
check "gradcheck passes" python3 loom.py gradcheck

echo
echo "[3/9] BPE tokenizer: train + exact round-trip"
python3 loom.py train-tokenizer --vocab-size 400 --out "$WORKDIR/tokenizer.json" --verbose \
    > "$WORKDIR/tok.log" 2>&1
check_grep "tokenizer trained" "Saved tokenizer" "$WORKDIR/tok.log"
check_grep "round-trip is exact" "Round-trip exact: True" "$WORKDIR/tok.log"

echo
echo "[4/9] Tokenizer edge cases (empty string, missing file)"
python3 - "$WORKDIR/tokenizer.json" <<'EOF' > "$WORKDIR/edge.log" 2>&1
import sys
from loom.tokenizer import BPETokenizer
tok = BPETokenizer.load(sys.argv[1])
assert tok.encode("") == []
assert tok.decode([]) == ""
print("edge cases ok")
EOF
check_grep "empty-string tokenizer edge cases" "edge cases ok" "$WORKDIR/edge.log"
python3 loom.py train-tokenizer --corpus /no/such/file.txt > "$WORKDIR/missing.log" 2>&1
check_grep "clean error on missing corpus (no traceback)" "^ERROR: corpus not found" "$WORKDIR/missing.log"

echo
echo "[5/9] Training: loss decreases, checkpoint saves"
python3 loom.py train --tokenizer "$WORKDIR/tokenizer.json" --out "$WORKDIR/ckpt.npz" \
    --steps 120 --batch-size 8 --block-size 32 --d-model 32 --n-layer 2 --n-head 2 \
    --log-every 30 --history-out "$WORKDIR/history.csv" > "$WORKDIR/train.log" 2>&1
check_grep "training ran to completion" "Saved checkpoint" "$WORKDIR/train.log"
python3 - "$WORKDIR/history.csv" <<'EOF' > "$WORKDIR/loss_check.log" 2>&1
import sys
rows = [line.strip().split(",") for line in open(sys.argv[1]) if line.strip()]
losses = [float(r[1]) for r in rows]
assert losses[-1] < losses[0], f"loss did not decrease: {losses[0]} -> {losses[-1]}"
print(f"loss decreased: {losses[0]:.4f} -> {losses[-1]:.4f}")
EOF
check_grep "loss measurably decreased" "loss decreased" "$WORKDIR/loss_check.log"

echo
echo "[6/9] Training edge cases (--steps 0, corpus shorter than block_size)"
python3 loom.py train --tokenizer "$WORKDIR/tokenizer.json" --steps 0 \
    --out "$WORKDIR/unused.npz" > "$WORKDIR/steps0.log" 2>&1
check_grep "clean error on --steps 0 (no traceback)" "^ERROR: --steps must be >= 1" "$WORKDIR/steps0.log"

echo
echo "[7/9] Generation: greedy, temperature+top-k, top-p, all in-vocab"
python3 loom.py generate --checkpoint "$WORKDIR/ckpt.npz" --tokenizer "$WORKDIR/tokenizer.json" \
    --prompt "Old Maren" --max-new-tokens 60 --temperature 0.0 > "$WORKDIR/gen_greedy.log" 2>&1
check "greedy generation runs" test -s "$WORKDIR/gen_greedy.log"
python3 loom.py generate --checkpoint "$WORKDIR/ckpt.npz" --tokenizer "$WORKDIR/tokenizer.json" \
    --prompt "The village" --max-new-tokens 60 --temperature 0.8 --top-k 40 --seed 1 \
    > "$WORKDIR/gen_topk.log" 2>&1
check "temperature+top-k generation runs" test -s "$WORKDIR/gen_topk.log"
python3 loom.py generate --checkpoint "$WORKDIR/ckpt.npz" --tokenizer "$WORKDIR/tokenizer.json" \
    --prompt "Tamsin" --max-new-tokens 60 --top-p 0.9 --seed 2 > "$WORKDIR/gen_topp.log" 2>&1
check "top-p (nucleus) generation runs" test -s "$WORKDIR/gen_topp.log"
echo "  sample (greedy): $(head -c 120 "$WORKDIR/gen_greedy.log" | tr '\n' ' ')..."

echo
echo "[8/9] Chat REPL (piped input) and attention visualizer"
printf "Old Maren\nquit\n" | python3 loom.py chat --checkpoint "$WORKDIR/ckpt.npz" \
    --tokenizer "$WORKDIR/tokenizer.json" --max-new-tokens 20 > "$WORKDIR/chat.log" 2>&1
check_grep "chat REPL responds" "Loom chat REPL" "$WORKDIR/chat.log"
python3 loom.py attn-viz --checkpoint "$WORKDIR/ckpt.npz" --tokenizer "$WORKDIR/tokenizer.json" \
    --prompt "Old Maren said" --out "$WORKDIR/attention.html" > "$WORKDIR/viz.log" 2>&1
check_grep "attention viz written" "Wrote attention visualization" "$WORKDIR/viz.log"
check_grep "attention viz embeds real per-head data" '"n_head"' "$WORKDIR/attention.html"

echo
echo "[9/9] Inference edge cases (empty prompt, missing checkpoint)"
python3 loom.py generate --checkpoint "$WORKDIR/ckpt.npz" --tokenizer "$WORKDIR/tokenizer.json" \
    --prompt "   " > "$WORKDIR/empty_prompt.log" 2>&1
check_grep "clean error on whitespace-only prompt" "^ERROR: --prompt must be non-empty" "$WORKDIR/empty_prompt.log"
python3 loom.py generate --checkpoint /no/such/ckpt.npz --tokenizer "$WORKDIR/tokenizer.json" \
    --prompt "hi" > "$WORKDIR/missing_ckpt.log" 2>&1
check_grep "clean error on missing checkpoint (no traceback)" "^ERROR: checkpoint file not found" "$WORKDIR/missing_ckpt.log"

echo
echo "=== $PASS passed, $FAIL failed ==="
if [ "$FAIL" -ne 0 ]; then
    exit 1
fi
