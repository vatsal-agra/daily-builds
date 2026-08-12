#!/usr/bin/env bash
# End-to-end verification: the full test suite, then the scripted
# multi-node CLI demo, then a quick sanity pass over the persisted
# `nonce local` commands. Exits non-zero on the first failure.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

echo "=================================================================="
echo " 1/3  Test suite (crypto, merkle, blockchain, network, wallet, ...)"
echo "=================================================================="
python3 -m unittest discover -s tests -v

echo
echo "=================================================================="
echo " 2/3  Scripted end-to-end demo (nonce demo)"
echo "=================================================================="
python3 -m nonce demo

echo
echo "=================================================================="
echo " 3/3  Persisted single-node CLI (nonce local ...)"
echo "=================================================================="
DATA_DIR="$(mktemp -d)"
trap 'rm -rf "$DATA_DIR"' EXIT

python3 -m nonce local --data-dir "$DATA_DIR" init
python3 -m nonce local --data-dir "$DATA_DIR" mine --blocks 3
BALANCE_BEFORE=$(python3 -m nonce local --data-dir "$DATA_DIR" balance)
echo "balance before send: $BALANCE_BEFORE"

RECIPIENT=$(python3 -m nonce wallet | awk '/^address:/ {print $2}')
python3 -m nonce local --data-dir "$DATA_DIR" send "$RECIPIENT" 5.0
python3 -m nonce local --data-dir "$DATA_DIR" history

# invalid input must be rejected cleanly, not silently accepted or crash with a traceback
if python3 -m nonce local --data-dir "$DATA_DIR" send notAnAddress 1 2>/tmp/nonce_demo_err; then
    echo "FAIL: sending to an invalid address should have been rejected"
    exit 1
fi
grep -q "not a valid Nonce address" /tmp/nonce_demo_err
echo "invalid-address rejection: OK"

echo
echo "=================================================================="
echo " ALL GREEN"
echo "=================================================================="
