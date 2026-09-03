#!/usr/bin/env bash
# Keystone end-to-end demo/verification script.
# Runs the full test suite, then every CLI path, then (if available) a
# real headless-Chromium check of the block explorer. Exits non-zero on
# any failure.
set -uo pipefail
cd "$(dirname "$0")"

RED='\033[0;31m'; GREEN='\033[0;32m'; YELLOW='\033[1;33m'; BOLD='\033[1m'; NC='\033[0m'
FAILED=0

section() { echo -e "\n${BOLD}=== $1 ===${NC}"; }
ok()      { echo -e "${GREEN}✓${NC} $1"; }
fail()    { echo -e "${RED}✗${NC} $1"; FAILED=1; }

section "1/6 Unit + integration test suite (unittest, stdlib only)"
if python3 -m unittest discover -s tests -p "test_*.py" -v 2>&1 | tee /tmp/keystone_tests.log | tail -5; then
    COUNT=$(grep -oE "Ran [0-9]+ test" /tmp/keystone_tests.log | grep -oE "[0-9]+" | tail -1)
    if grep -q "^OK" /tmp/keystone_tests.log; then
        ok "all $COUNT tests passed"
    else
        fail "test suite reported failures (see above)"
    fi
else
    fail "test suite crashed"
fi

section "2/6 CLI: keygen"
if python3 -m keystone keygen | tee /tmp/keystone_keygen.log | grep -q "address:"; then
    ok "keygen produced a wallet"
else
    fail "keygen did not produce expected output"
fi

section "3/6 CLI: script-demo (m-of-n multisig scripting stretch feature)"
if python3 -m keystone script-demo | tee /tmp/keystone_script.log | grep -q "RESULT: PASS"; then
    ok "script-demo passed"
else
    fail "script-demo did not report PASS"
fi

section "4/6 CLI: demo (full multi-node network -- mining, gossip, fork resolution, payments)"
if python3 -m keystone demo --nodes 5 --seconds 10 --base-port 25100 | tee /tmp/keystone_demo.log | grep -q "RESULT: PASS"; then
    ok "5-node network demo converged and PASSED"
else
    fail "network demo did not report PASS"
fi

section "5/6 CLI: input validation / clean error handling"
python3 -m keystone demo --nodes 0 --seconds 1 >/tmp/keystone_badinput.log 2>&1
if [ $? -ne 0 ] && grep -q "must be at least 1" /tmp/keystone_badinput.log; then
    ok "bad --nodes input rejected with a clean error, not a crash"
else
    fail "bad input handling regressed"
fi

section "6/6 Headless-browser check of the block explorer"
if python3 tests/browser_check.py | tee /tmp/keystone_browser.log; then
    if grep -q "^PASS" /tmp/keystone_browser.log; then
        ok "explorer renders correctly in real Chromium with zero console errors"
    elif grep -q "^SKIP" /tmp/keystone_browser.log; then
        echo -e "${YELLOW}(skipped -- optional dependency unavailable, HTTP-level explorer tests already ran in step 1)${NC}"
    else
        fail "browser check failed"
    fi
else
    fail "browser check crashed"
fi

echo
if [ "$FAILED" -eq 0 ]; then
    echo -e "${GREEN}${BOLD}ALL CHECKS PASSED${NC}"
    exit 0
else
    echo -e "${RED}${BOLD}ONE OR MORE CHECKS FAILED${NC}"
    exit 1
fi
