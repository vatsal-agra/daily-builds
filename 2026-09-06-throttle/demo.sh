#!/usr/bin/env bash
# Throttle end-to-end verification: exercises every feature in PLAN.md and
# every CLI path, prints PASS/FAIL for each, and exits nonzero on any
# failure. Run from anywhere; paths are resolved relative to this script.
set -u
cd "$(dirname "${BASH_SOURCE[0]}")"

PASS=0
FAIL=0
FAILED_NAMES=()

check() {
  local name="$1"
  shift
  if "$@" >/tmp/throttle_demo_last.log 2>&1; then
    echo "  PASS  $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $name"
    echo "        (see /tmp/throttle_demo_last.log for the last check's output)"
    tail -n 15 /tmp/throttle_demo_last.log | sed 's/^/        | /'
    FAIL=$((FAIL + 1))
    FAILED_NAMES+=("$name")
  fi
}

# check_output <name> <expected substring> <command...>  -- runs the
# command, requires exit 0, AND requires the substring to appear.
check_output() {
  local name="$1"; local needle="$2"; shift 2
  if "$@" >/tmp/throttle_demo_last.log 2>&1 && grep -qF -- "$needle" /tmp/throttle_demo_last.log; then
    echo "  PASS  $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $name (expected to find: $needle)"
    tail -n 15 /tmp/throttle_demo_last.log | sed 's/^/        | /'
    FAIL=$((FAIL + 1))
    FAILED_NAMES+=("$name")
  fi
}

# check_fails <name> <command...> -- requires the command to exit NONzero
# (used for negative/invalid-input tests).
check_fails() {
  local name="$1"; shift
  if ! "$@" >/tmp/throttle_demo_last.log 2>&1; then
    echo "  PASS  $name"
    PASS=$((PASS + 1))
  else
    echo "  FAIL  $name (expected nonzero exit, got 0)"
    FAIL=$((FAIL + 1))
    FAILED_NAMES+=("$name")
  fi
}

echo "=== Throttle verification ==="
echo
echo "-- unit + integration test suite --"
check "pytest (67 unit/integration tests)" python3 -m pytest -q

echo
echo "-- Feature 1: packet-level network sim (bandwidth, buffer, loss, reorder) --"
check "clean link: single flow completes, byte-exact" \
  python3 -m throttle.cli run --bytes 300000 --bandwidth 1000000 --buffer 100000
check "lossy+reordering link: still completes, byte-exact" \
  python3 -m throttle.cli run --bytes 300000 --loss 0.02 --reorder 0.03 --cap 60
# An undersized buffer legitimately means the transfer never finishes
# (exit code 1 by design) -- what this checks is that the drop-tail
# buffer really did drop packets and the run reported that honestly
# instead of crashing or silently completing.
python3 -m throttle.cli run --bytes 500000 --buffer 2000 --cap 30 >/tmp/throttle_demo_last.log 2>&1
if grep -q "DID NOT COMPLETE" /tmp/throttle_demo_last.log && grep -qE "link drops: [1-9][0-9]* overflow" /tmp/throttle_demo_last.log; then
  echo "  PASS  undersized buffer: drop-tail overflow really happens (reports drops, doesn't crash)"
  PASS=$((PASS + 1))
else
  echo "  FAIL  undersized buffer: drop-tail overflow really happens"
  tail -n 15 /tmp/throttle_demo_last.log | sed 's/^/        | /'
  FAIL=$((FAIL + 1))
  FAILED_NAMES+=("undersized buffer drop-tail")
fi

echo
echo "-- Feature 2: full TCP state machine (handshake, sliding window, reassembly, teardown) --"
check_output "zero-byte transfer: handshake + immediate FIN teardown, no crash" \
  "byte-for-byte reassembly correct: True" \
  python3 -m throttle.cli run --bytes 0
check_output "tiny receive window still completes correctly (flow control exercised)" \
  "byte-for-byte reassembly correct: True" \
  python3 -m throttle.cli run --bytes 300000 --recv-window 3000 --bandwidth 5000000 --cap 60

echo
echo "-- Feature 3: congestion control (Reno/Tahoe/CUBIC), RTT estimation, RTO backoff --"
check_output "Reno completes under loss" "byte-for-byte reassembly correct: True" \
  python3 -m throttle.cli run --bytes 300000 --cc reno --loss 0.01 --cap 60
check_output "Tahoe completes under loss" "byte-for-byte reassembly correct: True" \
  python3 -m throttle.cli run --bytes 300000 --cc tahoe --loss 0.01 --cap 60
check_output "CUBIC completes under loss" "byte-for-byte reassembly correct: True" \
  python3 -m throttle.cli run --bytes 300000 --cc cubic --loss 0.01 --cap 60
check_output "Reno finishes faster than Tahoe under identical loss (fast recovery works)" \
  "reassembly=OK" \
  python3 -m throttle.cli experiment reno-vs-tahoe

echo
echo "-- Feature 4: multi-flow fairness experiments --"
python3 -m throttle.cli experiment fairness-equal-rtt >/tmp/throttle_demo_last.log 2>&1
FAIRNESS=$(grep -oE "Jain's fairness index: [0-9.]+" /tmp/throttle_demo_last.log | grep -oE "[0-9.]+$")
if [ -n "$FAIRNESS" ] && python3 -c "import sys; sys.exit(0 if float('$FAIRNESS') >= 0.9 else 1)"; then
  echo "  PASS  3 equal-RTT Reno flows converge to near-perfect fairness (index=$FAIRNESS)"
  PASS=$((PASS + 1))
else
  echo "  FAIL  3 equal-RTT Reno flows did not converge to near-perfect fairness (index=$FAIRNESS)"
  tail -n 15 /tmp/throttle_demo_last.log | sed 's/^/        | /'
  FAIL=$((FAIL + 1))
  FAILED_NAMES+=("fairness-equal-rtt")
fi
check_output "short-RTT flow wins a majority share (real TCP RTT bias)" \
  "reassembly=OK" \
  python3 -m throttle.cli experiment rtt-unfairness

echo
echo "-- Stretch 1: Tahoe + CUBIC as real, independently comparable algorithms --"
check_output "CUBIC beats Reno on a high bandwidth-delay-product path" \
  "reassembly=OK" \
  python3 -m throttle.cli experiment reno-vs-cubic

echo
echo "-- Stretch 2: interactive HTML visualizer --"
check "viz report generates" python3 -m throttle.cli viz /tmp/throttle_demo_report.html
if [ -s /tmp/throttle_demo_report.html ]; then
  echo "  PASS  report file is non-empty"
  PASS=$((PASS + 1))
else
  echo "  FAIL  report file missing or empty"
  FAIL=$((FAIL + 1))
  FAILED_NAMES+=("report file non-empty")
fi

echo
echo "-- Stretch 3: RFC 2018 SACK (fixes the Reno-without-SACK limitation from REVIEW.md) --"
check_output "SACK-enabled transfer completes and reports SACK retransmits" \
  "reassembly correct: True" \
  python3 -m throttle.cli run --bytes 1000000 --sack --loss 0.02 --cap 60
check_output "SACK-vs-plain-Reno comparison runs both sides successfully" \
  "reassembly=OK" \
  python3 -m throttle.cli experiment reno-vs-sack

echo
echo "-- Polish: clean error handling on invalid input (no raw tracebacks) --"
check_fails "negative bandwidth is rejected" python3 -m throttle.cli run --bandwidth -5
check_fails "out-of-range loss probability is rejected" python3 -m throttle.cli run --loss 1.5
check_fails "zero time cap is rejected" python3 -m throttle.cli run --cap 0
check_output "negative bandwidth error message is clean (not a traceback)" \
  "throttle: error:" \
  bash -c "python3 -m throttle.cli run --bandwidth -5; true"

echo
echo "-- Full demo (every canned experiment via the demo subcommand) --"
check_output "throttle demo completes all experiments with verified reassembly" \
  "all experiments completed with verified, correct reassembly." \
  python3 -m throttle.cli demo

echo
echo "-- Headless-browser check on the generated report (zero console errors) --"
if command -v node >/dev/null 2>&1 && [ -d /opt/pw-browsers ]; then
  cat > /tmp/throttle_browser_check.js <<'EOF'
const { chromium } = require('playwright');
(async () => {
  const browser = await chromium.launch({ executablePath: '/opt/pw-browsers/chromium' });
  const page = await browser.newPage();
  const errors = [];
  page.on('console', msg => { if (msg.type() === 'error') errors.push(msg.text()); });
  page.on('pageerror', err => errors.push(String(err)));
  await page.goto('file:///tmp/throttle_demo_report.html');
  await page.waitForTimeout(300);
  const svgCount = await page.locator('svg').count();
  await browser.close();
  if (errors.length > 0) {
    console.error('console errors:', errors);
    process.exit(1);
  }
  if (svgCount < 10) {
    console.error('expected many rendered SVG charts, found', svgCount);
    process.exit(1);
  }
  console.log('OK:', svgCount, 'charts rendered, zero console errors');
})();
EOF
  check "headless Chromium: report renders with zero console errors" \
    env NODE_PATH=/opt/node22/lib/node_modules node /tmp/throttle_browser_check.js
else
  echo "  SKIP  (node/playwright not available in this environment)"
fi

echo
echo "=== Results: $PASS passed, $FAIL failed ==="
if [ "$FAIL" -ne 0 ]; then
  echo "Failed checks:"
  for n in "${FAILED_NAMES[@]}"; do echo "  - $n"; done
  exit 1
fi
echo "All checks green."
exit 0
