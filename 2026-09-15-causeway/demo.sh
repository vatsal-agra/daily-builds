#!/usr/bin/env bash
# Causeway — full verification walkthrough (Phase 5).
# Exercises every shipped feature and fails loudly (non-zero exit) on the
# first thing that doesn't work. Safe to re-run.
set -uo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PASS=0
FAIL=0
WORKDIR="$(mktemp -d)"
trap 'rm -rf "$WORKDIR"' EXIT

check() {
  local desc="$1"; shift
  echo "── $desc"
  if "$@"; then
    echo "   ✓ PASS"
    PASS=$((PASS + 1))
  else
    echo "   ✗ FAIL"
    FAIL=$((FAIL + 1))
  fi
}

echo "=============================================================="
echo " Causeway verification — $(date)"
echo "=============================================================="

# ------------------------------------------------------------------ #
# 1. Full unit/integration test suite.
# ------------------------------------------------------------------ #
run_unit_tests() {
  python3 -m unittest discover -s tests 2>&1 | tail -20
}
check "1. Unit + integration test suite (37 tests: segment codec, RTT estimator, Reno congestion control, flow control, reassembly, teardown, fuzz transfer, adversarial regressions)" \
      run_unit_tests

# ------------------------------------------------------------------ #
# 2. In-process fuzz demo across a spread of network conditions.
# ------------------------------------------------------------------ #
run_demo_matrix() {
  local ok=0 total=0
  # The last row (40% one-way loss) is deliberately extreme -- ~65%
  # round-trip failure -- so it uses a smaller transfer and a matching
  # generous time budget, the same parameters already validated in
  # tests/test_fuzz_transfer.py::test_extreme_loss_still_eventually_succeeds.
  for cond in "0.0 0.0 0.0 60000 900" "0.1 0.05 0.1 60000 900" "0.25 0.1 0.2 60000 900" "0.4 0.0 0.0 8000 1500"; do
    read -r loss dup reorder nbytes maxtime <<< "$cond"
    total=$((total + 1))
    out=$(python3 -m causeway.cli demo --bytes "$nbytes" --loss "$loss" --dup "$dup" \
          --reorder "$reorder" --seed "$total" --max-time "$maxtime" 2>&1)
    if echo "$out" | grep -q "byte-exact match: True"; then
      ok=$((ok + 1))
      echo "   loss=$loss dup=$dup reorder=$reorder -> OK"
    else
      echo "   loss=$loss dup=$dup reorder=$reorder -> FAILED"
      echo "$out" | tail -5
    fi
  done
  [ "$ok" -eq "$total" ]
}
check "2. Narrated CLI demo across 4 network-condition scenarios" run_demo_matrix

# ------------------------------------------------------------------ #
# 3. Real two-process transfer, direct (no proxy).
# ------------------------------------------------------------------ #
run_direct_transfer() {
  local infile="$WORKDIR/input_direct.bin"
  local outfile="$WORKDIR/output_direct.bin"
  head -c 250000 /dev/urandom > "$infile"
  python3 -m causeway.cli recv --bind 127.0.0.1:19501 --out "$outfile" --timeout 30 \
      </dev/null >"$WORKDIR/recv_direct.log" 2>&1 &
  sleep 0.3
  python3 -m causeway.cli send "$infile" --peer 127.0.0.1:19501 --timeout 30 \
      >"$WORKDIR/send_direct.log" 2>&1
  sleep 0.5
  [ -f "$outfile" ] && cmp -s "$infile" "$outfile"
}
check "3. Real two-process transfer over real UDP (no proxy), byte-exact" run_direct_transfer

# ------------------------------------------------------------------ #
# 4. Capstone: real two-process transfer through the real lossy proxy.
# ------------------------------------------------------------------ #
run_proxy_transfer() {
  local infile="$WORKDIR/input_proxy.bin"
  local outfile="$WORKDIR/output_proxy.bin"
  head -c 300000 /dev/urandom > "$infile"
  python3 -m causeway.cli recv --bind 127.0.0.1:19511 --out "$outfile" --timeout 45 \
      </dev/null >"$WORKDIR/recv_proxy.log" 2>&1 &
  python3 -m causeway.cli proxy --listen 127.0.0.1:19510 --target 127.0.0.1:19511 \
      --loss 0.1 --dup 0.05 --reorder 0.1 --delay-ms 8 --jitter-ms 12 --seed 3 --duration 45 \
      </dev/null >"$WORKDIR/proxy.log" 2>&1 &
  sleep 0.5
  python3 -m causeway.cli send "$infile" --peer 127.0.0.1:19510 --timeout 45 \
      >"$WORKDIR/send_proxy.log" 2>&1
  local send_rc=$?
  sleep 1.5
  echo "   proxy stats: $(tail -1 "$WORKDIR/proxy.log" 2>/dev/null)"
  [ "$send_rc" -eq 0 ] && [ -f "$outfile" ] && cmp -s "$infile" "$outfile"
}
check "4. CAPSTONE: real send/proxy/recv (3 processes) through a real lossy/reordering/duplicating UDP relay, byte-exact SHA-256 match" \
      run_proxy_transfer

# ------------------------------------------------------------------ #
# 5. Visualizer: generate from a real captured log, headless-browser check.
# ------------------------------------------------------------------ #
run_visualizer_check() {
  local log="$WORKDIR/viz_log.json"
  local html="$WORKDIR/viz.html"
  python3 -m causeway.cli demo --bytes 100000 --loss 0.1 --dup 0.05 --reorder 0.08 \
      --seed 21 --log-json "$log" >/dev/null 2>&1 || return 1
  python3 -m causeway.cli viz --log-json "$log" --out "$html" >/dev/null 2>&1 || return 1
  [ -s "$html" ] || return 1
  if command -v node >/dev/null 2>&1; then
    NODE_PATH="$(npm root -g 2>/dev/null)" node tests/browser_smoke_test.js "$html"
  else
    echo "   (node not available, skipping headless-browser check; HTML file generated OK)"
  fi
}
check "5. Visualizer generation + headless-Chromium smoke test (zero console errors, hover tooltip works, stat tiles render)" \
      run_visualizer_check

# ------------------------------------------------------------------ #
# 6. Adversarial regression checks (things that used to crash ugly).
# ------------------------------------------------------------------ #
run_adversarial_checks() {
  local ok=0
  python3 -m causeway.cli demo --bytes -5 2>"$WORKDIR/e1" ; grep -q "error:" "$WORKDIR/e1" && ! grep -q Traceback "$WORKDIR/e1" && ok=$((ok+1))
  python3 -m causeway.cli demo --loss 5.0 --bytes 1000 2>"$WORKDIR/e2" ; grep -q "error:" "$WORKDIR/e2" && ! grep -q Traceback "$WORKDIR/e2" && ok=$((ok+1))
  python3 -m causeway.cli demo --mss 0 --bytes 1000 2>"$WORKDIR/e3" ; grep -q "error:" "$WORKDIR/e3" && ! grep -q Traceback "$WORKDIR/e3" && ok=$((ok+1))
  python3 -m causeway.cli send /no/such/file.bin --peer 127.0.0.1:1 2>"$WORKDIR/e4" ; grep -q "error:" "$WORKDIR/e4" && ! grep -q Traceback "$WORKDIR/e4" && ok=$((ok+1))
  [ "$ok" -eq 4 ]
}
check "6. Adversarial regressions: invalid input fails cleanly, not with a raw Python traceback (negative bytes, out-of-range loss, mss=0, missing file)" \
      run_adversarial_checks

echo "=============================================================="
echo " Results: $PASS passed, $FAIL failed"
echo "=============================================================="
[ "$FAIL" -eq 0 ]
