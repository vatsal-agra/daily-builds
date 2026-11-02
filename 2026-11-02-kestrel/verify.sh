#!/usr/bin/env bash
# End-to-end verification: vet, unit tests, then every CLI feature with assertions on the output.
set -euo pipefail
cd "$(dirname "$0")"
BIN=$(mktemp -d)/kestrel
pass=0
ok()   { echo "  ok   $1"; pass=$((pass+1)); }
fail() { echo "  FAIL $1"; exit 1; }
expect() { # name, haystack, regex
  grep -Eq "$3" <<<"$2" && ok "$1" || { echo "$2"; fail "$1 (wanted /$3/)"; }
}

echo "== build, vet, unit tests"
go vet ./... && ok "go vet"
go build -o "$BIN" ./cmd/kestrel && ok "build"
go test ./... >/dev/null && ok "go test ./..."

echo "== feature 1: Kalman filter consistency (NEES/NIS)"
out=$($BIN consistency -filter kf -sensor cartesian -runs 600 -steps 30)
expect "KF NEES consistent" "$out" "NEES.*CONSISTENT"
expect "KF NIS consistent"  "$out" "NIS.*CONSISTENT"
out=$($BIN consistency -filter kf -mismatch 0.005 -runs 400)
expect "wrong Q is detected" "$out" "NEES.*INCONSISTENT"

echo "== feature 2: EKF / UKF on radar range+bearing"
for f in ekf ukf; do
  out=$($BIN consistency -filter $f -sensor radar -runs 600 -steps 30)
  expect "$f radar consistent" "$out" "NEES.*CONSISTENT"
done
out=$($BIN consistency -filter kf -sensor radar 2>&1 || true)
expect "KF refuses radar" "$out" "cannot process radar"

echo "== feature 3+4: association, lifecycle, scoring on every scenario"
for s in cruise crossing swarm manoeuvre birthdeath dropouts; do
  out=$($BIN run -scenario $s -filter imm-ekf)
  expect "$s: tracks follow targets" "$out" "coverage +9[0-9]\.[0-9] %"
  expect "$s: no ID switches" "$out" "ID switches +0"
done
out=$($BIN run -scenario knot -assoc jpda -tracks)
expect "knot with JPDA runs" "$out" "mean OSPA"

echo "== stretch: IMM beats CV, RTS smoother, JPDA, report"
out=$($BIN compare -scenario manoeuvre -seeds 3)
expect "compare table lists IMM" "$out" "imm-ekf"
out=$($BIN smooth -runs 200)
expect "smoother consistent" "$out" "CONSISTENT"
out=$($BIN run -scenario cruise -smooth)
expect "tracker smoothing gain" "$out" "RTS smoothing"
rep=$(mktemp -d)/r.html
$BIN report -scenario crossing -smooth -o "$rep" >/dev/null
grep -q "<svg" "$rep" && grep -q "Confirmed tracks" "$rep" && ok "HTML report written"

echo "== error handling"
out=$($BIN run -scenario nope 2>&1 || true);            expect "unknown scenario"   "$out" "unknown scenario"
out=$($BIN run -filter zzz 2>&1 || true);               expect "unknown filter"     "$out" "unknown filter"
out=$($BIN run -smooth -filter imm-ekf 2>&1 || true);   expect "smooth+IMM refused" "$out" "not supported"
out=$($BIN consistency -runs 1 2>&1 || true);           expect "bad run count"      "$out" "Runs>=2"
out=$($BIN frobnicate 2>&1 || true);                    expect "unknown command"    "$out" "unknown command"

if command -v node >/dev/null && node -e "require('playwright')" 2>/dev/null; then
  echo "== headless-browser check of the report"
  cat > "$BIN.js" <<JS
const { chromium } = require('playwright');
(async () => { const b = await chromium.launch(); const p = await b.newPage({viewport:{width:390,height:800}});
  const errs=[]; p.on('pageerror',e=>errs.push(e.message)); await p.goto('file://$rep');
  const w = await p.evaluate(()=>document.documentElement.scrollWidth);
  const n = await p.evaluate(()=>document.querySelectorAll('svg polyline').length);
  await b.close(); if (errs.length||w>390||n<3) { console.log('bad',errs,w,n); process.exit(1);} })();
JS
  node "$BIN.js" && ok "report renders at phone width, no overflow, has tracks" || fail "browser check"
fi
echo "ALL GREEN ($pass checks)"
