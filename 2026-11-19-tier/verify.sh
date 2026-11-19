#!/usr/bin/env bash
# End-to-end verification for Tier. Exits non-zero on the first failure.
set -u
cd "$(dirname "$0")"
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  ok   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  FAIL %s\n' "$1"; }
check(){ if eval "$2" >/dev/null 2>&1; then ok "$1"; else bad "$1"; fi; }
OUT=$(mktemp -d); trap 'rm -rf "$OUT"' EXIT

echo "== build & static checks"
check "gofmt clean"            '[ -z "$(gofmt -l .)" ]'
check "go vet"                 'go vet ./...'
check "build"                  'go build -o "$OUT/tier" ./cmd/tier'
T="$OUT/tier"

echo "== unit / property / oracle tests (race detector)"
check "go test -race ./..."    'go test -race -count=1 ./...'

echo "== feature 1: DOT parser (CLI)"
check "parses every example"   'for f in examples/*.dot; do $T metrics $f >/dev/null || exit 1; done'
check "positioned parse error" '$T metrics - <<<"digraph { a -> }" 2>&1 | grep -q "line 1, col 16"'

echo "== feature 2: cycle removal"
check "cycle reversed (states.dot)" '$T metrics examples/states.dot | grep -E "^reversed +[1-9]"'
check "both strategies work"   '$T metrics examples/states.dot -acyclic dfs && $T metrics examples/states.dot -acyclic greedy'

echo "== feature 3: network simplex layering"
check "simplex <= longest edge length (build.dot)" '
  a=$($T metrics examples/build.dot -ranker simplex | awk "/edge length/{print \$3}")
  b=$($T metrics examples/build.dot -ranker longest | awk "/edge length/{print \$3}")
  [ "$a" -le "$b" ]'

echo "== feature 4: crossings + Brandes-Köpf + SVG"
check "sweep beats no ordering" '
  a=$($T metrics examples/layered40.dot | awk "/crossings/{print \$2}")
  b=$($T metrics examples/layered40.dot -order none | awk "/crossings/{print \$2}")
  [ "$a" -lt "$b" ]'
check "BK has fewer bends than packed" '
  a=$($T metrics examples/layered40.dot | awk "/bends/{print \$2}")
  b=$($T metrics examples/layered40.dot -coord packed | awk "/bends/{print \$2}")
  [ "$a" -lt "$b" ]'
for f in examples/*.dot; do
  check "svg is well-formed XML: $f" "$T layout $f -o $OUT/x.svg && python3 -c \"import xml.dom.minidom,sys;xml.dom.minidom.parse('$OUT/x.svg')\""
done

echo "== stretch: splines, polyline, LR, labels, loops, bands, json"
check "spline path uses curves"   '$T layout examples/build.dot | grep -q " C\|C[0-9]"'
check "polyline has no curves"    '! $T layout examples/build.dot -polyline | grep -q "<path d=\"M[^\"]*C"'
check "LR differs from TB"        '! cmp -s <($T layout examples/build.dot) <($T layout examples/build.dot -rankdir LR)'
check "edge labels rendered"      '$T layout examples/compiler.dot | grep -q ">typed AST<"'
check "self-loop rendered"        '$T layout examples/compiler.dot | grep -q ">dedupe<"'
check "rank bands"                '$T layout examples/compiler.dot -bands | grep -q "class=\"band\""'
check "json output"               '$T layout examples/build.dot -format json | python3 -c "import json,sys;d=json.load(sys.stdin);assert len(d[\"Nodes\"])==12"'

echo "== stretch: report + exact oracle"
check "html report has 5 cards"   '[ "$($T report examples/build.dot | grep -c "<section class=\"card")" = 5 ]'
check "oracle: gap >= 0"          'printf "digraph{a->c;a->d;b->c;b->d;c->e;d->e}" | $T exact - | grep -E "^gap +[0-9]+$"'

echo "== robustness"
check "empty graph"               'echo "digraph{}" | $T layout - | grep -q "<svg"'
check "150 isolated nodes wrap"   'python3 -c "print(\"digraph{\"+\";\".join(f\"n{i}\" for i in range(150))+\"}\")" | $T layout - | python3 -c "
import re,sys; s=sys.stdin.read(); w,h=map(float,re.search(r\"viewBox=.0 0 ([0-9.]+) ([0-9.]+)\",s).groups()); assert w<3*h,(w,h)"'
check "800-node cyclic graph < 10s" '$T gen -kind cyclic -n 800 -seed 9 -density 1.5 | timeout 10 $T metrics -'
check "deterministic output"      'cmp <($T layout examples/layered40.dot) <($T layout examples/layered40.dot)'
check "bad weight rejected"       '! $T metrics - <<<"digraph{a->b[weight=x]}"'
check "huge node rejected"        '! $T metrics - <<<"digraph{a[width=99999999]}"'

echo
echo "passed $PASS, failed $FAIL"
if [ "$FAIL" -eq 0 ]; then echo "ALL GREEN"; else exit 1; fi
