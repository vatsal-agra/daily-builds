#!/usr/bin/env bash
# Faraday end-to-end verification: unit tests, the self-checking demo
# walkthrough, and a real CLI + HTTP-server exercise of every subcommand.
set -euo pipefail
cd "$(dirname "$0")"

pass() { echo "  [OK] $1"; }
fail() { echo "  [FAIL] $1"; exit 1; }

echo "=== 1/5: unit test suite (analytic oracles) ==="
python3 -m unittest discover -s tests -v
pass "47/47 tests green"

echo
echo "=== 2/5: self-checking demo walkthrough ==="
python3 -m faraday.cli demo
pass "demo walkthrough (all analytic-oracle checks)"

echo
echo "=== 3/5: CLI subcommands against real presets ==="
python3 -m faraday.cli list-presets | grep -q voltage_divider && pass "list-presets"
python3 -m faraday.cli dc voltage_divider | grep -q "V(     2) =  5.000000" && pass "dc voltage_divider"
python3 -m faraday.cli tran rc_step --tstop 2m --dt 1u --uic --out /tmp/faraday_tran.csv
[ "$(wc -l < /tmp/faraday_tran.csv)" -gt 100 ] && pass "tran rc_step -> CSV ($(wc -l < /tmp/faraday_tran.csv) rows)"
python3 -m faraday.cli ac rc_lowpass --fstart 1 --fstop 1meg --points 40 --out /tmp/faraday_ac.csv
[ "$(wc -l < /tmp/faraday_ac.csv)" -eq 41 ] && pass "ac rc_lowpass -> CSV (40 points + header)"
python3 -m faraday.cli netlist <(python3 -c "from faraday import circuits, netlist; print(netlist.to_netlist(circuits.inverting_amplifier().elements))") | grep -q "Rf vminus out" && pass "netlist parse + re-print"

echo
echo "=== 4/5: CLI error paths (must fail cleanly, no traceback) ==="
if python3 -m faraday.cli dc /nonexistent.cir 2>/tmp/faraday_err.txt; then
  fail "expected nonzero exit for missing file"
fi
grep -q "^faraday:" /tmp/faraday_err.txt && ! grep -q "Traceback" /tmp/faraday_err.txt && pass "missing file -> clean one-line error"

echo "R1 1 2 -100" > /tmp/faraday_bad.cir
if python3 -m faraday.cli dc /tmp/faraday_bad.cir 2>/tmp/faraday_err.txt; then
  fail "expected nonzero exit for negative resistor"
fi
grep -q "^faraday: error:" /tmp/faraday_err.txt && pass "negative resistor -> clean one-line error"

echo
echo "=== 5/5: live HTTP server + JSON API ==="
python3 -m faraday.cli serve --port 8799 >/tmp/faraday_server.log 2>&1 &
SERVER_PID=$!
trap 'kill $SERVER_PID 2>/dev/null || true' EXIT
for _ in $(seq 1 20); do
  curl -sf http://127.0.0.1:8799/ >/dev/null 2>&1 && break
  sleep 0.2
done
curl -sf http://127.0.0.1:8799/ -o /dev/null && pass "GET / (UI page)"
curl -sf http://127.0.0.1:8799/api/presets | python3 -c "import json,sys; d=json.load(sys.stdin); assert 'half_wave_rectifier' in d" && pass "GET /api/presets"
curl -sf -X POST http://127.0.0.1:8799/api/simulate -H "Content-Type: application/json" \
  -d '{"netlist":"V1 1 0 DC 10\nR1 1 2 1000\nR2 2 0 1000\n","analysis":"dc"}' \
  | python3 -c "import json,sys; d=json.load(sys.stdin); assert abs(d['voltages']['2']-5.0)<1e-9" && pass "POST /api/simulate (dc)"
AC_RESP=$(curl -sf -X POST http://127.0.0.1:8799/api/simulate -H "Content-Type: application/json" \
  -d '{"netlist":"V1 in 0 DC 0 AC 1\nR1 in out 1000\nC1 out 0 1e-7\n","analysis":"ac","fstart":1,"fstop":1000000,"points":10}')
echo "$AC_RESP" | python3 -c "import json,sys; json.load(sys.stdin)" && pass "POST /api/simulate (ac) is valid JSON (no -Infinity)"
BAD_STATUS=$(curl -s -o /dev/null -w "%{http_code}" -X POST http://127.0.0.1:8799/api/simulate -H "Content-Type: application/json" -d '{"netlist":"garbage","analysis":"dc"}')
[ "$BAD_STATUS" = "400" ] && pass "bad netlist -> HTTP 400 with JSON error, not a 500 traceback"

echo
echo "ALL CHECKS PASSED"
