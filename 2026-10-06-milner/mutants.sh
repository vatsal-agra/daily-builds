#!/usr/bin/env bash
# Mutation check: plant a bug in the implementation and demand that the test-suite notices.
# Usage: ./mutants.sh        (needs git; restores every file afterwards)
set -u
cd "$(dirname "$0")"
killed=0; survived=0; total=0
run_mutant() { # name file python-expression-old python-expression-new
  local name="$1" file="$2" old="$3" new="$4"
  total=$((total+1))
  cp "$file" "$file.orig"
  if ! python3 - "$file" "$old" "$new" <<'PY'
import sys
path, old, new = sys.argv[1:4]
s = open(path).read()
if old not in s:
    print("  mutation target not found:", old[:60]); sys.exit(3)
open(path, "w").write(s.replace(old, new, 1))
PY
  then mv "$file.orig" "$file"; echo "ERROR  $name (could not apply)"; survived=$((survived+1)); return; fi
  if ! go build ./... 2>/dev/null; then
    echo "INVALID   $name (mutant does not compile)"; survived=$((survived+1))
  elif go test -count=1 ./... >/dev/null 2>&1; then
    echo "SURVIVED  $name"; survived=$((survived+1))
  else
    echo "killed    $name"; killed=$((killed+1))
  fi
  mv "$file.orig" "$file"
}

run_mutant "occurs check disabled"            internal/types/unify.go      "if x == v {
			return true
		}" "if false {
			return true
		}"
run_mutant "level adjustment removed"         internal/types/unify.go      "if x.Level > v.Level {
			x.Level = v.Level
		}" ""
run_mutant "never generalise"                 internal/types/infer.go      "if x.Level > i.level && x.Level != Generic {
			x.Level = Generic
		}" ""
run_mutant "value restriction off"            internal/types/infer.go      "case *syntax.ECon:
		return x.Arg == nil || nonExpansive(x.Arg)" "case *syntax.EApp:
		return true
	case *syntax.ECon:
		return x.Arg == nil || nonExpansive(x.Arg)"
run_mutant "instantiate shares variables"     internal/types/infer.go      "if r, ok := m[x]; ok {
				return r
			}
			v := i.newVar()
			m[x] = v
			return v" "if r, ok := m[x]; ok {
				return r
			}
			v := i.newVar()
			return v"
run_mutant "row rewrite drops the tail"       internal/types/unify.go      "return u.unify(ca.Args[1], rest)" "_ = rest
	return nil"
run_mutant "failed decl keeps weak bindings"  internal/types/decl.go       "in.u.undo()" ""
run_mutant "arrow parens dropped"             internal/types/print.go      "if prec > 0 {
				b.WriteByte('(')
			}
			p.write(b, x.Args[0], 1)" "p.write(b, x.Args[0], 1)"
run_mutant "exhaustive when any head present" internal/check/exhaust.go    "return len(heads) == len(fam)" "return true"
run_mutant "default matrix keeps all rows"    internal/check/exhaust.go    "if r[0].isWild() {
			out = append(out, r[1:])
		}" "out = append(out, r[1:])"
run_mutant "guarded arms count as covering"   internal/check/exhaust.go    "if !a.guarded {
				rows = append(rows, row{ip})
			}" "rows = append(rows, row{ip})"
run_mutant "or-pattern alternatives ignored"  internal/check/exhaust.go    "for _, a := range q[0].alts {" "for _, a := range q[0].alts[:1] {"
run_mutant "tail call becomes a real call"    internal/eval/machine.go     "return fv.Fn.Body, newEnv, nil, false" "return nil, nil, m.eval(fv.Fn.Body, newEnv), true"
run_mutant "de Bruijn index off by one"       internal/eval/compile.go     "return &nLocal{Idx: len(c.scope) - 1 - i}" "return &nLocal{Idx: len(c.scope) - i}"
run_mutant "constructor index ignored"        internal/eval/machine.go     "if c.Idx != p.Idx {
			return false
		}" ""
run_mutant "redefinition mutates old cell"    internal/eval/interp.go      "in.Globals[name] = cell" "if old, ok := in.Globals[name]; ok {
		old.V = cell.V
		return
	}
	in.Globals[name] = cell"
run_mutant "structural compare ignores tails" internal/eval/builtins.go    "a, b = x.Arg, y.Arg" "return 0"
run_mutant "layout rule disabled"             internal/syntax/parser.go    "if !p.layout || i == 0" "if true || !p.layout || i == 0"
run_mutant "match arm order reversed"         internal/eval/machine.go     "for i := range x.Arms {
		arm := &x.Arms[i]" "for i := len(x.Arms) - 1; i >= 0; i-- {
		arm := &x.Arms[i]"
echo
echo "mutants: $total, killed: $killed, survived: $survived"
[ "$survived" -eq 0 ]
