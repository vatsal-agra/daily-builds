#!/usr/bin/env bash
# Mutation check: apply one deliberate bug at a time and require the test suite to notice.
cd "$(dirname "$0")/.."
BK=$(mktemp -d)/src; cp -r src "$BK"
trap 'rm -rf src && cp -r "$BK" src' EXIT
KILLED=0; SURV=0; EQ=0; EQUIV=''
mut() { # EQUIV=1 marks a known equivalent mutant
  local EQUIV=$EQUIV # file, old, new
  python3 - "$1" "$2" "$3" <<'PY'
import sys
p,o,n=sys.argv[1:4]
t=open(p).read()
assert o in t, "pattern missing: "+o
open(p,'w').write(t.replace(o,n,1))
PY
  if cargo test --release 2>&1 | grep -q "FAILED\|error\["; then echo "KILLED   : $1: $2"; KILLED=$((KILLED+1));
  elif [ -n "$EQUIV" ]; then echo "survived (equivalent mutant, see REVIEW.md): $1: $2"; EQ=$((EQ+1));
  else echo "SURVIVED : $1: $2"; SURV=$((SURV+1)); fi
  rm -rf src && cp -r "$BK" src
}
EQUIV=1 mut src/caller.rs "if e.1 + 1 >= bs + FLANK && e.1 + e.2.len() + FLANK <= be" "if true"
mut src/caller.rs "let eps = (0.004 * (1.0 + copies as f64)).min(0.15);" "let eps = 0.0001;"
mut src/mapper.rs "(60.0 * gap * quality)" "(60.0 * quality)"
mut src/mapper.rs "if sg.score + p.clip_penalty >= lo.score" "if false"
mut src/fm.rs "row = self.c[b as usize] + self.rank(b, row);
            steps += 1;" "row = self.c[b as usize] + self.rank(b, row);
            steps += 2;"
mut src/align.rs "if e_ext > e_open" "if e_ext >= e_open + 1000"
EQUIV=1 mut src/dbg.rs "if !changed {
            break;
        }" "break;"
mut src/dbg.rs "g.pred(y).len() != 1 || visited" "visited"
mut src/vcf.rs "if r.last() == a.last() && (r.len() > 1 || a.len() > 1)" "if false"
mut src/mash.rs "(2.0 * j / (1.0 + j)).ln()" "(j).ln()"
mut src/asmeval.rs "(p.diag - a.diag).abs() > DIAG_TOL" "false"
mut src/sim.rs "if rng.chance(p.het_frac) {" "if true {"
mut src/mapper.rs "c.exact |= exact;" ""
mut src/caller.rs "if alt_tot >= 6 && (af == 0 || ar == 0)" "if false && (af == 0 || ar == 0)"
mut src/seq.rs "if r.names.contains(&f.name) {" "if false {"
mut src/mapper.rs "if flag & 4 == 0 && !(seq.is_empty() && flag & (256 | 2048) != 0) {" "if flag & 4 == 0 {"
mut src/fm.rs "if sa_samples.iter().any(|&s| s as usize >= n) {" "if false {"
mut src/dbg.rs "if sm[v] > 0.8 * sm[peak]" "if false && sm[v] > 0.8 * sm[peak]"
echo "mutants killed: $KILLED, surviving: $SURV, equivalent: $EQ"
[ "$SURV" -eq 0 ]
