#!/usr/bin/env bash
# Runs every check for Cubist. Exit 0 and "ALL GREEN" only if everything passes.
set -uo pipefail
cd "$(dirname "$0")"
TMP=$(mktemp -d); trap 'kill $SRV 2>/dev/null; rm -rf "$TMP"' EXIT
n=0; fail=0
check() { n=$((n+1)); if eval "$2" >"$TMP/out" 2>&1; then echo "ok   $1"; else echo "FAIL $1"; sed 's/^/     | /' "$TMP/out" | head -15; fail=$((fail+1)); fi; }
has() { grep -q -- "$1" "$TMP/out"; }   # assertion on last command output (used inside eval'd checks via cat)

check "gofmt clean"            '[ -z "$(gofmt -l .)" ]'
check "go vet"                 'go vet ./...'
check "unit tests (race)"      'go test -race -count=1 ./...'
check "build"                  'go build -o "$TMP/cubist" .'
C="$TMP/cubist"

# F1 notation / simplify / invert
check "simplify R L R' U U' D' D -> L"   '[ "$($C simplify "R L R'"'"' U U'"'"' D'"'"' D")" = "L" ]'
check "invert R U R' U'"                  '[ "$($C invert "R U R'"'"' U'"'"'")" = "U R U'"'"' R'"'"'" ]'
check "bad notation is rejected"          'OUT=$($C simplify "R U x" 2>&1); RC=$?; [ $RC -ne 0 ] && echo "$OUT" | grep -q "unsupported move"'

# F2 facelets
S=UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB
check "verify solved facelets"            '$C verify $S | grep -q "^VALID"'
check "verify catches bad census"         '! $C verify UUUUUUUUURRRRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBR'
check "verify catches twisted corner"     'OUT=$($C verify UUUUUUUURFRRRRRRRRFFUFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB); echo "$OUT" | grep -q twisted'
check "verify catches flipped edge"       'OUT=$($C verify UUUUURUUURURRRRRRRFFFFFFFFFDDDDDDDDDLLLLLLLLLBBBBBBBBB); echo "$OUT" | grep -q flipped'
check "show prints a net"                 '[ "$($C show --scramble "R" | wc -l)" = 9 ]'
check "54-letter positional = facelets"   '$C solve $S | grep -q "already solved"'
check "empty scramble = solved"           '$C solve --scramble "" | grep -q "already solved"'

# F3 solver
SC="R U R' U' F2 D L' B2 U2 R"
check "solve known scramble, verified"    '$C solve "$SC" | grep -q "solved ✔"'
check "solve --json is valid JSON w/ solved final" 'python3 -c "import json,sys; d=json.loads(sys.argv[1]); assert d[\"final\"]==\"$S\" and len(d[\"moves\"])>0" "$($C solve --json "$SC")"'
check "solver beats naive: superflip <= 22" 'N=$($C solve --json --time 1s --scramble "U R2 F B R B2 R U2 L B2 R U'"'"' D'"'"' R2 F R'"'"' L B2 U2 F2" | python3 -c "import json,sys; print(len(json.load(sys.stdin)[\"moves\"]))"); echo moves=$N; [ "$N" -le 22 ]'
check "reversible scramble uses inverse"  '$C solve --json "R U R'"'"' U'"'"'" | grep -q inverse-of-scramble'
check "facelet input solves (round trip via JSON start state)" 'ST=$($C solve --json --scramble "R U F2 D'"'"' B L2 U R2" | python3 -c "import json,sys; print(json.load(sys.stdin)[\"start\"])"); echo start=$ST; $C solve --facelets "$ST" | grep -q "solved ✔"'
check "infeasible --max gives up w/ error" '! timeout 60 $C solve --max 12 --scramble "D B2 D'"'"' B2 L2 D2 B2 U'"'"' L2 B2 U R2 U B F U'"'"' R'"'"' F U2 F'"'"' D U2" 2>&1'
check "negative --time rejected"          '! $C solve --time -1s "R" 2>&1'

# F4 player (static render + headless browser)
check "render writes standalone HTML"     '$C render -o "$TMP/p.html" --scramble "R U R'"'"' U'"'"' F2 D L'"'"' B2 U2 R" && grep -q "const DATA = {" "$TMP/p.html" && ! grep -q "http" <(grep -o "src=[^ >]*" "$TMP/p.html")'
if command -v node >/dev/null && node -e "require('playwright')" 2>/dev/null; then
  ( "$C" serve --addr 127.0.0.1:18099 >/dev/null 2>&1 & echo $! > "$TMP/pid" ); SRV=$(cat "$TMP/pid"); sleep 1.5
  check "headless browser: player + serve UI" 'node tools/browser_check.js "$TMP/p.html" http://127.0.0.1:18099/'
  kill $SRV 2>/dev/null
else echo "skip headless browser checks (node/playwright not available)"; fi

# F5 analyzer
check "order(R U R' U') = 6"              '$C analyze "R U R'"'"' U'"'"'" | grep -q "^order          6 "'
check "order(R U) = 105"                  '$C analyze "R U" | grep -q "^order          105 "'
check "order(R U2 D' B D') = 1260"        '$C analyze "R U2 D'"'"' B D'"'"'" | grep -q "^order          1260 "'

# F6 random + bench
check "scramble --state is deterministic per seed" '[ "$($C scramble --seed 5)" = "$($C scramble --seed 5)" ] && [ -n "$($C scramble --seed 5)" ]'
check "scramble --moves 25 has 25 moves"  '[ "$($C scramble --moves 25 --seed 1 | wc -w)" = 25 ]'
check "state scramble solves back (round trip)" 'SCR=$($C scramble --seed 8); $C solve "$SCR" | grep -q "solved ✔"'
check "bench 60 states, mean <= 21.5"     '$C bench -n 60 --time 100ms | tee "$TMP/bench"; awk "/^mean/ {exit !(\$2 <= 21.5)}" "$TMP/bench"'

# F7 serve API
( "$C" serve --addr 127.0.0.1:18098 >/dev/null 2>&1 & echo $! > "$TMP/pid2" ); SRV=$(cat "$TMP/pid2"); sleep 1.5
check "API solves scramble"               'curl -s -m 20 -XPOST 127.0.0.1:18098/api/solve -d "{\"scramble\":\"R U F\"}" | grep -q "\"final\":\"$S\""'
check "API 422 on bad input"              '[ "$(curl -s -m 20 -o /dev/null -w %{http_code} -XPOST 127.0.0.1:18098/api/solve -d "{\"scramble\":\"Q\"}")" = 422 ]'
check "API 405 on GET"                    '[ "$(curl -s -m 20 -o /dev/null -w %{http_code} 127.0.0.1:18098/api/solve)" = 405 ]'
kill $SRV 2>/dev/null

echo
if [ $fail -eq 0 ]; then echo "ALL GREEN ($n checks)"; else echo "$fail of $n checks FAILED"; exit 1; fi
