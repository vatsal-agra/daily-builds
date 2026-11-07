#!/bin/bash
# Full verification gate for Sable. Exits non-zero on the first failing stage.
#   ./verify.sh          everything
#   ./verify.sh --quick  skip fuzzing and the headless-browser check
set -u
cd "$(dirname "$0")"
QUICK=0; [ "${1:-}" = "--quick" ] && QUICK=1
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
fail=0; pass=0
ok()  { printf '   ok   %s\n' "$1"; pass=$((pass+1)); }
bad() { printf '   FAIL %s\n' "$1"; fail=$((fail+1)); }
run() { local n="$1"; shift; if "$@" >"$T/out" 2>&1; then ok "$n"; else bad "$n"; tail -20 "$T/out"; fi; }
S="$T/sable"

echo "== 1. build, format, vet"
run "go build" go build -o "$S" ./cmd/sable
run "gofmt clean" bash -c '[ -z "$(gofmt -l .)" ]'
run "go vet" go vet ./...

echo "== 2. unit / property / regression tests (all executors vs oracle, mutation-test regressions, scale)"
run "go test" go test -count=1 ./...

echo "== 3. every example through every executor (AST, IR, SSA O0-O2, VM x 2 allocators x 6 K)"
for f in examples/*.sb; do
  run "check $(basename "$f")" "$S" check "$f"
done

echo "== 4. feature demos through the CLI"
run "run: fib result"          bash -c "$S run examples/fib.sb 2>&1 | grep -q 'exit value: 17711'"
run "run: trap exits 3"        bash -c "$S run examples/trap.sb >/dev/null 2>&1; [ \$? -eq 3 ]"
run "run: engines agree"       bash -c "[ \"\$($S run examples/nqueens.sb -engine ast 2>&1)\" = \"\$($S run examples/nqueens.sb -engine vm -k 3 -alg gc 2>&1)\" ]"
run "ir: phi present in SSA"   bash -c "$S ir examples/primes.sb -stage ssa | grep -q '= phi'"
run "ir: lowered has load/store" bash -c "$S ir examples/primes.sb -stage lowered | grep -q 'load \\$'"
run "ir: inlining removes calls" bash -c "! $S ir examples/gcdlcm.sb | grep -q 'call gcd'"
run "ir: -noinline keeps calls" bash -c "$S ir examples/gcdlcm.sb -noinline | grep -q 'call gcd'"
run "ir: SCCP folds constfold.sb to constants" bash -c "[ \$($S ir examples/constfold.sb -func main | grep -c 'call') -eq 0 ]"
run "asm: callee-saved save/restore" bash -c "$S asm examples/fib.sb -k 4 -noinline | grep -q 'st    \\[fp+'"
run "asm: spills at K=2"       bash -c "$S asm examples/mandel.sb -k 2 | grep -q 'ld    '"
run "stats: table"             bash -c "$S stats examples/gcdlcm.sb | grep -q 'graph-color'"
run "compile error has caret"  bash -c "printf 'func main() { return 1 }' | $S run - 2>&1 | grep -q '\\^'"
run "nesting bomb is an error" bash -c "python3 -c \"print('func main() { return '+'('*100000+'1'+')'*100000+'; }')\" | $S run - 2>&1 | grep -q 'too deeply nested'"
run "endless loop stops fast"  bash -c "echo 'func main() { while 1 { } }' | timeout 20 $S run - 2>&1 | grep -q 'out of fuel'"

echo "== 5. report"
run "report writes html" "$S" report examples/mandel.sb -o "$T/r.html" -k 5
run "report is self-contained" bash -c "! grep -qE '(src|href)=\"https?:' $T/r.html"

if [ $QUICK -eq 0 ]; then
  echo "== 6. differential fuzzing (random programs, 16 executors each)"
  run "fuzz 1500 programs"           "$S" fuzz -n 1500 -seed 424242
  run "fuzz 600 programs, 6 helpers" "$S" fuzz -n 600 -seed 777000 -funcs 6
  echo "== 7. headless browser check of the report (desktop + phone, light + dark)"
  cat >"$T/shot.js" <<JS
const { chromium } = require('playwright');
(async () => {
  const b = await chromium.launch(); let bad = 0;
  for (const [w, scheme] of [[1280,'light'],[390,'dark']]) {
    const p = await (await b.newContext({ viewport:{width:w,height:900}, colorScheme:scheme })).newPage();
    const errs=[]; p.on('pageerror',e=>errs.push(String(e)));
    await p.goto('file://$T/r.html');
    await p.evaluate(()=>document.querySelectorAll('details').forEach(d=>d.open=true));
    const over = await p.evaluate(()=>document.documentElement.scrollWidth>window.innerWidth+1);
    const svgs = await p.evaluate(()=>document.querySelectorAll('svg.cfg').length);
    console.log(w, scheme, 'overflow', over, 'cfgs', svgs, 'errors', errs.length);
    if (over || errs.length || svgs < 2) bad++;
  }
  await b.close(); process.exit(bad);
})();
JS
  run "report renders (no overflow, no errors)" node "$T/shot.js"
fi

echo
if [ $fail -eq 0 ]; then echo "ALL GREEN ($pass checks)"; else echo "$fail FAILED ($pass passed)"; exit 1; fi
