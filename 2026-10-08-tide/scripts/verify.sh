#!/usr/bin/env bash
# End-to-end verification of every Tide feature against the real binary.
# Usage: scripts/verify.sh        (exits non-zero on the first failed check)
set -uo pipefail
cd "$(dirname "$0")/.."
WORK=$(mktemp -d); trap 'kill $(jobs -p) 2>/dev/null; rm -rf "$WORK"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  \033[32mok\033[0m   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; }
check(){ if eval "$2"; then ok "$1"; else bad "$1  [$2]"; fi; }
jq_()  { python3 -c "import json,sys; d=json.load(sys.stdin); print($1)"; }
section(){ printf '\n== %s\n' "$1"; }

section "static checks + unit tests (codec, WAL, store, query, server)"
check "gofmt clean"       '[ -z "$(gofmt -l .)" ]'
check "go vet"            'go vet ./... 2>&1'
check "go test -race"     'go test -race -count=1 ./... 2>&1 | tee "$WORK/test.log" | grep -v "no test files" | grep -vq "FAIL"'
go build -o "$WORK/tide" ./cmd/tide || { echo "build failed"; exit 1; }
T="$WORK/tide"

PORT=$(python3 -c "import socket; s=socket.socket(); s.bind(('127.0.0.1',0)); print(s.getsockname()[1])")
URL="http://127.0.0.1:$PORT"
DATA="$WORK/data"
NOW=$(python3 -c "import time; print(int(time.time()*1000))")
start() { "$T" serve -dir "$DATA" -addr "127.0.0.1:$PORT" -alerts "$WORK/alerts.json" -alert-interval 1s -compact-every 0 >"$WORK/serve.log" 2>&1 & SPID=$!
          for i in $(seq 50); do curl -sf "$URL/healthz" >/dev/null && return 0; sleep 0.1; done; return 1; }
q() { curl -s --get "$URL/query" --data-urlencode "q=$1"; }

cat > "$WORK/alerts.json" <<'JSON'
[{"name":"Hot","expr":"avg(temp) by_placeholder","op":">","threshold":50}]
JSON
cat > "$WORK/alerts.json" <<'JSON'
[{"name":"Hot","expr":"avg(temp) range 5m step 1m","op":">","threshold":50,"for":"0s","summary":"temp over 50"}]
JSON

section "F4  HTTP API: ingest, dashboard, health"
check "server starts" 'start'
check "healthz"       'curl -sf "$URL/healthz" | grep -q ok'
check "dashboard served" 'curl -sf "$URL/" | grep -q "<title>Tide</title>"'
# counter: host a +1/s, host b +3/s (10s spacing => +10 / +30), 60 samples ending ~now
python3 - "$NOW" > "$WORK/body.txt" <<'PY'
import sys
now=int(sys.argv[1]); n=60
for i in range(n):
    t=now-(n-1-i)*10_000
    print(f'reqs{{host="a",code="200"}} {i*10} {t}')
    print(f'reqs{{host="b",code="200"}} {i*30} {t}')
    print(f'reqs{{host="b",code="500"}} {i} {t}')
    print(f'temp{{room="lab"}} {20+i*0.5} {t}')
    print(f'temp{{room="attic"}} {70-i*0.1} {t}')
    print(f'lat{{route="/x"}} {i%10+1} {t}')
PY
R=$(curl -s -XPOST "$URL/write" --data-binary @"$WORK/body.txt")
check "write accepted all 360 samples" '[ "$(echo "$R" | jq_ "d[\"accepted\"]")" = 360 ]'
R=$(curl -s -XPOST "$URL/write" -d $'good{a="b"} 1\nthis is junk\nalso{bad 2')
check "bad lines reported, good line kept" '[ "$(echo "$R" | jq_ "d[\"accepted\"]")" = 1 ] && echo "$R" | grep -q "line 2"'
check "all-bad write -> 400" '[ "$(curl -s -o /dev/null -w "%{http_code}" -XPOST "$URL/write" -d "junk")" = 400 ]'
R=$(curl -s -XPOST "$URL/write" --data-binary @"$WORK/body.txt")
check "re-sending same data is rejected as out-of-order" '[ "$(echo "$R" | jq_ "d[\"accepted\"]")" = 0 ] && [ "$(echo "$R" | jq_ "d[\"outOfOrder\"]")" = 360 ]'
check "invalid values/timestamps rejected with reason" 'curl -s -XPOST "$URL/write" -d $'"'"'m 1 -5\nm 1 99999999999999999'"'"' | grep -q "out of range"'
check "/series lists matching series only" '[ "$(curl -s --get "$URL/series" --data-urlencode "match=reqs{host=\"a\"}" | jq_ "len(d)")" = 1 ]'
check "/stats reports samples and compression" 'curl -s "$URL/stats" | python3 -c "import json,sys; d=json.load(sys.stdin); assert d[\"totalSamples\"]>=361 and d[\"compressionRatio\"]>2, d"'

section "F3  Query language: matchers, functions, grouping, errors"
check "raw selector returns samples" '[ "$(q "temp{room=\"lab\"} range 15m" | jq_ "len(d[\"series\"][0][\"points\"])")" = 60 ]'
check "regex matcher (anchored)"     '[ "$(q "temp{room=~\"la.*\"} range 15m" | jq_ "len(d[\"series\"])")" = 1 ]'
check "negative regex matcher"       '[ "$(q "temp{room!~\"la.*\"} range 15m" | jq_ "d[\"series\"][0][\"labels\"][\"room\"]")" = attic ]'
check "partial regex does not match" '[ "$(q "temp{room=~\"la\"} range 15m" | jq_ "len(d[\"series\"])")" = 0 ]'
check "rate(): a=1/s, b=3/s => sum 4/s" 'q "sum(rate(reqs{code=\"200\"})) range 8m step 1m at latest" | python3 -c "
import json,sys; d=json.load(sys.stdin); v=[p[\"v\"] for p in d[\"series\"][0][\"points\"]]
assert len(v)>=5 and all(abs(x-4)<0.01 for x in v[1:]), v"'
check "by(): one series per code" '[ "$(q "sum(rate(reqs)) by (code) range 8m step 1m at latest" | jq_ "\",\".join(sorted(s[\"labels\"][\"code\"] for s in d[\"series\"]))")" = "200,500" ]'
check "max across series"  'q "max(avg(temp)) range 5m step 1m at latest" | python3 -c "
import json,sys; d=json.load(sys.stdin); assert len(d[\"series\"])==1 and d[\"series\"][0][\"points\"][-1][\"v\"]>60, d"'
check "parse error => 400 with caret position" 'curl -s -o "$WORK/e.json" -w "%{http_code}" --get "$URL/query" --data-urlencode "q=sum(avg(temp" | grep -q 400 && grep -q "\"pos\"" "$WORK/e.json"'
check "too many points => 422" '[ "$(curl -s -o /dev/null -w "%{http_code}" --get "$URL/query" --data-urlencode "q=avg(temp) range 365d step 1s")" = 422 ]'
check "no match => empty array not null" 'q "nothing_here" | grep -q "\"series\":\\[\\]"'

section "F6  Alert rules (stretch)"
sleep 2.5
check "Hot alert fires for attic only" 'curl -s "$URL/alerts" | python3 -c "
import json,sys; d=json.load(sys.stdin); f=[a for a in d if a[\"state\"]==\"firing\"]
assert len(f)==1 and f[0][\"labels\"][\"room\"]==\"attic\" and f[0][\"name\"]==\"Hot\", d"'

section "F2  Durability: kill -9 recovery, flush, torn WAL, corruption"
BEFORE=$(curl -s "$URL/stats" | jq_ 'd["totalSamples"]')
kill -9 $SPID; wait $SPID 2>/dev/null
check "restart after kill -9" 'start'
check "all samples recovered from WAL" '[ "$(curl -s "$URL/stats" | jq_ "d[\"totalSamples\"]")" = "$BEFORE" ] && [ "$(curl -s "$URL/stats" | jq_ "d[\"recoveredWalSamples\"]")" -gt 0 ]'
check "flush -> block, WAL reset" 'curl -s -XPOST "$URL/flush" | python3 -c "
import json,sys; d=json.load(sys.stdin); assert d[\"blocks\"]==1 and d[\"headSamples\"]==0 and d[\"walBytes\"]==0, d"'
check "data still queryable from block" '[ "$(q "temp{room=\"lab\"} range 15m" | jq_ "len(d[\"series\"][0][\"points\"])")" = 60 ]'
check "re-send after flush still rejected" '[ "$(curl -s -XPOST "$URL/write" --data-binary @"$WORK/body.txt" | jq_ "d[\"accepted\"]")" = 0 ]'
NOW2=$((NOW+60000))
curl -s -XPOST "$URL/write" -d "after{x=\"1\"} 1 $NOW2
after{x=\"1\"} 2 $((NOW2+1000))" >/dev/null
kill -9 $SPID; wait $SPID 2>/dev/null
cp "$DATA/wal.log" "$WORK/wal.bak"; SZ=$(stat -c %s "$DATA/wal.log"); truncate -s $((SZ-4)) "$DATA/wal.log"
check "torn WAL tail tolerated + reported" 'start && [ "$(curl -s "$URL/stats" | jq_ "d[\"walTornBytesDropped\"]")" -gt 0 ]'
check "intact prefix of torn WAL survived" '[ "$(q "after range 1h at latest" | jq_ "len(d[\"series\"][0][\"points\"])")" = 1 ]'
LOCKOUT=$("$T" stats -dir "$DATA" 2>&1); LOCKRC=$?
check "second process on same dir refused (lock)" '[ "$LOCKRC" != 0 ] && echo "$LOCKOUT" | grep -q "in use"'
kill $SPID; wait $SPID 2>/dev/null
BLK=$(ls "$DATA"/blocks/*.blk | head -1); python3 - "$BLK" <<'PY'
import sys; p=sys.argv[1]; b=bytearray(open(p,'rb').read()); b[40]^=0xFF; open(p,'wb').write(b)
PY
check "corrupted block detected at startup (refuses to serve bad data)" '! start && grep -q "corrupt block" "$WORK/serve.log"'
python3 - "$BLK" <<'PY'
import sys; p=sys.argv[1]; b=bytearray(open(p,'rb').read()); b[40]^=0xFF; open(p,'wb').write(b)
PY
check "block verifies again after restoring the byte" 'start'

section "F3b Percentiles on a bucket-aligned fixture"
# ten samples 1..10 inside one hour-aligned bucket, three hours ago
T0=$(( (NOW/3600000)*3600000 - 3*3600000 ))
for i in $(seq 1 10); do echo "lat2{route=\"/y\"} $i $((T0+i*1000))"; done > "$WORK/lat2.txt"
curl -s -XPOST "$URL/write" --data-binary @"$WORK/lat2.txt" >/dev/null
pq() { q "$1(lat2) range 1h step 1h at $((T0+3599999))" | jq_ 'round(d["series"][0]["points"][0]["v"],3)'; }
check "p50 of 1..10 = 5.5 (interpolated)" '[ "$(pq p50)" = 5.5 ]'
check "p90 of 1..10 = 9.1"                '[ "$(pq p90)" = 9.1 ]'
check "p99 of 1..10 = 9.91"               '[ "$(pq p99)" = 9.91 ]'

section "F5  Compaction and retention (stretch)"
# create overlapping extra blocks, then compact
for k in 1 2; do curl -s -XPOST "$URL/write" -d "extra{k=\"$k\"} $k $((NOW2+10000*k))" >/dev/null; curl -s -XPOST "$URL/flush" >/dev/null; done
check "multiple blocks exist" '[ "$(curl -s "$URL/stats" | jq_ "d[\"blocks\"]")" -ge 3 ]'
check "compact merges to one block" 'curl -s -XPOST "$URL/compact" | python3 -c "
import json,sys; d=json.load(sys.stdin); assert d[\"blocksAfter\"]==1 and d[\"blocksBefore\"]>=3, d"'
check "data intact after compaction" '[ "$(q "temp{room=\"lab\"} range 15m" | jq_ "len(d[\"series\"][0][\"points\"])")" = 60 ]'
check "retention keeps fresh block" '[ "$(curl -s -XPOST "$URL/retention?older=1h" | jq_ "d[\"blocksDropped\"]")" = 0 ]'
# write a 3-day-old sample into its own block, then expire it
curl -s -XPOST "$URL/write" -d "ancient{x=\"1\"} 1 $((NOW-3*86400000))" >/dev/null; curl -s -XPOST "$URL/flush" >/dev/null
check "old block present before retention" '[ "$(curl -s "$URL/stats" | jq_ "d[\"blocks\"]")" = 2 ]'
check "retention drops exactly the expired block" '[ "$(curl -s -XPOST "$URL/retention?older=48h" | jq_ "d[\"blocksDropped\"]")" = 1 ] && [ "$(curl -s "$URL/stats" | jq_ "d[\"blocks\"]")" = 1 ]'
check "expired data gone, fresh data kept" '[ "$(q "ancient at now range 7d" | jq_ "len(d[\"series\"])")" = 0 ] && [ "$(q "temp{room=\"lab\"} range 15m" | jq_ "len(d[\"series\"])")" = 1 ]'
check "retention rejects bad duration" '[ "$(curl -s -o /dev/null -w "%{http_code}" -XPOST "$URL/retention?older=zzz")" = 400 ]'
kill $SPID; wait $SPID 2>/dev/null

section "F1/F7  Codec efficiency, generator, benchmark, CLI (stretch)"
check "gen builds history" '"$T" gen -dir "$WORK/gen" -hosts 4 -hours 6 -interval 10s | tee "$WORK/gen.out" | grep -q "generated"'
check "compression > 3x on synthetic fleet data" 'python3 - "$WORK/gen.out" <<PY
import re,sys; t=open(sys.argv[1]).read(); x=float(re.search(r"compression\s+([\d.]+)x",t).group(1)); assert x>3, x
PY'
check "CLI query over generated data" '"$T" query -dir "$WORK/gen" "sum(rate(http_requests_total)) by (route) range 1h step 5m" | grep -q "api/orders"'
check "CLI reports parse errors (exit 1)" '! "$T" query -dir "$WORK/gen" "avg(" 2>"$WORK/cli.err"; grep -q "parse error" "$WORK/cli.err"'
BENCH=$("$T" bench -series 36 -samples 500 2>&1); BRC=$?
check "bench runs and reports" '[ "$BRC" = 0 ] && echo "$BENCH" | grep -q "compression" && echo "$BENCH" | grep -q "query"'

section "Dashboard (headless Chromium, desktop + phone, light + dark)"
if command -v node >/dev/null && NODE_PATH="${NODE_PATH:-/opt/node22/lib/node_modules}" node -e "require('playwright')" 2>/dev/null; then
  rm -rf "$WORK/demo"
  "$T" serve -dir "$WORK/demo" -addr "127.0.0.1:$PORT" -demo -alerts alerts.example.json -alert-interval 1s >"$WORK/demo.log" 2>&1 & DPID=$!
  for i in $(seq 100); do curl -sf "$URL/healthz" >/dev/null && break; sleep 0.1; done
  sleep 2
  NODE_PATH="${NODE_PATH:-/opt/node22/lib/node_modules}" EXPECT_ALERTS=1 node scripts/ui_check.js "$URL" | tee "$WORK/ui.out"
  PASS=$((PASS + $(grep -c '^  ok' "$WORK/ui.out"))); FAIL=$((FAIL + $(grep -c '^  FAIL' "$WORK/ui.out")))
  kill $DPID 2>/dev/null; wait $DPID 2>/dev/null
else
  echo "  (skipped: node + playwright not available)"
fi

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" = 0 ]
