#!/usr/bin/env bash
# Cryptex demo script — exercises every CLI subcommand end-to-end.
# Run from the project directory: bash demo.sh
# Requires Python 3.11+.

set -euo pipefail
cd "$(dirname "$0")"
PY=python3

PASS=0; FAIL=0

check() {
    local name="$1"; shift
    if "$@" >/dev/null 2>&1; then
        echo "  OK  $name"; PASS=$((PASS + 1))
    else
        echo "  FAIL  $name"; FAIL=$((FAIL + 1))
    fi
}

echo "=============================="
echo "  CRYPTEX  CLI DEMO"
echo "=============================="

# --- SHA-256 ---
echo ""
echo "[SHA-256]"
check "sha256 hash --text" $PY cryptex.py sha256 hash --text "hello world"
check "sha256 hash --file" $PY cryptex.py sha256 hash --file cryptex.py
KEY_HEX=$(python3 -c "import os; print(os.urandom(32).hex())")
check "sha256 hmac" $PY cryptex.py sha256 hmac "$KEY_HEX" --text "message"
check "sha256 test vectors" $PY cryptex.py sha256 test

# --- AES-256 ---
echo ""
echo "[AES-256]"
AES_KEY=$($PY cryptex.py aes keygen | grep -oP '(?<=key \(keep secret\): )\S+')
check "aes keygen" $PY cryptex.py aes keygen
CT=$($PY cryptex.py aes encrypt "$AES_KEY" --text "Hello, Cryptex!")
check "aes encrypt --text" echo "$CT"
PT=$($PY cryptex.py aes decrypt "$AES_KEY" "$CT" 2>&1)
check "aes decrypt" test "$PT" = "Hello, Cryptex!"
check "aes test vectors" $PY cryptex.py aes test
# Error handling
check "aes bad hex → clean error" bash -c "$PY cryptex.py aes encrypt badhex --text hi 2>&1 | grep -q 'Error:'"
check "aes no text/file → clean error" bash -c "$PY cryptex.py aes encrypt $AES_KEY 2>&1 | grep -q 'Error:'"

# --- RSA ---
echo ""
echo "[RSA-2048]"
check "rsa keygen" $PY cryptex.py rsa keygen --bits 2048
CT_RSA=$($PY cryptex.py rsa encrypt rsa_pub.pem --message "top secret")
check "rsa encrypt" echo "$CT_RSA"
PT_RSA=$($PY cryptex.py rsa decrypt rsa_priv.pem "$CT_RSA")
check "rsa decrypt" test "$PT_RSA" = "top secret"
SIG=$($PY cryptex.py rsa sign rsa_priv.pem --message "sign this")
check "rsa sign" echo "$SIG"
check "rsa verify" $PY cryptex.py rsa verify rsa_pub.pem "$SIG" --message "sign this"

# --- ECDH ---
echo ""
echo "[P-256 ECDH]"
ALICE=$($PY cryptex.py ecdh keygen)
ALICE_PRIV=$(echo "$ALICE" | grep Private | awk '{print $3}')
ALICE_PUB=$(echo "$ALICE" | grep Public | awk '{print $3}')
BOB=$($PY cryptex.py ecdh keygen)
BOB_PRIV=$(echo "$BOB" | grep Private | awk '{print $3}')
BOB_PUB=$(echo "$BOB" | grep Public | awk '{print $3}')
S_AB=$($PY cryptex.py ecdh exchange "$ALICE_PRIV" "$BOB_PUB" | awk '{print $NF}')
S_BA=$($PY cryptex.py ecdh exchange "$BOB_PRIV" "$ALICE_PUB" | awk '{print $NF}')
check "ecdh shared secret matches" test "$S_AB" = "$S_BA"
check "ecdh bad key → clean error" bash -c "$PY cryptex.py ecdh exchange badhex $BOB_PUB 2>&1 | grep -q 'Error:'"

# --- ECDSA ---
echo ""
echo "[P-256 ECDSA]"
PRIV_EC=$($PY cryptex.py ecdsa keygen | grep Private | awk '{print $3}')
PUB_EC=$($PY cryptex.py ecdsa keygen | grep Public | awk '{print $3}')
# Use same key
EC_KEYS=$($PY cryptex.py ecdsa keygen)
PRIV_EC=$(echo "$EC_KEYS" | grep Private | awk '{print $3}')
PUB_EC=$(echo "$EC_KEYS" | grep Public | awk '{print $3}')
SIG_EC=$($PY cryptex.py ecdsa sign "$PRIV_EC" --message "hello ecdsa")
check "ecdsa sign" echo "$SIG_EC"
check "ecdsa verify" $PY cryptex.py ecdsa verify "$PUB_EC" "$SIG_EC" --message "hello ecdsa"
check "ecdsa bad sig → INVALID" bash -c "$PY cryptex.py ecdsa verify $PUB_EC ${SIG_EC:1} --message 'hello ecdsa' 2>&1 | grep -qE 'INVALID|Error'"

# --- ChaCha20-Poly1305 ---
echo ""
echo "[ChaCha20-Poly1305]"
CC_KEYGEN=$($PY cryptex.py chacha keygen)
CC_KEY=$(echo "$CC_KEYGEN" | grep '^Key:' | awk '{print $2}')
CC_NONCE=$(echo "$CC_KEYGEN" | grep '^Nonce:' | awk '{print $2}')
CC_CT=$($PY cryptex.py chacha encrypt "$CC_KEY" "$CC_NONCE" --text "ChaCha20 message" --aad "header")
check "chacha encrypt" echo "$CC_CT"
CC_PT=$($PY cryptex.py chacha decrypt "$CC_KEY" "$CC_NONCE" "$CC_CT" --aad "header")
check "chacha decrypt" test "$CC_PT" = "ChaCha20 message"
check "chacha test vectors" $PY cryptex.py chacha test

# --- Full demo ---
echo ""
echo "[Full demo]"
check "demo 20/20" $PY cryptex.py demo

# --- Cleanup ---
rm -f rsa_pub.pem rsa_priv.pem

echo ""
echo "=============================="
echo "  RESULT: $PASS passed, $FAIL failed"
echo "=============================="
[ "$FAIL" -eq 0 ]
