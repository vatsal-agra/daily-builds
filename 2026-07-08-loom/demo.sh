#!/usr/bin/env bash
# Loom demo -- exercises every feature end-to-end from a clean checkout.
set -euo pipefail
cd "$(dirname "$0")"

PASS=0
FAIL=0
check() {
    local desc="$1"
    shift
    if "$@" >/tmp/loom_demo_step.log 2>&1; then
        echo "  [PASS] $desc"
        PASS=$((PASS + 1))
    else
        echo "  [FAIL] $desc"
        tail -20 /tmp/loom_demo_step.log | sed 's/^/         /'
        FAIL=$((FAIL + 1))
    fi
}

echo "=== Loom demo ==="

echo
echo "-- D1: full unit + gradient-check + integration test suite --"
check "run every test module (python3 -m unittest discover)" \
    python3 -m unittest discover -s tests -v

echo
echo "-- D2: tokenizer CLI --"
check "train + roundtrip a tokenizer via the CLI" \
    python3 cli.py tokenize --corpus data/corpus.txt --vocab-size 300 \
    --out /tmp/loom_demo_tok.json --text "a brand new sentence, with punctuation!"

echo
echo "-- D3: tiny end-to-end training run (fresh model, a few seconds) --"
check "train a tiny model from scratch via the CLI" \
    python3 cli.py train --steps 60 --n-embd 32 --n-head 4 --n-layer 2 \
    --block-size 32 --batch-size 8 --vocab-size 300 --warmup-steps 10 \
    --eval-every 30 --eval-iters 3 --log-every 30 --out-dir /tmp/loom_demo_ckpt

echo
echo "-- D4: generation from the freshly trained checkpoint --"
check "generate with KV-cache" \
    python3 cli.py generate --checkpoint-dir /tmp/loom_demo_ckpt \
    --prompt "Long ago," --max-new-tokens 40 --seed 0
check "generate without KV-cache (sliding-window path)" \
    python3 cli.py generate --checkpoint-dir /tmp/loom_demo_ckpt \
    --prompt "Long ago," --max-new-tokens 40 --seed 0 --no-kv-cache

echo
echo "-- D5: real trained checkpoint (checkpoints/, if present) --"
if [ -d "checkpoints" ] && [ -f "checkpoints/model.npz" ]; then
    check "generate from the real shipped checkpoint" \
        python3 cli.py generate --checkpoint-dir checkpoints \
        --prompt "Long ago, in the Whispering Forest," --max-new-tokens 120 --seed 1
else
    echo "  [SKIP] checkpoints/ not present"
fi

echo
echo "-- D6: attention visualizer --"
if [ -d "checkpoints" ] && [ -f "checkpoints/model.npz" ]; then
    check "render attention_viz.html from the real checkpoint" \
        python3 cli.py viz --checkpoint-dir checkpoints --max-new-tokens 20 \
        --out /tmp/loom_demo_viz.html
else
    check "render attention_viz.html from the demo checkpoint" \
        python3 cli.py viz --checkpoint-dir /tmp/loom_demo_ckpt --max-new-tokens 20 \
        --out /tmp/loom_demo_viz.html
fi

echo
echo "-- D7: edge cases --"
check "empty prompt does not crash generation" \
    python3 cli.py generate --checkpoint-dir /tmp/loom_demo_ckpt --prompt "" --max-new-tokens 10
check "unicode prompt survives tokenizer roundtrip" \
    python3 -c "
import sys; sys.path.insert(0, '.')
from loom.tokenizer import BPETokenizer
tok = BPETokenizer(); tok.load('/tmp/loom_demo_tok.json')
s = 'héllo 世界 🚀 unseen-during-training text!!'
assert tok.decode(tok.encode(s)) == s, 'roundtrip mismatch'
print('roundtrip OK:', repr(s))
"

echo
echo "=== Loom demo summary: $PASS passed, $FAIL failed ==="
if [ "$FAIL" -ne 0 ]; then
    exit 1
fi
