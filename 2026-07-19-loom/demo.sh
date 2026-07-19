#!/usr/bin/env bash
# Loom demo: exercises every feature end-to-end. Run from the project root.
set -euo pipefail
cd "$(dirname "$0")"

pass=0
fail=0
check() {
    local desc="$1"; shift
    echo "--- $desc"
    if "$@"; then
        echo "    OK"
        pass=$((pass + 1))
    else
        echo "    FAILED"
        fail=$((fail + 1))
    fi
}

echo "=== Loom demo ==="
echo

echo "[1/7] Unit test suite (autodiff, model, optimizer, tokenizer, checkpoint, sampling)"
check "unittest suite" python3 -m unittest discover -s tests

echo
echo "[2/7] Gradient check every autodiff op against numerical finite differences"
check "gradcheck CLI" python3 -m loom.cli gradcheck

echo
echo "[3/7] Char tokenizer round-trip"
check "tokenize CLI" python3 -m loom.cli tokenize

echo
echo "[4/7] From-scratch BPE tokenizer (stretch): train merges, show compression, round-trip"
check "bpe CLI" python3 -m loom.cli bpe --merges 100

echo
echo "[5/7] Quick end-to-end training run (small, just to prove the pipeline works live)"
check "train CLI (smoke)" python3 -m loom.cli train --steps 60 --d-model 32 --n-heads 2 \
    --n-layers 2 --d-ff 64 --block-size 32 --batch-size 16 --out /tmp/loom_demo_ckpt

echo
echo "[6/7] Generate from the smoke-trained checkpoint (temperature/top-k/top-p all exercised)"
check "generate: temperature" python3 -m loom.cli generate --ckpt /tmp/loom_demo_ckpt --prompt "The " -n 60 --temperature 0.8 --seed 1
check "generate: top-k"       python3 -m loom.cli generate --ckpt /tmp/loom_demo_ckpt --prompt "The " -n 60 --top-k 10 --seed 1
check "generate: top-p"       python3 -m loom.cli generate --ckpt /tmp/loom_demo_ckpt --prompt "The " -n 60 --top-p 0.9 --seed 1
check "generate: greedy"      python3 -m loom.cli generate --ckpt /tmp/loom_demo_ckpt --prompt "The " -n 60 --temperature 0 --seed 1

echo
echo "[7/7] Attention visualizer: capture real attention weights from a generation run and render HTML"
check "attn viz" python3 -m loom.cli attn --ckpt /tmp/loom_demo_ckpt --prompt "The old" -n 30 --out /tmp/loom_demo_attn.html

if [ -f checkpoints/loom.npz ]; then
    echo
    echo "[bonus] Sample from the fully-trained checkpoint (checkpoints/loom.npz) to show real learned structure"
    python3 -m loom.cli generate --ckpt checkpoints/loom --prompt "The " -n 300 --temperature 0.7 --seed 7
fi

echo
echo "=== demo.sh: $pass passed, $fail failed ==="
if [ "$fail" -ne 0 ]; then
    exit 1
fi
