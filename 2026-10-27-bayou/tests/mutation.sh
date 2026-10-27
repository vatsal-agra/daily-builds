#!/usr/bin/env bash
# Mutation check of the test-suite: inject a bug, expect `go test` to fail ("killed"), restore.
# Exits non-zero if any injected bug survives. usage: tests/mutation.sh
cd "$(dirname "$0")/.."
status=0
# Two mutants are deliberately not listed because they are semantically equivalent:
#  - cpdag R3's `!adj[c][d]` guard (unreachable for CPDAGs derived from DAGs; the brute-force class test passes either way)
#  - report.jsonForScript's '<' escape (encoding/json already escapes it; the function is defence in depth)
mutate() { # file old new pkgs...
  local file=$1 old=$2 new=$3; shift 3
  cp "$file" "$file.orig"
  python3 - "$file" "$old" "$new" <<'PY' || { mv "$file.orig" "$file"; echo "pattern not found: $old"; status=1; return; }
import sys
p, old, new = sys.argv[1:4]
s = open(p).read()
assert old in s
open(p, 'w').write(s.replace(old, new, 1))
PY
  if go test -count=1 "$@" >/dev/null 2>&1; then echo "SURVIVED  $file: $old"; status=1; else echo "killed    $file: $old"; fi
  mv "$file.orig" "$file"
}
mutate internal/graph/graph.go          'if anc[s.v] {'                                   'if obs[s.v] {'                                   ./internal/graph ./internal/infer
mutate internal/infer/ve.go             'assign[v] = int(am.Val[idx])'                    'assign[v] = 0'                                    ./internal/infer
mutate internal/infer/jt.go             'b = factor.Product(b, msg[ei][dir])'             'b = b'                                            ./internal/infer
mutate internal/infer/jt.go             'acc = factor.Product(acc, msg[oi][odir])'        'acc = acc'                                        ./internal/infer
mutate internal/factor/factor.go        'if x > best {'                                   'if x >= best {'                                   ./internal/factor ./internal/infer
mutate internal/factor/factor.go        'out.Val[ri] = best'                              'out.Val[ri] = sum'                                ./internal/factor ./internal/infer
mutate internal/learn/params.go         'if it > 0 && ll-prev < o.Tol'                    'if it > 0 && ll-prev < o.Tol && false'            ./internal/learn
mutate internal/learn/params.go         'cpt[r*c+s] = (counts[r*c+s] + alpha) / (tot + alpha*float64(c))' 'cpt[r*c+s] = (counts[r*c+s] + alpha) / (tot + alpha)' ./internal/learn
mutate internal/bn/bn.go                'cfg[i] = r % c'                                  'cfg[i] = (r + 1) % c'                             ./internal/parse ./internal/infer ./cmd/bayou
mutate internal/infer/ve.go             'rel = net.Ancestors(roots)'                      'rel = map[int]bool{}; for i := range net.Vars { rel[i] = true }' ./internal/infer
mutate internal/infer/approx.go         'w *= net.Vars[v].CPT[r*c+s]'                     'w *= 1'                                           ./internal/infer
mutate internal/infer/approx.go         'p *= net.Vars[ch].CPT[net.RowIndex(ch, a)*net.Card(ch)+a[ch]]' 'p *= 1'                         ./internal/infer
mutate internal/infer/voi.go            'row.Expected += p * post.Entropy()'              'row.Expected += post.Entropy()'                   ./internal/infer
mutate internal/learn/cpdag.go          'if dir[a][c] && dir[c][b] {'                     'if false {'                                       ./internal/learn
mutate internal/learn/structure.go      'score += s.lgamma(float64(c)) - s.lgamma(tot+float64(c))' 'score += s.lgamma(float64(c)) - s.lgamma(tot)' ./internal/learn
mutate internal/learn/structure.go      '!reversalCreatesCycle(parents, from, to)'        'true'                                             ./internal/learn
mutate internal/parse/csv.go            'if !ok && missingTokens[strings.ToLower(cell)]'  'if missingTokens[strings.ToLower(cell)]'          ./internal/parse
mutate internal/parse/bn.go             'func isWildcard(t token) bool { return t.k == tWord && t.s == "*" }' 'func isWildcard(t token) bool { return t.s == "*" }' ./internal/parse
exit $status
