#!/usr/bin/env bash
# Full verification: formatting, vet, unit + CLI tests, scripted end-to-end demo with assertions,
# headless-browser check of the generated report. Ends with ALL GREEN or exits non-zero.
set -euo pipefail
cd "$(dirname "$0")"
TMP=$(mktemp -d); trap 'rm -rf "$TMP"' EXIT
pass=0
ok()   { pass=$((pass+1)); printf '  ok   %s\n' "$1"; }
die()  { printf '  FAIL %s\n' "$1"; exit 1; }
has()  { grep -qE -- "$2" <<<"$1" || die "$3 (expected /$2/ in output)"; ok "$3"; }

echo "== static"
[ -z "$(gofmt -l .)" ] || die "gofmt"; ok "gofmt clean"
go vet ./... ; ok "go vet"
echo "== go tests"
go test -count=1 ./... | sed 's/^/  /'; ok "go test ./..."
go test -count=1 -race ./orrery -run 'TestBarnesHut|TestTwoBody|TestKepler' >/dev/null; ok "race detector on core tests"
go build -o "$TMP/orrery" ./cmd/orrery; O="$TMP/orrery"; ok "build"

echo "== feature 1: integrators + diagnostics"
out=$($O bench twobody -dt 0.01 -T 100)
has "$out" 'yoshida4 +yes' "bench lists symplectic yoshida4"
e_lf=$(awk '$1=="leapfrog"{print $3}' <<<"$out"); e_eu=$(awk '$1=="euler"{print $3}' <<<"$out")
python3 - "$e_lf" "$e_eu" <<'PY' || die "leapfrog should beat euler by >100x"
import sys; a,b=map(float,sys.argv[1:]); sys.exit(0 if b>100*a else 1)
PY
ok "leapfrog energy error << euler ($e_lf vs $e_eu)"
out=$($O run figure8 -m yoshida4 -dt 0.002 -T 6.32591398)
has "$out" 'force-evals=' "run prints diagnostics"
last=$(awk '/^ +6\.3259/{print $2}' <<<"$out" | tail -1)
python3 - "$last" <<'PY' || die "figure-eight energy not conserved"
import sys; sys.exit(0 if abs(float(sys.argv[1]))<1e-9 else 1)
PY
ok "figure-eight closes with |dE/E0| < 1e-9 ($last)"
out=$($O run pythagorean -dt 0.01 -T 70); has "$out" 'WARNING' "fixed-step chaos run warns loudly"
out=$($O run pythagorean -m dopri5 -dt 0.1 -T 70); ! grep -q WARNING <<<"$out" || die "dopri5 should be clean"; ok "dopri5 survives close encounters cleanly"
out=$($O run solar -m wh -dt 0.05 -T 100); has "$out" 'force-evals' "Wisdom–Holman runs the solar system"

echo "== feature 2: Barnes–Hut"
out=$($O bh plummer -n 1500)
th01=$(awk '$1=="0.10"{print $2}' <<<"$out"); th10=$(awk '$1=="1.00"{print $2}' <<<"$out")
python3 - "$th01" "$th10" <<'PY' || die "BH error must shrink with theta"
import sys; a,b=map(float,sys.argv[1:]); sys.exit(0 if a<b/100 and a<1e-3 else 1)
PY
ok "BH rms error theta=0.1 ($th01) << theta=1.0 ($th10)"
out=$($O bh disc -n 20000); sp=$(awk '$1=="1.00"{gsub("x","",$6); print $6}' <<<"$out")
python3 - "$sp" <<'PY' || die "tree should be >3x faster than direct at N=20000, theta=1"
import sys; sys.exit(0 if float(sys.argv[1])>3 else 1)
PY
ok "tree is ${sp}x faster than direct at N=20000, theta=1"

echo "== feature 3: scenarios, Kepler oracle, elements"
$O gen figure8 > "$TMP/f8.sc"; out=$($O run "$TMP/f8.sc" -m rk4 -dt 0.01 -T 1); has "$out" 'steps=100' "scenario file generated and re-run"
cat > "$TMP/sys.sc" <<'SC'
title Demo
G 1
body Sun m=1
body P m=1e-3 orbit=Sun a=2 e=0.25 i=10 raan=20 argp=30 ma=40
SC
out=$($O elements "$TMP/sys.sc"); has "$out" 'P +2 +0\.25000 +10\.000 +20\.000 +30\.000' "orbit directive -> state -> elements round trip"
out=$($O elements solar); has "$out" 'Neptune +30\.07' "solar elements"
out=$($O run "$TMP/nope.sc" 2>&1 || true); has "$out" 'cannot read' "missing file reported"
printf 'G 1\nbody A m=1\nbody B m=oops\n' > "$TMP/bad.sc"; out=$($O run "$TMP/bad.sc" 2>&1 || true); has "$out" 'line 3' "parse error carries line number"

echo "== feature 4: HTML report"
$O report solar -m leapfrog -dt 0.01 -T 30 -o "$TMP/solar.html" >/dev/null; [ -s "$TMP/solar.html" ] || die "report empty"; ok "solar report written"
$O report figure8 -m yoshida4 -dt 0.005 -T 12.6 -o "$TMP/f8.html" >/dev/null; ok "figure8 report written"
$O report plummer -n 80 -dt 0.02 -T 3 -m leapfrog -o "$TMP/pl.html" >/dev/null; ok "plummer report written"
if command -v node >/dev/null && node -e "require('playwright')" 2>/dev/null; then
  for f in solar f8 pl; do node tests/browser_check.js "$TMP/$f.html" | grep -q 'browser check ok' || die "browser check $f"; ok "headless browser check: $f"; done
else echo "  skip headless browser check (node/playwright unavailable)"; fi

echo "== stretch"
out=$($O order); has "$out" 'yoshida4 +4 +(3\.9|4\.0)' "observed order of yoshida4 ~ 4"; has "$out" 'leapfrog +2 +2\.0' "observed order of leapfrog = 2"; has "$out" 'wh +2 +2\.0' "observed order of Wisdom-Holman = 2"
out=$($O reverse figure8 -dt 0.01 -T 3); has "$out" 'leapfrog .*reversible \(round-off only\)' "leapfrog is time-reversible"; has "$out" 'symeuler .*irreversible' "symplectic Euler is not"
out=$($O lyap plummer -n 16 -dt 0.005 -T 40 -m yoshida4 -samples 2); has "$out" 'CHAOTIC' "16-body Plummer is chaotic"
out=$($O lyap twobody -dt 0.01 -T 800 -m yoshida4 -samples 2); has "$out" 'REGULAR' "Kepler orbit is regular"
out=$($O lyap pythagorean -dt 0.0005 -T 30 -m yoshida4 -samples 2); has "$out" 'TRANSIENT' "Pythagorean problem shows transient chaos"

echo
echo "ALL GREEN ($pass checks)"
