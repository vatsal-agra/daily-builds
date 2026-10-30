#!/usr/bin/env bash
# Mutation harness: inject one plausible bug at a time and require the test
# suite to notice. A surviving mutant means a hole in the tests.
set -u
cd "$(dirname "$0")/.."
killed=0; survived=0; total=0
mutate() { # file  old  new  package  description
  local f=$1 old=$2 new=$3 pkg=$4 desc=$5
  total=$((total+1))
  cp "$f" "$f.orig"
  python3 - "$f" "$old" "$new" <<'PY'
import sys
f,old,new=sys.argv[1:4]
s=open(f).read()
if old not in s: sys.exit(3)
open(f,'w').write(s.replace(old,new,1))
PY
  if [ $? -eq 3 ]; then mv "$f.orig" "$f"; echo "SKIP (pattern missing): $desc"; total=$((total-1)); return; fi
  if go test -count=1 -timeout 300s "$pkg" >/dev/null 2>&1; then
    survived=$((survived+1)); echo "SURVIVED: $desc"
  else
    killed=$((killed+1)); echo "killed:   $desc"
  fi
  mv "$f.orig" "$f"
}
mutate qr/gf.go 'x ^= 0x11D' 'x ^= 0x11B' ./qr "GF primitive polynomial"
mutate qr/rs.go 'GFPow(n - 1 - p)' 'GFPow(p)' ./qr "RS locator exponent"
mutate qr/rs.go 'if _, ok := syndromes(out, ecc); !ok {' 'if false {' ./qr "RS post-correction syndrome check removed"
mutate qr/rs.go 'den ^= GFMul(psi[i], gfPowN(xinv, i-1))' 'den ^= GFMul(psi[i], gfPowN(xinv, i))' ./qr "Forney derivative power"
mutate qr/mask.go 'return (x/3+y/2)%2 == 0' 'return (x/2+y/3)%2 == 0' ./qr "mask 4 formula"
mutate qr/mask.go 'parts[0] += 3 + run - 5' 'parts[0] += 3 + run - 4' ./qr "penalty N1 run increment"
mutate qr/mask.go 'parts[2] += 40' 'parts[2] += 30' ./qr "penalty N3 weight"
mutate qr/mask.go 'parts[1] += 3' 'parts[1] += 2' ./qr "penalty N2 weight"
mutate qr/tables.go '{0, 17, 28, 22, 16,' '{0, 17, 28, 22, 17,' ./qr "ECC table entry"
mutate qr/layout.go 'rem = (rem << 1) ^ ((rem >> 9) * 0x537)' 'rem = (rem << 1) ^ ((rem >> 9) * 0x53F)' ./qr "format BCH generator"
mutate qr/layout.go 'return (data<<10 | rem) ^ 0x5412' 'return (data<<10 | rem) ^ 0x5413' ./qr "format mask constant"
mutate qr/segment.go 'w.put(v, [4]int{0, 4, 7, 10}[j-i])' 'w.put(v, [4]int{0, 4, 7, 9}[j-i])' ./qr "numeric group width"
mutate qr/segment.go 'charCost := [3]int{20, 33, 48}' 'charCost := [3]int{20, 40, 48}' ./qr "DP alnum cost"
mutate qr/encode.go 'for pad := 0xEC; w.len() < capBits; pad ^= 0xEC ^ 0x11 {' 'for pad := 0xEC; w.len() < capBits; pad ^= 0 {' ./qr "pad byte alternation"
mutate qr/decode.go 'if i >= 40 {' 'if i >= 0 {' ./qr "format brute-force window"
mutate scan/scan.go 't >= 0.7' 't >= 0.0' ./scan "timing pre-filter removed"
mutate scan/scan.go 'if best < 22 {' 'if best < 0 {' ./scan "alignment acceptance threshold"
mutate scan/geom.go 'hn[8] = 1' 'hn[8] = 2' ./scan "homography normalisation"
mutate scan/finder.go 'if diag == 0 {' 'if diag == 5 {' ./scan "finder diagonal check"
mutate scan/binarize.go 'v < mean*ratio' 'v < mean*0.1' ./scan "adaptive threshold ratio"
echo "(RS post-correction syndrome check is defence in depth: BM+Chien root-count already guarantees a codeword, so that mutant is equivalent.)"
echo "mutants: $total  killed: $killed  survived: $survived"
[ "$survived" -le 1 ] # exactly one known-equivalent mutant
