#!/usr/bin/env bash
# End-to-end verification: unit tests + CLI round trips + the perceptual-vs-flat claim + report.
set -euo pipefail
cd "$(dirname "$0")"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
echo "== vet + unit tests"; gofmt -l . | (! grep .) ; go vet ./... ; go test ./... 2>&1 | tail -3
go build -o "$T/chime" ./cmd/chime; C="$T/chime"
echo "== CLI round trip on every signal"
for s in tones castanets bells voice noise sweep silence mix; do
  $C gen -signal $s -seconds 3 -o $T/$s.wav
  $C encode -b 64 $T/$s.wav $T/$s.chm >/dev/null
  $C decode $T/$s.chm $T/$s.dec.wav
  [ "$(stat -c %s $T/$s.wav)" = "$(stat -c %s $T/$s.dec.wav)" ] || { echo "size mismatch $s"; exit 1; }
  echo "  ok $s ($(stat -c %s $T/$s.chm) bytes)"
done
echo "== perceptual beats flat (audible excess) at equal bitrate"
for s in mix bells castanets; do
  out=$($C eval -b 48 $T/$s.wav | tail -1); echo "  $s: $out"
  python3 - "$out" <<'PY'
import re,sys
m=re.search(r'excess ([\d.]+) → ([\d.]+) dB',sys.argv[1]); assert m and float(m.group(2))<float(m.group(1)), sys.argv[1]
PY
done
echo "== flags: noise fill, no M/S, no switching, quality mode"
$C encode -nf -noms -noswitch -b 48 $T/mix.wav $T/f.chm >/dev/null; $C decode $T/f.chm $T/f.wav
$C encode -q 25 $T/mix.wav $T/q.chm >/dev/null; $C info $T/q.chm
echo "== error handling (each must fail cleanly)"
for cmd in "encode -b -5 $T/mix.wav $T/x.chm" "encode -b 64 -q 3 $T/mix.wav $T/x.chm" "decode $T/mix.wav $T/x.wav" "gen -signal bogus -o $T/x.wav" "encode $T/nonexistent.wav $T/x.chm"; do
  if $C $cmd 2>/dev/null; then echo "  should have failed: $cmd"; exit 1; else echo "  rejected: ${cmd%% *}"; fi
done
head -c 300 $T/mix.chm > $T/trunc.chm; ! $C decode $T/trunc.chm $T/x.wav 2>/dev/null && echo "  rejected: truncated chm"
echo "== report"
$C report -b 48 -o $T/r.html $T/mix.wav; grep -q "Bitstream budget" $T/r.html && echo "  report ok ($(stat -c %s $T/r.html) bytes)"
echo "ALL GREEN"
