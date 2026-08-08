#!/usr/bin/env bash
# Orrery end-to-end demo/verification script.
#
# Runs the full unit test suite, then the CLI's self-checking `demo`
# walkthrough (which itself exercises every required + stretch feature
# and prints PASS/FAIL for each physics claim), then a few extra CLI
# smoke checks (checkpoint/resume round trip, error paths). Exits
# non-zero on the first failure.

set -euo pipefail
cd "$(dirname "${BASH_SOURCE[0]}")"

PY=python3
OUTDIR="$(mktemp -d)"
trap 'rm -rf "$OUTDIR"' EXIT

pass() { echo "  ok: $1"; }
fail() { echo "  FAIL: $1" >&2; exit 1; }

echo "== Orrery demo.sh =="
echo "Scratch output dir: $OUTDIR"
echo

echo "-- 1. Unit test suite --"
$PY -m unittest discover -s tests -v
pass "106-test unit suite green"
echo

echo "-- 2. Self-checking CLI demo (physics claims + reports) --"
$PY -m orrery.cli demo --outdir "$OUTDIR/demo_output"
pass "CLI demo: all PASS, exit 0"
echo

echo "-- 3. CLI smoke: info --"
$PY -m orrery.cli info | grep -q "solar_system" || fail "info didn't list solar_system"
pass "info lists scenarios"
echo

echo "-- 4. CLI smoke: checkpoint save + resume round trip --"
$PY -m orrery.cli run --scenario binary_star --steps 300 --out "$OUTDIR/ckpt.json" --report "$OUTDIR/run1.html"
[ -f "$OUTDIR/ckpt.json" ] || fail "checkpoint not written"
[ -f "$OUTDIR/run1.html" ] || fail "report not written"
$PY -m orrery.cli resume "$OUTDIR/ckpt.json" --steps 300 --dt 0.002738 --out "$OUTDIR/ckpt2.json" --report "$OUTDIR/run2.html"
[ -f "$OUTDIR/ckpt2.json" ] || fail "resumed checkpoint not written"
pass "checkpoint save + resume round trip"
echo

echo "-- 5. CLI smoke: Barnes-Hut benchmark --"
$PY -m orrery.cli bench --ns "10,50,200" --out "$OUTDIR/bench.html" | tail -3
[ -f "$OUTDIR/bench.html" ] || fail "benchmark report not written"
pass "benchmark report written"
echo

echo "-- 6. CLI smoke: clean errors on bad input (no raw tracebacks) --"
for args in \
  "run --scenario plummer_cluster --n 0 --steps 5" \
  "run --scenario binary_star --dt -1 --steps 5" \
  "resume /nonexistent/checkpoint.json --steps 5"
do
  set +e
  out=$($PY -m orrery.cli $args 2>&1)
  code=$?
  set -e
  [ "$code" -eq 0 ] && fail "expected nonzero exit for: orrery $args"
  echo "$out" | grep -q "Traceback" && fail "raw traceback leaked for: orrery $args"
  echo "$out" | grep -q "ERROR" || fail "no clean ERROR message for: orrery $args"
done
pass "all bad-input cases fail cleanly, no raw tracebacks"
echo

echo "-- 7. CLI smoke: collisions flag end-to-end --"
coll_out=$($PY -m orrery.cli run --scenario plummer_cluster --n 15 --seed 3 --steps 200 --collisions --report "$OUTDIR/coll.html")
echo "$coll_out" | grep -q "energy:" || fail "collisions run failed"
pass "collisions scenario ran end-to-end"

echo "-- 8. CLI robustness: doesn't crash when stdout closes early (e.g. | head) --"
set +o pipefail
out=$($PY -m orrery.cli run --scenario solar_system --steps 5000 2>&1 | head -n 2)
set -o pipefail
echo "$out" | grep -q "BrokenPipeError" && fail "raw BrokenPipeError leaked when piped to head"
pass "clean under an early-closing pipe (no BrokenPipeError)"
echo

echo "=================================================="
echo "ALL CHECKS PASSED"
echo "=================================================="
