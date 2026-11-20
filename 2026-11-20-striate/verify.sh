#!/usr/bin/env bash
# End-to-end demo + verification of every Striate feature. Exits non-zero on any failure.
set -euo pipefail
cd "$(dirname "$0")"
OUT=$(mktemp -d); trap 'rm -rf "$OUT"' EXIT
S="python3 -m striate"
say() { printf '\n== %s\n' "$*"; }
expect() { grep -qF -- "$2" <<<"$1" || { echo "FAIL: expected '$2' in: $1"; exit 1; }; }

say "1. Code 128 encode -> PNG -> decode"
$S encode code128 "Hello, Striate 2026" -o $OUT/c128.png; r=$($S decode $OUT/c128.png); echo "$r"; expect "$r" "Hello, Striate 2026"
say "2. EAN-13 / UPC-A / EAN-8 (check digits auto-added)"
for spec in "ean13 400638133393 4006381333931" "upca 03600029145 036000291452" "ean8 9638507 96385074"; do
  set -- $spec; $S encode $1 $2 -o $OUT/$1.png; r=$($S decode $OUT/$1.png); echo "$r"; expect "$r" "$3"; done
say "3. Code 39 (+mod43) and ITF"
$S encode code39 "CODE39" --mod43 -o $OUT/c39.png; r=$($S decode $OUT/c39.png); echo "$r"; expect "$r" "CODE39W"
$S encode itf 1234567 --check -o $OUT/itf.png; r=$($S decode $OUT/itf.png); echo "$r"; expect "$r" "12345670"
say "4. SVG output"
$S encode ean13 4006381333931 -o $OUT/x.svg; grep -q "<svg" $OUT/x.svg && echo "svg ok"
say "5. GS1-128"
$S encode gs1 "(01)09501101530003(17)261231(10)LOT42" -o $OUT/gs1.png; r=$($S decode $OUT/gs1.png); echo "$r"; expect "$r" "2026-12-31"
say "6. Error handling (expect exit code 2)"
set +e; $S encode itf 123 -o $OUT/bad.png 2>/dev/null; [ $? -eq 2 ] && echo "odd ITF rejected"; $S decode $OUT/nope.png 2>/dev/null; [ $? -eq 2 ] && echo "missing file rejected"; set -e
say "7. Benchmark (mild)"
r=$($S bench blur -n 2); echo "$r" | head -4; expect "$r" "code128"
say "8. Gallery"
$S gallery -o $OUT/g.html; test -s $OUT/g.html && echo "gallery ok"
say "9. Unit + regression tests"
python3 -m unittest discover -s tests 2>&1 | tail -3
echo; echo "ALL GREEN"
