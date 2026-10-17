#!/usr/bin/env bash
# Exercises every Kolmo feature end to end. Exits non-zero on the first failure.
set -euo pipefail
cd "$(dirname "$0")"
W=$(mktemp -d); trap 'rm -rf "$W"' EXIT
go build -o "$W/kolmo" ./cmd/kolmo
K="$W/kolmo"
step() { printf '\n\033[1m== %s\033[0m\n' "$*"; }

# corpus: prose (this repo's docs), low-entropy synthetic, and incompressible bytes
cat PLAN.md REVIEW.md ../LEDGER.md 2>/dev/null | head -c 300000 > "$W/prose.txt"
python3 -c "
import random; random.seed(7)
open('$W/dna.txt','wb').write(bytes(random.choice(b'ACGT') for _ in range(200000)))
open('$W/random.bin','wb').write(bytes(random.randrange(256) for _ in range(100000)))
open('$W/zeros.bin','wb').write(bytes(1_000_000))"

step "1. DEFLATE: ours -> system gzip, system gzip -> ours"
"$K" gzip -l 9 "$W/prose.txt" > "$W/p.gz"
gzip -dc "$W/p.gz" | cmp - "$W/prose.txt" && echo "gzip(1) decodes our stream: OK"
gzip -9c "$W/prose.txt" | "$K" gunzip - | cmp - "$W/prose.txt" && echo "we decode gzip(1) output: OK"
echo "ours: $(wc -c < "$W/p.gz") bytes   gzip -9: $(gzip -9c "$W/prose.txt" | wc -c) bytes"

step "2-4. every method through the KOL1 container, verified"
for f in prose.txt dna.txt random.bin; do "$K" bench "$W/$f"; done

step "4. auto selection, inspect, CRC integrity"
"$K" compress -f "$W/prose.txt" -o "$W/prose.kol"
"$K" inspect "$W/prose.kol"
"$K" decompress -f "$W/prose.kol" -o "$W/prose.out" && cmp "$W/prose.txt" "$W/prose.out" && echo "round trip OK"
python3 - "$W/prose.kol" <<'PY'
import sys; p=sys.argv[1]; b=bytearray(open(p,'rb').read()); b[len(b)//2]^=1; open(p+'.bad','wb').write(b)
PY
if "$K" decompress -f "$W/prose.kol.bad" -o "$W/bad.out" 2>"$W/err"; then echo "FAIL: corruption not detected"; exit 1; fi
echo "bit flip detected: $(cat "$W/err")"

step "size-bomb guard"
printf 'KOL1\x03\x80\x80\x80\x80\x04\x00\x00\x00\x00abcd' > "$W/bomb.kol"
if "$K" decompress "$W/bomb.kol" -o "$W/bomb.out" 2>"$W/err"; then echo "FAIL"; exit 1; fi
echo "rejected: $(cat "$W/err")"

step "6. heat map report"
"$K" heat -max 50000 -f "$W/prose.txt" -o "$W/heat.html"
test -s "$W/heat.html" && echo "report: $(wc -c < "$W/heat.html") bytes"

step "7. deflate levels"
for l in 1 4 6 9; do printf 'level %s: ' $l; "$K" gzip -l $l "$W/prose.txt" | wc -c; done

step "go test ./... (unit + fuzz-style + interop + CLI)"
go test ./... 2>&1 | grep -v "no test files"
printf '\n\033[1;32mALL FEATURES VERIFIED\033[0m\n'
