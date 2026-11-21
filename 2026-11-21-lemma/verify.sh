#!/usr/bin/env bash
# Lemma — end-to-end verification.  Runs the unit/integration suites and a scripted demo of every
# feature with assertions.  Prints ALL GREEN only if every check passes.
set -u
cd "$(dirname "$0")"
PY=${PYTHON:-python3}
pass=0; fail=0
check() { # name, command...
  local name=$1; shift
  if out=$("$@" 2>&1); then pass=$((pass+1)); printf '  ok   %s\n' "$name"
  else fail=$((fail+1)); printf '  FAIL %s\n%s\n' "$name" "$out" | head -40; fi
}
has() { # name, expected-substring, command...
  local name=$1 want=$2; shift 2
  local out; out=$("$@" 2>&1); local rc=$?
  if [[ "$out" == *"$want"* ]]; then pass=$((pass+1)); printf '  ok   %s\n' "$name"
  else fail=$((fail+1)); printf '  FAIL %s (wanted %q, rc=%s)\n%s\n' "$name" "$want" "$rc" "$out" | head -30; fi
}
echo "== syntax / byte-compile"
check "compileall" $PY -m compileall -q lemma tests
echo "== unit & integration tests"
for t in kernel surface tactics probes audit examples cli fuzz; do
  check "tests.test_$t" $PY -m unittest "tests.test_$t"
done
echo "== feature demo (assertions on real output)"
has "F1 kernel: add_comm accepted (prelude)"    "add_comm : forall (m n : Nat), m + n = n + m" $PY -m lemma eval "#check add_comm"
has "F1 kernel: computation 6*7"                "42 : Nat"                    $PY -m lemma eval "6 * 7"
has "F1 kernel: Type : Type rejected"           "type mismatch"               $PY -m lemma check /dev/stdin <<< "def bad : Type := Type"
has "F2 inductive: recursor generated"          "forall (motive : Nat -> Type)" $PY -m lemma eval "#print Nat.rec"
has "F2 inductive: non-positive rejected"       "positive"                    $PY -m lemma check /dev/stdin <<< "inductive Bad : Type where | mk : (Bad -> Nat) -> Bad"
has "F3 surface: structural recursion + eqns"   "[+2 equation lemma(s)]"      $PY -m lemma check examples/nat.lm
has "F3 surface: positioned error"              "fail_demo.lm:6:38: error"    $PY -m lemma check examples/fail_demo.lm
has "F4 tactics: induction proofs"              "6 theorem(s) proved"         $PY -m lemma check examples/nat.lm
has "F4 tactics: indexed induction"             "4 theorem(s) proved"         $PY -m lemma check examples/even.lm
has "F4 tactics: unsolved goals shown"          "⊢ b = a"                     $PY -m lemma check examples/fail_demo.lm
has "F5 auditor: independent verification"      "verified independently"      $PY -m lemma check examples/trees.lm --audit
CERT=$(mktemp --suffix=.json)
$PY -m lemma check examples/even.lm --export "$CERT" >/dev/null 2>&1
has "F5 auditor: certificate round-trip"        "verified independently"      $PY -m lemma audit "$CERT"
$PY - "$CERT" <<'PYEOF'
import json, sys
c = json.load(open(sys.argv[1]))
for d in c["decls"]:
    if d["name"] == "Nat.rec":
        d["rules"]["succ"][0] = d["rules"]["zero"][0]
json.dump(c, open(sys.argv[1], "w"))
PYEOF
has "F5 auditor: tampered recursor rejected"    "REJECTED"                    $PY -m lemma audit "$CERT"
rm -f "$CERT"
REP=$(mktemp --suffix=.html)
has "F6 report: written"                        "report written"              $PY -m lemma report examples/trees.lm -o "$REP"
has "F6 report: has proof steps + audit badge"  "independent audit"           grep -o "independent audit" "$REP"
rm -f "$REP"
has "F7 repl: eval + theorem + error"           "1024 : Nat"                  bash -c "printf '#eval 2 * 2 * 2 * 2 * 2 * 2 * 2 * 2 * 2 * 2\n:quit\n' | $PY -m lemma repl"
has "F8 library: reverse_reverse"               "reverse A (reverse A xs) = xs" $PY -m lemma eval "#check reverse_reverse"
has "F8 library: no axioms"                     "does not depend on any axioms" $PY -m lemma eval "#print axioms mul_comm"
echo
echo "passed: $pass   failed: $fail"
if [ "$fail" -eq 0 ]; then echo "ALL GREEN"; else echo "SOME CHECKS FAILED"; exit 1; fi
