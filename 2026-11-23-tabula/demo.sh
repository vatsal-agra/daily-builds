#!/usr/bin/env bash
# End-to-end demo / acceptance script: exercises every Tabula feature through the CLI
# and asserts on the results. Exit status 0 = everything green.
set -u
cd "$(dirname "$0")"
OUT=$(mktemp -d)
trap 'rm -rf "$OUT"' EXIT
go build -o "$OUT/tabula" ./cmd/tabula || exit 1
T="$OUT/tabula"
pass=0; fail=0
ok()   { pass=$((pass+1)); printf '  \033[32mok\033[0m   %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; }
check(){ if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1  [$2]"; fi; }

echo "[1] model + validation"
echo '{"name":"x","days":2,"periods":2,"teachers":[{"id":"t","unavailable":[[0,1,5]]}],"rooms":[],"groups":[],"lessons":[]}' > "$OUT/bad.json"
check "malformed slot is rejected with a clear error"   "$T check $OUT/bad.json 2>&1 | grep -q 'slot must be'; [ \${PIPESTATUS[0]} -ne 0 ]"
echo '{"nme":1}' > "$OUT/unk.json"
check "unknown JSON field is rejected"                   "! $T check $OUT/unk.json"
check "missing file gives non-zero exit"                 "! $T check $OUT/nope.json"
check "valid hand-written example passes check"          "$T check examples/school.json"

echo "[4] impossibility diagnostics"
check "impossible example exits non-zero"                "! $T check examples/impossible.json"
for m in 'seating 25' 'only 2 usable day' 'both claim teacher fox' 'seating 90'; do
  check "diagnoses: $m"                                  "$T check examples/impossible.json | grep -q '$m'"
done
check "solve refuses impossible problem"                 "$T solve examples/impossible.json 2>&1 | grep -q 'no timetable can exist'"

echo "[2,3] construct + anneal (hand-written school)"
check "solve school.json -> solution + html + ics"       "$T solve examples/school.json -o $OUT/s.json -html $OUT/s.html -ics $OUT/ics -iters 2000000 -q"
check "solution passes the independent verifier"         "$T verify examples/school.json $OUT/s.json | grep -q '^VALID'"
check "pinned assembly landed on Monday period 1"        "python3 -c \"import json,sys;p=[x for x in json.load(open('$OUT/s.json'))['placements'] if x['lesson']=='assembly'][0];sys.exit(0 if (p['day'],p['period'])==(0,0) else 1)\""
check "annealing beat the constructor's cost"            "$T solve examples/school.json -iters 2000000 | awk '/cost/{for(i=1;i<=NF;i++)if(\$i==\"cost\"){a=\$(i+1);b=\$(i+3)}} END{exit !(b<a)}'"
check "same seed + -iters is byte-identical"             "$T solve examples/school.json -iters 300000 -q -o $OUT/a.json && $T solve examples/school.json -iters 300000 -q -o $OUT/b.json && cmp $OUT/a.json $OUT/b.json"

echo "[5] HTML viewer"
check "viewer is one self-contained file"                "[ -s $OUT/s.html ] && ! grep -q 'https\\?://' $OUT/s.html"
check "viewer embeds the solution"                       "grep -q 'Oakfield' $OUT/s.html"

echo "[6] verifier catches tampering"
python3 - "$OUT/s.json" "$OUT/tampered.json" <<'PY'
import json,sys
s=json.load(open(sys.argv[1]))
a,b=s['placements'][0],s['placements'][1]
b['day'],b['period'],b['room']=a['day'],a['period'],a['room']   # force a room clash
json.dump(s,open(sys.argv[2],'w'))
PY
check "tampered solution is INVALID"                     "$T verify examples/school.json $OUT/tampered.json | grep -q '^INVALID'"

echo "[7] generator + tight instances"
check "gen is deterministic"                             "$T gen -seed 4 -o $OUT/g1.json >/dev/null && $T gen -seed 4 -o $OUT/g2.json >/dev/null && cmp $OUT/g1.json $OUT/g2.json"
check "gen rejects nonsense"                             "! $T gen -load 3 -o $OUT/z.json"
$T gen -seed 9 -groups 10 -teachers 10 -rooms 6 -load 0.9 -o "$OUT/tight.json" >/dev/null
check "tight feasible instance (load .9) is solved"      "$T solve $OUT/tight.json -iters 100000 -q -o $OUT/tight.sol.json && $T verify $OUT/tight.json $OUT/tight.sol.json | grep -q '^VALID'"
$T gen -seed 21 -groups 12 -teachers 14 -rooms 9 -load 0.7 -o "$OUT/big.json" >/dev/null
check "larger instance solves and verifies"              "$T solve $OUT/big.json -iters 500000 -q -o $OUT/big.sol.json && $T verify $OUT/big.json $OUT/big.sol.json | grep -q '^VALID'"

echo "[8] minimal-disruption re-solve"
python3 - "$OUT/s.json" "$OUT/school2.json" <<'PY'
import json,sys
sol=json.load(open(sys.argv[1])); p=json.load(open('examples/school.json'))
L={l['id']:l for l in p['lessons']}
d=[x for x in sol['placements'] if L[x['lesson']]['teacher']=='diaz'][:2]
for t in p['teachers']:
    if t['id']=='diaz': t['unavailable']=t.get('unavailable',[])+[[x['day'],x['period']] for x in d]
json.dump(p,open(sys.argv[2],'w'))
PY
$T resolve "$OUT/school2.json" "$OUT/s.json" -iters 500000 -o "$OUT/r.json" > "$OUT/r.txt"
$T solve "$OUT/school2.json" -iters 500000 -o "$OUT/f.json" -q
cat > "$OUT/moved.py" <<'PY'
import json,sys
k=lambda f:{(x['lesson'],x['session']):(x['day'],x['period']) for x in json.load(open(f))['placements']}
a,b=k(sys.argv[1]),k(sys.argv[2]); print(sum(1 for i in a if a[i]!=b[i]))
PY
R=$(python3 "$OUT/moved.py" "$OUT/s.json" "$OUT/r.json"); F=$(python3 "$OUT/moved.py" "$OUT/s.json" "$OUT/f.json")
echo "      re-solve moved $R sessions, fresh solve moved $F"
check "re-solve moves a small fraction of a fresh solve" "[ $R -ge 2 ] && [ $((R*2)) -lt $F ]"
check "re-solve result verifies against new problem"     "$T verify $OUT/school2.json $OUT/r.json | grep -q '^VALID'"

echo "[9] iCalendar"
check "one calendar per group + teacher"      "[ \$(ls $OUT/ics | wc -l) -eq 8 ]"
check "calendar is RFC-shaped (CRLF, VEVENT, RRULE)"     "grep -q RRULE:FREQ=WEEKLY $OUT/ics/group-Y4.ics && head -c 15 $OUT/ics/group-Y4.ics | grep -q BEGIN:VCALENDAR"
check "no ICS line exceeds 75 octets"                    "! awk '{sub(/\\r\$/,\"\")} length(\$0)>75{f=1} END{exit !f}' $OUT/ics/*.ics"
check "non-Monday -start is rejected"                    "! $T solve examples/school.json -iters 10 -q -ics $OUT/ics2 -start 2026-09-08"

echo "[show] text rendering"
check "show prints every group"                          "$T show examples/school.json $OUT/s.json | grep -c '== group' | grep -q 3"

echo "[cli] misc"
check "unknown command exits 2"                          "$T bogus >/dev/null 2>&1; [ \$? -eq 2 ]"
check "empty problem solves"                             "echo '{\"name\":\"e\",\"days\":5,\"periods\":6,\"teachers\":[],\"rooms\":[],\"groups\":[],\"lessons\":[]}' > $OUT/e.json && $T solve $OUT/e.json -q"

echo
echo "go unit tests:"; go test ./tabula 2>&1 | tail -3
[ ${PIPESTATUS[0]} -eq 0 ] && ok "go test ./tabula" || bad "go test ./tabula"
echo
echo "demo: $pass passed, $fail failed"
[ $fail -eq 0 ]
