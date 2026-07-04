#!/usr/bin/env bash
# Ironkey demo/verification script — runs the full unit test suite, then
# exercises every feature end to end through the real CLI, exactly as a
# user would invoke it. Exits non-zero on any failure.
set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PY=python3
PASS=0
FAIL=0

check() {
  local desc="$1"; shift
  if "$@" >/tmp/ironkey_demo_out.$$ 2>&1; then
    echo "  [PASS] $desc"
    PASS=$((PASS + 1))
  else
    echo "  [FAIL] $desc"
    cat /tmp/ironkey_demo_out.$$
    FAIL=$((FAIL + 1))
  fi
  rm -f /tmp/ironkey_demo_out.$$
}

echo "=== 1. Unit test suite (122 tests: bigint, sha256, hmac/kdf, aes, modes, rsa, x25519, session, vault, padding-oracle attack, viz, cli) ==="
check "full unittest suite" "$PY" -m unittest discover -s tests -t . -v

echo
echo "=== 2. CLI feature walkthrough (required features) ==="
check "hash" "$PY" cli.py hash --text "ironkey demo"
check "hmac" "$PY" cli.py hmac --key demo --text "ironkey demo"
check "kdf" "$PY" cli.py kdf --password "demo password" --iterations 1000

KEY=$($PY -c "import os; print(os.urandom(32).hex())")
$PY cli.py aes encrypt --key-hex "$KEY" --mode gcm --text "aes-gcm demo message" --out /tmp/ironkey_demo_gcm.bin
check "aes gcm round trip" bash -c "[ \"\$($PY cli.py aes decrypt --key-hex $KEY --mode gcm --in /tmp/ironkey_demo_gcm.bin)\" = 'aes-gcm demo message' ]"
$PY cli.py aes encrypt --key-hex "$KEY" --mode cbc --text "aes-cbc demo message" --out /tmp/ironkey_demo_cbc.bin
check "aes cbc round trip" bash -c "[ \"\$($PY cli.py aes decrypt --key-hex $KEY --mode cbc --in /tmp/ironkey_demo_cbc.bin)\" = 'aes-cbc demo message' ]"

$PY cli.py rsa genkey --bits 2048 --pub-out /tmp/ironkey_demo_pub.json --priv-out /tmp/ironkey_demo_priv.json
$PY cli.py rsa encrypt --pub /tmp/ironkey_demo_pub.json --text "rsa oaep demo" --out /tmp/ironkey_demo_rsa.bin
check "rsa oaep round trip" bash -c "[ \"\$($PY cli.py rsa decrypt --priv /tmp/ironkey_demo_priv.json --in /tmp/ironkey_demo_rsa.bin)\" = 'rsa oaep demo' ]"
$PY cli.py rsa sign --priv /tmp/ironkey_demo_priv.json --text "sign me" --out /tmp/ironkey_demo_sig.bin
check "rsa pss verify (valid)" bash -c "[ \"\$($PY cli.py rsa verify --pub /tmp/ironkey_demo_pub.json --text 'sign me' --sig /tmp/ironkey_demo_sig.bin)\" = 'VALID' ]"
check "rsa pss verify rejects tampered message" bash -c "! $PY cli.py rsa verify --pub /tmp/ironkey_demo_pub.json --text 'tampered' --sig /tmp/ironkey_demo_sig.bin"

echo
echo "=== 3. Stretch features ==="
check "x25519 handshake demo" "$PY" cli.py dh demo
check "encrypted session demo (tamper + replay detection)" "$PY" cli.py session demo

$PY cli.py vault encrypt --password "demo vault password" --iterations 1000 --text "vault contents" --out /tmp/ironkey_demo_vault.bin
check "vault round trip" bash -c "[ \"\$($PY cli.py vault decrypt --password 'demo vault password' --in /tmp/ironkey_demo_vault.bin)\" = 'vault contents' ]"
check "vault rejects wrong password" bash -c "! $PY cli.py vault decrypt --password 'wrong password' --in /tmp/ironkey_demo_vault.bin"

check "padding-oracle attack recovers plaintext with no key" "$PY" cli.py attack demo --text "attack this secret"
check "html visualizer generates" "$PY" cli.py viz --out /tmp/ironkey_demo_viz.html

echo
echo "=== 4. Full end-to-end demo command ==="
check "cli.py demo (every module, one process)" "$PY" cli.py demo

echo
echo "=================================================="
echo "  $PASS passed, $FAIL failed"
echo "=================================================="

rm -f /tmp/ironkey_demo_*.bin /tmp/ironkey_demo_*.json /tmp/ironkey_demo_viz.html

if [ "$FAIL" -ne 0 ]; then
  exit 1
fi
