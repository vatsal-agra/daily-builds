#!/usr/bin/env bash
# Girder end-to-end verification: formatting, vet, unit tests, every CLI feature on real models.
set -euo pipefail
cd "$(dirname "$0")"
OUT=$(mktemp -d); trap 'rm -rf "$OUT"' EXIT
pass=0; step(){ printf '\n== %s\n' "$1"; }
ok(){ pass=$((pass+1)); printf '  ok: %s\n' "$1"; }
die(){ printf '  FAIL: %s\n' "$1"; exit 1; }
near(){ awk -v a="$1" -v b="$2" -v t="$3" 'BEGIN{d=a-b; if(d<0)d=-d; exit !(d<=t*(b<0?-b:b))}'; }

step "format / vet / build"
[ -z "$(gofmt -l .)" ] || die "gofmt"; ok "gofmt clean"
go vet ./... ; ok "go vet"
go build -o "$OUT/girder" ./cmd/girder; ok "build"
G="$OUT/girder"

step "unit + physics tests"
go test -count=1 ./... | tail -3; ok "go test ./..."

step "feature 3: closed-form validation suite"
$G validate -o "$OUT/val.html" | tail -3 | grep -q "all .* checks passed" || die "validate"; ok "validate passes"

step "features 1,2,4: solve every model, all three solvers agree"
for f in plate_hole cantilever cylinder dam portal warren_truss; do
  $G solve testdata/$f.fem -o "$OUT/$f.html" >"$OUT/$f.txt" || die "solve $f"
  grep -q NaN "$OUT/$f.html" && die "NaN in $f report"
  ok "$f solved, report has no NaN"
done
vm=$(awk '/max von Mises/{print $5}' "$OUT/cantilever.txt")
near "$vm" 300 0.03 || die "cantilever vm $vm (beam theory 300)"; ok "cantilever peak stress $vm vs Mc/I=300"
d0=$($G solve testdata/cantilever.fem -solver direct | awk '/strain energy/{print $4}')
d1=$($G solve testdata/cantilever.fem -solver cg-jacobi | awk '/strain energy/{print $4}')
d2=$($G solve testdata/cantilever.fem -solver cg-ic0 | awk '/strain energy/{print $4}')
near "$d1" "$d0" 1e-8 && near "$d2" "$d0" 1e-8 || die "solvers disagree $d0 $d1 $d2"; ok "strain energy identical across solvers ($d0)"
grep -q "N=-56.003" "$OUT/portal.txt" || die "portal column axial force"; ok "portal frame column force 56.003 kN (statics)"
grep -q "N=70 " "$OUT/warren_truss.txt" || die "truss chord force"; ok "Warren truss chord force 70 kN (method of sections)"

step "stretch 5: topology optimisation"
$G topopt -case mbb -nx 40 -ny 14 -iter 40 -q -o "$OUT/topo.html" | tee "$OUT/topo.txt" | tail -1
awk '/volume/{for(i=1;i<=NF;i++) if($i=="volume") print $(i+1)}' "$OUT/topo.txt" | tr -d ',' | { read v; near "$v" 0.4 0.005 || die "volume $v"; }; ok "volume constraint met"
grep -q "stiffer" "$OUT/topo.txt" && ok "compliance improved over uniform design"

step "stretch 6: modal analysis"
f1=$($G modal testdata/modal_plate.fem | awk '/mode  1/{print $3}')
near "$f1" 81.5 0.02 || die "f1=$f1"; ok "plate fundamental $f1 Hz vs beam theory 81.5"

step "stretch 8: heat"
$G heat testdata/heat_hole.fem | grep -q "T in \[20, 300\]" || die "heat range"; ok "heat solution bounded by boundary temperatures (max principle)"

step "hostile input is rejected with a precise message"
chk(){ printf "$2" > "$OUT/bad.fem"; if $G solve "$OUT/bad.fem" >"$OUT/err.txt" 2>&1; then die "accepted: $1"; fi; grep -q "$3" "$OUT/err.txt" || { cat "$OUT/err.txt"; die "message for $1"; }; ok "$1"; }
chk "unsupported body" "material E=1 t=1\nmesh rect w=1 h=1 nx=2 ny=2\nfix node=0 dofs=xy\nload node=8 fx=1\n" "move freely"
chk "bad selection" "material E=1 t=1\nmesh rect w=1 h=1 nx=2 ny=2\nfix where x==9 dofs=x\n" "matches no nodes"
chk "orphan frame node" "frame\nnode 0 0\nnode 1 0\nnode 5 5\nbeam 0 1 E=1 A=1 I=1\nsupport 0 dofs=xyr\n" "not connected"
chk "truss mechanism" "frame\nnode 0 0\nnode 4 0\nnode 8 0\nbar 0 1 E=1 A=1\nbar 1 2 E=1 A=1\nsupport 0 dofs=xy\nsupport 2 dofs=xy\nforce 1 fy=-1\n" "mechanism"
chk "negative modulus" "material E=-5\n" "Young"
chk "unknown directive" "material E=1\nwobble\n" "unknown directive"

printf '\nALL GREEN — %d end-to-end checks\n' "$pass"
