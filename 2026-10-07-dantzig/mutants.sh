#!/usr/bin/env bash
# Mutation harness: plants bugs in a scratch copy and demands that the test suite notices each one.
set -u
cd "$(dirname "$0")"
SRC=$(pwd)
killed=0; survived=0
mutate() { # name file old new pkgs
  local name=$1 file=$2 old=$3 new=$4 pkgs=$5
  local W; W=$(mktemp -d); cp -r "$SRC"/. "$W"/
  if ! python3 - "$W/$file" "$old" "$new" <<'PY'
import sys
p, old, new = sys.argv[1:4]
s = open(p).read()
if s.count(old) < 1:
    sys.exit(3)
open(p, "w").write(s.replace(old, new, 1))
PY
  then echo "  ??   $name: pattern not found"; survived=$((survived+1)); rm -rf "$W"; return; fi
  if (cd "$W" && go test $pkgs >/dev/null 2>&1); then
    echo "  LIVE $name  <-- survived"; survived=$((survived+1))
  else
    echo "  dead $name"; killed=$((killed+1))
  fi
  rm -rf "$W"
}
echo "planting bugs..."
mutate "bound: wrong side for d>0"        internal/exact/exact.go 'case 1:
			if box.Lo[j] == nil {
				return nil, false
			}
			s.Add(s, t.Mul(d[j], box.Lo[j]))' 'case 1:
			if box.Hi[j] == nil {
				return nil, false
			}
			s.Add(s, t.Mul(d[j], box.Hi[j]))' "./internal/exact ./internal/lp ./internal/bb"
mutate "farkas: accept zero value"        internal/exact/exact.go 'if v.Sign() <= 0 {' 'if v.Sign() < 0 {' "./internal/exact ./internal/lp ./internal/bb"
mutate "ray: ignore objective"            internal/exact/exact.go 'if Dot(cost, dir).Sign() >= 0 {' 'if Dot(cost, dir).Sign() >= 2 {' "./internal/exact ./internal/lp"
mutate "ray: allow bounded direction"     internal/exact/exact.go 'if v.Hi != nil {
				return fmt.Errorf("ray increases' 'if false {
				return fmt.Errorf("ray increases' "./internal/exact ./internal/lp"
mutate "checker: accept weak bound leaf"  internal/bb/proof.go 'if eff.Cmp(incObj) < 0 {' 'if eff.Cmp(incObj) < -1 {' "./internal/bb"
mutate "checker: skip incumbent ints"     internal/bb/proof.go 'exact.CheckPoint(m, box0, x, true)' 'exact.CheckPoint(m, box0, x, false)' "./internal/bb"
mutate "checker: no hash check"           internal/bb/proof.go 'if p.ModelHash != HashModel(m) {' 'if false {' "./internal/bb ./cmd/dantzig"
mutate "checker: ignore unreachable nodes" internal/bb/proof.go 'return nil, fmt.Errorf("proof contains unreachable node %d", i)' 'continue' "./internal/bb"
mutate "checker: gcd off-by-one"          internal/exact/exact.go 'if first.Cmp(hi) <= 0 {' 'if first.Cmp(hi) < 0 {' "./internal/exact"
mutate "bb: branch cuts off integer"      internal/bb/bb.go 'box.Hi[j] = new(big.Rat).Set(fl)' 'box.Hi[j] = new(big.Rat).Sub(fl, big.NewRat(1, 1))' "./internal/bb ./internal/gen"
mutate "bb: prune too eagerly"            internal/bb/bb.go 'return lb >= s.incF-1e-9*(1+math.Abs(s.incF))' 'return lb >= s.incF-1.5' "./internal/bb ./internal/gen"
mutate "simplex dual: wrong eligibility"  internal/simplex/dual.go 'return sgn*t < 0' 'return sgn*t > 0' "./internal/lp ./internal/bb"
mutate "simplex primal: ignore upper bound" internal/simplex/simplex.go 'case !math.IsInf(hi, 1):
					return blk{hi, hi - x}, true' 'case false:
					return blk{hi, hi - x}, true' "./internal/lp ./internal/bb"
mutate "parser: swap <= and >="           internal/model/parse.go 'case tLE:
			row.Hi = rhs
		case tGE:
			row.Lo = rhs' 'case tLE:
			row.Lo = rhs
		case tGE:
			row.Hi = rhs' "./internal/model ./internal/lp"
mutate "sens: wrong sign of shadow price" internal/sens/sens.go 'Dual: sgn(y[i])' 'Dual: y[i]' "./internal/sens"
mutate "sens: cost range off"             internal/sens/sens.go 'rng.Lo = new(big.Rat).Neg(d[j])' 'rng.Lo = new(big.Rat).Set(d[j])' "./internal/sens"
mutate "gen: tsp distance"                internal/gen/gen.go 'return int64(sqrt(dx*dx+dy*dy) + 0.5)' 'return int64(sqrt(dx*dx+dy*dy))+1' "./internal/gen"
echo
echo "mutants: $killed killed, $survived survived"
[ $survived -eq 0 ]
