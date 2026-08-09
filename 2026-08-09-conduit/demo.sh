#!/usr/bin/env bash
# Conduit verification suite: unit/integration tests, the full CLI demo,
# the standalone conduit-cp demo, and a couple of CLI smoke checks.
# Exits non-zero (and stops immediately) on the first failure.
set -euo pipefail
cd "$(dirname "$0")"

BOLD='\033[1m'
GREEN='\033[32m'
RED='\033[31m'
RESET='\033[0m'

section() { echo -e "\n${BOLD}== $1 ==${RESET}"; }
pass() { echo -e "${GREEN}PASS${RESET}: $1"; }
fail() { echo -e "${RED}FAIL${RESET}: $1"; exit 1; }

WORKDIR=$(mktemp -d)
trap 'rm -rf "$WORKDIR"' EXIT

section "1/4 — full test suite (unit + integration + HTTP + curl oracle + conduit-cp)"
if python3 -m unittest discover -s tests -v; then
    pass "test suite"
else
    fail "test suite"
fi

section "2/4 — end-to-end CLI demo (curl through 3 netsim scenarios + conduit-cp)"
REPORT="$WORKDIR/demo_report.html"
if python3 -m conduit.cli demo --report "$REPORT"; then
    pass "conduit.cli demo"
else
    fail "conduit.cli demo"
fi
if [ -s "$REPORT" ]; then
    pass "trace report generated ($(wc -c < "$REPORT") bytes)"
else
    fail "trace report was not generated"
fi

section "3/4 — standalone conduit-cp smoke test"
head -c 500000 /dev/urandom > "$WORKDIR/payload.bin"
mkdir -p "$WORKDIR/out"
if python3 -m tools.conduit_cp demo "$WORKDIR/payload.bin" "$WORKDIR/out" --loss 0.06 --dup 0.02 --reorder 0.05 --seed 7; then
    pass "conduit-cp demo"
else
    fail "conduit-cp demo"
fi
SRC_SHA=$(sha256sum "$WORKDIR/payload.bin" | cut -d' ' -f1)
DST_SHA=$(sha256sum "$WORKDIR/out/payload.bin" | cut -d' ' -f1)
if [ "$SRC_SHA" = "$DST_SHA" ]; then
    pass "conduit-cp file integrity ($SRC_SHA)"
else
    fail "conduit-cp file integrity mismatch: $SRC_SHA != $DST_SHA"
fi

section "4/4 — CLI input-validation smoke checks (must fail cleanly, not crash)"
if python3 -m tools.conduit_cp send /no/such/file.bin 127.0.0.1 9 2>/dev/null; then
    fail "conduit-cp send accepted a nonexistent file"
else
    pass "conduit-cp send rejects a nonexistent file"
fi
if python3 -m conduit.cli serve /no/such/dir 2>/dev/null; then
    fail "conduit serve accepted a nonexistent directory"
else
    pass "conduit serve rejects a nonexistent directory"
fi

echo -e "\n${GREEN}${BOLD}ALL CHECKS PASSED${RESET}"
