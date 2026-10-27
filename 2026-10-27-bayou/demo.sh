#!/usr/bin/env bash
# End-to-end demo that exercises every Bayou feature through the CLI and asserts on the output.
# Exits non-zero on the first failed assertion.  usage: ./demo.sh
set -euo pipefail
cd "$(dirname "$0")"
go build -o bin/bayou ./cmd/bayou
B=./bin/bayou
W=$(mktemp -d)
trap 'rm -rf "$W"' EXIT
step=0
say()   { step=$((step+1)); printf '\n\033[1m[%02d] %s\033[0m\n' "$step" "$*"; }
run()   { printf '  $ bayou %s\n' "$*"; "$B" "$@" | sed 's/^/    /'; }
grab()  { "$B" "$@" 2>&1; }
need()  { # need "<haystack>" "<needle>" "<what>"
  if ! grep -qF -- "$2" <<<"$1"; then echo "  ✗ FAILED: expected '$2' in output ($3)"; echo "$1" | head -20; exit 1; fi
  echo "  ✓ $3"; }
fail_expected() { # fail_expected <rc> <needle> -- args...
  local rc=$1 needle=$2; shift 3; local out; set +e; out=$("$B" "$@" 2>&1); local got=$?; set -e
  if [ "$got" != "$rc" ] || ! grep -qF -- "$needle" <<<"$out"; then echo "  ✗ FAILED: bayou $* → rc=$got out=$out (wanted rc=$rc containing '$needle')"; exit 1; fi
  echo "  ✓ rejected with exit $rc: ${out%%$'\n'*}"; }

say "Feature 1 — model language, validation, BIF round trip"
run info examples/asia.bn
out=$(grab check examples/asia.bn);                         need "$out" "ok: Asia" "Asia validates"
$B convert examples/car.bn --to bif -o "$W/car.bif"
a=$($B convert "$W/car.bif" --to bn); b=$($B convert examples/car.bn --to bn)
[ "$a" = "$b" ] && echo "  ✓ .bn → BIF → .bn is lossless"
printf 'network Bad\nvar A { a, b }\ncpt A = 0.5, 0.6\n' > "$W/bad.bn"
fail_expected 1 "sums to" -- check "$W/bad.bn"
printf 'var A {a,b}\nvar B {a,b}\ncpt A | B { a: 1,0\n b: 1,0 }\ncpt B | A { a: 1,0\n b: 1,0 }\n' > "$W/cyc.bn"
fail_expected 1 "cycle" -- check "$W/cyc.bn"

say "Feature 2 — exact inference: posteriors, P(e), MPE, MAP (VE = junction tree = enumeration)"
run query examples/asia.bn -q Tuberculosis,LungCancer -e XRay=abnormal,Smoking=yes
for eng in ve jt enum; do $B query examples/car.bn -q Starts,BatteryDead -e Lights=dim --engine $eng > "$W/q.$eng"; done
cmp "$W/q.ve" "$W/q.jt" && cmp "$W/q.ve" "$W/q.enum" && echo "  ✓ the three engines print identical tables"
out=$(grab query examples/burglar.bn -q Burglary -e Alarm=yes);              need "$out" "0.373" "P(burglary | alarm) = 0.37 (textbook value)"
out=$(grab query examples/burglar.bn -q Burglary -e Alarm=yes,Earthquake=yes); need "$out" "0.003" "an earthquake explains the alarm away: P(burglary) falls to 0.003"
run mpe examples/asia.bn -e Dyspnea=yes,XRay=abnormal
out=$(grab map examples/burglar.bn -q Burglary,Earthquake -e Alarm=yes);     need "$out" "Burglary           = no" "MAP differs from the marginal mode (false alarm)"
fail_expected 1 "probability 0" -- query examples/asia.bn -q Smoking -e Either=no,Tuberculosis=yes

say "Feature 3 — junction tree, all marginals, d-separation"
run tree examples/asia.bn
out=$(grab marginals examples/asia.bn -e Dyspnea=yes);                       need "$out" "posterior marginals given Dyspnea=yes" "every marginal in one calibration"
out=$(grab dsep examples/asia.bn -x Tuberculosis -y LungCancer);             need "$out" "are d-separated" "TB ⫫ cancer a priori"
out=$(grab dsep examples/asia.bn -x Tuberculosis -y LungCancer -z Either);   need "$out" "NOT d-separated" "observing the OR node couples them (collider)"
out=$(grab independencies examples/burglar.bn -z Alarm);                     need "$out" "JohnCalls ⫫ MaryCalls | {Alarm}" "both callers independent given the alarm"
out=$(grab blanket examples/burglar.bn -v Burglary);                         need "$out" "Alarm" "Markov blanket includes the child"

say "Feature 4 — learning: sample → MLE → compare, then EM with missing cells and a latent chain"
$B sample examples/student.bn -n 40000 --seed 11 -o "$W/student.csv"
out=$(grab learn examples/student.bn "$W/student.csv" --alpha 0.5 --truth examples/student.bn -o "$W/student-learned.bn")
echo "$out" | sed 's/^/    /'; need "$out" "KL(truth‖learned)" "reports distance to the truth"
kl=$(sed -n 's/.*= \([0-9.]*\) nats.*/\1/p' <<<"$out"); awk -v k="$kl" 'BEGIN{exit !(k<0.002)}' && echo "  ✓ KL = $kl < 0.002 nats"
$B check "$W/student-learned.bn" >/dev/null && echo "  ✓ learned network is valid"
$B sample examples/weather-hmm.bn -n 3000 --seed 3 --hide W1,W2,W3,W4,W5 --missing 0.05 -o "$W/hmm.csv"
out=$(grab learn examples/weather-hmm.bn "$W/hmm.csv" --em --random --restarts 4 --seed 2 --truth examples/weather-hmm.bn -o "$W/hmm-learned.bn")
echo "$out" | sed 's/^/    /'; need "$out" "EM:" "EM ran on latent + missing data"
fail_expected 1 "--em" -- learn examples/weather-hmm.bn "$W/hmm.csv"

say "Feature 5 — approximate inference (and where exact inference is impossible)"
run approx examples/student.bn -q Intelligence -e Letter=strong --method gibbs -n 20000
out=$(grab approx examples/burglar.bn -q Burglary -e Alarm=yes -n 300000); need "$out" "exact (variable elimination) differs" "LW compared with exact"
$B gen --vars 150 --parents 4 --seed 2 -o "$W/big.bn"
out=$(grab info "$W/big.bn");                                               need "$out" "infeasible" "info warns about the huge treewidth"
fail_expected 1 "treewidth too large" -- marginals "$W/big.bn"
out=$(grab approx "$W/big.bn" -q X149 -e X0=s0 --method gibbs -n 3000);     need "$out" "Gibbs sampling" "…but Gibbs still answers"

say "Feature 6 — structure learning recovers the car-diagnosis graph from data"
$B sample examples/car.bn -n 40000 --seed 21 -o "$W/car.csv"
out=$(grab structure examples/car.bn "$W/car.csv" --score bic --truth examples/car.bn -o "$W/car-learned.bn")
echo "$out" | sed 's/^/    /'; need "$out" "SHD 0" "learned the exact Markov equivalence class"

say "Feature 7 — interactive HTML report (checked in headless Chromium)"
$B report examples/asia.bn -o "$W/asia.html"
$B marginals examples/asia.bn -e Smoking=yes,XRay=abnormal --json | python3 -c "
import json,sys
d=json.load(sys.stdin)['marginals']
json.dump({k:d[k] for k in ['LungCancer','Tuberculosis','Dyspnea']},open('$W/expected.json','w'))"
if command -v node >/dev/null && node -e "require('playwright')" 2>/dev/null; then
  node tests/browser_check.js "$W/asia.html" "$W/expected.json" | sed 's/^/    /'
else echo "  (skipped: node + playwright not available)"; fi

say "Feature 8 — value of information"
out=$(grab voi examples/car.bn -q BatteryDead -e Starts=no --top 3); echo "$out" | sed 's/^/    /'
need "$out" "gain(bits)" "ranked next observations"
out=$(grab voi examples/car.bn -q BatteryDead,FuelEmpty -e Starts=no --cost Radio=0.1,Lights=0.1,FuelGauge=0.1 --top 2)
need "$out" "gain/cost" "cost-aware ranking"

printf '\n\033[1;32mdemo OK — all %d steps passed\033[0m\n' "$step"
