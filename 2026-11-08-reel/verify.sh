#!/bin/bash
# Full verification gate for Reel. Exits non-zero if anything fails.
#   ./verify.sh          everything
#   ./verify.sh --quick  skip the slow report/x264 stages
set -u
cd "$(dirname "$0")"
QUICK=0; [ "${1:-}" = "--quick" ] && QUICK=1
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fail=0; pass=0
ok()  { printf '   ok   %s\n' "$1"; pass=$((pass+1)); }
bad() { printf '   FAIL %s\n' "$1"; fail=$((fail+1)); }
run() { local n="$1"; shift; if "$@" >"$T/out" 2>&1; then ok "$n"; else bad "$n"; tail -15 "$T/out"; fi; }
R="$T/reel"

echo "== 1. build, format, vet"
run "go build" go build -o "$R" ./cmd/reel
run "gofmt clean" bash -c '[ -z "$(gofmt -l .)" ]'
run "go vet" go vet ./...

echo "== 2. unit / property / fuzz tests (range coder, transform, interpolation, bit-exact x12 tool combos, fuzz, cuts, rate control)"
run "go test" go test -count=1 ./...

echo "== 3. CLI pipeline: gen -> enc -> dec -> psnr, every preset, B-frames, deblock, rate control"
for pre in pan objects mixed cut noise zoom; do
  "$R" gen -preset $pre -w 96 -h 80 -n 12 -o "$T/$pre.y4m" >/dev/null
  run "$pre: enc+dec matches encoder PSNR" bash -c "
    $R enc -i $T/$pre.y4m -o $T/$pre.reel -qp 30 -b 2 > $T/$pre.enc &&
    $R dec -i $T/$pre.reel -o $T/$pre.dec.y4m >/dev/null &&
    $R psnr $T/$pre.y4m $T/$pre.dec.y4m > $T/$pre.psnr &&
    a=\$(grep -o 'PSNR [0-9.]*' $T/$pre.enc | head -1 | cut -d' ' -f2) &&
    b=\$(grep -o 'PSNR [0-9.]*' $T/$pre.psnr | head -1 | cut -d' ' -f2) &&
    python3 -c \"import sys; sys.exit(0 if abs(float('\$a')-float('\$b'))<0.006 else 1)\""
done
run "info lists B-frames"      bash -c "$R info $T/mixed.reel | grep -q ' B '"
run "bitrate target within 8%" bash -c "
  $R gen -preset mixed -w 176 -h 144 -n 30 -o $T/rc.y4m >/dev/null &&
  $R enc -i $T/rc.y4m -o $T/rc.reel -bitrate 200 -b 2 | grep -o '[0-9.]* kbit/s' | head -1 | python3 -c \"import sys; v=float(sys.stdin.read().split()[0]); sys.exit(0 if abs(v-200)/200<0.08 else 1)\""

echo "== 4. error handling"
run "bad qp rejected"          bash -c "! $R enc -i $T/pan.y4m -o $T/x.reel -qp 99 2>&1 | grep -q panic && ! $R enc -i $T/pan.y4m -o $T/x.reel -qp 99"
run "missing file rejected"    bash -c "! $R enc -i $T/nope.y4m -o $T/x.reel"
run "non-reel file rejected"   bash -c "! $R dec -i $T/pan.y4m -o $T/x.y4m"
run "no doubled error prefix"  bash -c "$R dec -i $T/pan.y4m -o $T/x.y4m 2>&1 | grep -qv 'reel: reel:'"
run "truncated stream rejected" bash -c "head -c 300 $T/mixed.reel > $T/trunc.reel; ! $R dec -i $T/trunc.reel -o $T/x.y4m"
run "unreachable bitrate warns" bash -c "$R enc -i $T/mixed.y4m -o $T/x.reel -bitrate 1 | grep -q warning"

echo "== 5. interoperability: ffmpeg reads our Y4M; odd sizes round-trip"
if command -v ffmpeg >/dev/null; then
  run "ffmpeg decodes our y4m" bash -c "ffmpeg -v error -i $T/mixed.dec.y4m -f null -"
  "$R" gen -preset mixed -w 17 -h 33 -n 5 -o "$T/odd.y4m" >/dev/null
  run "odd size 17x33 round trip" bash -c "$R enc -i $T/odd.y4m -o $T/odd.reel -b 1 >/dev/null && $R dec -i $T/odd.reel -o $T/odd.dec.y4m >/dev/null && ffmpeg -v error -i $T/odd.dec.y4m -f null -"
  ffmpeg -v error -y -f lavfi -i "cellauto=size=176x144:rate=30" -frames:v 30 -pix_fmt yuv420p "$T/ca.y4m" 2>/dev/null
  run "real clip: scroll is not all I-frames (review #1)" bash -c "$R enc -i $T/ca.y4m -o $T/ca.reel -qp 28 >/dev/null && [ \$(stat -c %s $T/ca.reel) -lt 100000 ]"
else
  echo "   skip ffmpeg not installed"
fi

echo "== 6. tool ablation: each tool must pay for itself (BD-rate from the lab)"
if [ $QUICK -eq 0 ]; then
  run "report builds, tools monotonic" bash -c "
    $R report -quick -o $T/report.html >/dev/null 2>&1 &&
    grep -q 'Intra only' $T/report.html && grep -q 'bit-exact' $T/report.html &&
    python3 - $T/report.html <<'PY'
import re,sys
import html; h=html.unescape(open(sys.argv[1]).read())
rows=re.findall(r'<td>(?:<span[^>]*></span>)([^<]*)</td><td class=\"num\">[0-9.]+</td><td class=\"num\">[0-9.]+</td>(.*?)</tr>',h)
d={}
for name,rest in rows:
    m=re.findall(r'([+-][0-9.]+)%',rest)
    if m: d[name]=float(m[0])
need=['P-frames, 16x16, integer-pel','+ quarter-pel motion','+ partitions & RDO','+ deblocking filter','+ B-frames (2)']
bad=[n for n in need if d.get(n,1)>=0]
print(d); sys.exit(1 if bad else 0)
PY"
else
  echo "   skip (--quick)"
fi

echo
if [ $fail -eq 0 ]; then echo "ALL GREEN ($pass checks)"; else echo "FAILED ($fail of $((pass+fail)))"; exit 1; fi
