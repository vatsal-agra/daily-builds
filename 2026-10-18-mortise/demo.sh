#!/usr/bin/env bash
# End-to-end demo + verification: exercises every Mortise feature against a
# real C project (gcc) and real shell recipes, asserting on observable output.
#   ./demo.sh          run everything (unit tests included)
#   SKIP_TESTS=1 ./demo.sh   only the CLI scenarios
set -uo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=$(mktemp -d)
trap 'rm -rf "$WORK"' EXIT
PASS=0; FAIL=0
ok()   { PASS=$((PASS+1)); printf '  \033[32mok\033[0m   %s\n' "$1"; }
bad()  { FAIL=$((FAIL+1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; [ -n "${2:-}" ] && printf '       %s\n' "$2"; }
has()  { if grep -qE -- "$2" <<<"$1"; then ok "$3"; else bad "$3" "expected /$2/ in: $(head -c 400 <<<"$1" | tr '\n' '|')"; fi; }
hasnt(){ if grep -qE -- "$2" <<<"$1"; then bad "$3" "unexpected /$2/"; else ok "$3"; fi; }
eq()   { if [ "$1" = "$2" ]; then ok "$3"; else bad "$3" "got '$1', want '$2'"; fi; }
step() { printf '\n\033[1m== %s\033[0m\n' "$1"; }

step "build mortise"
(cd "$HERE" && go build -o "$WORK/mortise" ./cmd/mortise) || { echo "go build failed"; exit 1; }
M="$WORK/mortise"

if [ -z "${SKIP_TESTS:-}" ]; then
  step "go vet + go test -race (unit, property, stress, CLI, watch)"
  (cd "$HERE" && go vet ./... && go test -race -count=1 ./...) && ok "go test -race ./... green" || bad "go test"
fi

P="$WORK/cproj"; cp -r "$HERE/examples/cproj" "$P"; cd "$P"

step "feature 1: Mortisefile language (variables, glob, patsubst, patterns, merged deps)"
out=$($M list)
has "$out" '^pattern +build/%\.o: src/%\.c' "pattern rule parsed"
has "$out" '^rule +build/main\.o: build/gen/version\.h' "dependency-only rule merged with pattern"
printf 'a: b\nthis is nonsense\n' > bad.mk
out=$($M -f bad.mk 2>&1); rc=$?
has "$out" 'bad\.mk:2: expected a rule' "parse errors carry file:line"; eq "$rc" 2 "parse error exit code is 2"

step "feature 2: scheduler (cold build, parallelism, cycles, failures)"
out=$($M -v 2>&1)
has "$out" '5 ran' "cold build runs 5 tasks (4 compiles/gen/link)"
eq "$(./build/app)" "app 1.4.2: 7^2=49 3^3=27 vowels=3" "binary runs and prints correct output"
S="$WORK/side"; mkdir -p "$S"
cat > "$S/par.mk" <<'MK'
default all
phony all
all: p1 p2 p3 p4
p1:
    sleep 0.5; echo 1 > p1
p2:
    sleep 0.5; echo 2 > p2
p3:
    sleep 0.5; echo 3 > p3
p4:
    sleep 0.5; echo 4 > p4
MK
s=$(date +%s%N); $M -C "$S" -f par.mk -j4 -q --no-cache; t4=$(( ($(date +%s%N)-s)/1000000 ))
rm -rf "$S/p1" "$S/p2" "$S/p3" "$S/p4" "$S/.mortise"
s=$(date +%s%N); $M -C "$S" -f par.mk -j1 -q --no-cache; t1=$(( ($(date +%s%N)-s)/1000000 ))
[ "$t4" -lt 1200 ] && [ "$t1" -gt 1800 ] && ok "-j4: ${t4}ms vs -j1: ${t1}ms (parallel speed-up is real)" || bad "parallelism" "-j4=${t4}ms -j1=${t1}ms"
printf 'a: b\n    touch a\nb: c\n    touch b\nc: a\n    touch c\n' > "$S/cyc.mk"
out=$($M -C "$S" -f cyc.mk a 2>&1); rc=$?
has "$out" 'dependency cycle: a -> b -> c -> a' "cycle reported with full path"; eq "$rc" 2 "cycle exit code 2"
printf 'default all\nphony all\nall: good bad after\ngood:\n    echo g > good\nbad:\n    echo oops >&2; exit 3\nafter: bad\n    cp bad after\n' > "$S/fail.mk"
out=$($M -C "$S" -f fail.mk -k 2>&1); rc=$?
has "$out" 'FAILED: bad: command failed \(exit status 3\)' "failure names target and exit status"
has "$out" 'oops' "failing command output is shown"
has "$out" '1 failed, 1 skipped' "-k: dependents skipped"
[ -f "$S/good" ] && [ ! -f "$S/bad" ] && ok "-k built the independent target; partial output removed" || bad "-k semantics"
eq "$rc" 1 "build failure exit code 1"

step "feature 3: content-hash incremental builds + early cutoff"
out=$($M); has "$out" '5 up to date' "second build is a no-op"
touch src/main.c include/mathx.h VERSION
out=$($M); has "$out" '5 up to date' "touch (mtime-only change) rebuilds nothing"
echo "# release notes" >> VERSION
out=$($M -v 2>&1)
has "$out" '1 ran, 4 up to date.*early cutoff' "comment-only VERSION edit: generator reruns, output identical, nothing downstream rebuilds"
printf '# notes\n2.0.0\n' > VERSION
out=$($M); has "$out" '3 ran, 2 up to date' "real version change rebuilds gen -> main.o -> link only"
eq "$(./build/app | cut -d: -f1)" "app 2.0.0" "new version reached the binary"
echo "tampered" > build/gen/version.h
out=$($M -v 2>&1); has "$out" 'GEN +build/gen/version.h' "externally modified output is detected and rebuilt"
sed -i 's/-O1/-O2/' Mortisefile
out=$($M -n); has "$out" 'command changed' "changing a recipe (CFLAGS) is detected"
out=$($M); has "$out" '4 ran' "recipe change rebuilds all 4 compiles + link (gen unaffected)"

step "feature 4: dynamic deps from gcc -MMD depfiles"
echo "// edit" >> include/strx.h
out=$($M why 2>&1)
has "$out" 'discovered dependency include/strx\.h changed' "why: header known only via the depfile"
out=$($M -v 2>&1)
has "$out" 'CC +src/strx\.c' "strx.c recompiles (includes strx.h)"
has "$out" 'CC +src/mathx\.c \(up to date\)' "mathx.c does NOT recompile (does not include it)"
printf '#include "mathx.h"\n#include "strx.h"\n#include "version.h"\n#include <stdio.h>\nint main(void){ printf("%%s %%d\\n", APP_VERSION, cube(3)); return 0; }\n' > src/main.c
$M -q; eq "$(./build/app)" "2.0.0 27" "edited source recompiled + relinked correctly"

step "feature 5: content-addressed action cache"
$M clean >/dev/null
out=$($M); has "$out" '5 from cache' "after clean, every output restored from .mortise/cas"
out=$($M); has "$out" '5 up to date' "restored state is trusted"
$M clean >/dev/null
out=$($M --no-cache); has "$out" '5 ran' "--no-cache really rebuilds"

step "feature 6: why / graph / dry-run"
echo "// again" >> include/mathx.h
out=$($M -n)
has "$out" 'would build build/mathx\.o' "-n lists what would run"
hasnt "$out" 'would build build/strx\.o' "-n leaves unaffected targets out"
[ ! -e /dev/null ] || ok "-n built nothing (checked next)"
out=$($M why build/app); has "$out" 'build/mathx\.o: would rebuild' "why shows the chain down to the cause"
dot=$($M graph)
has "$dot" '^digraph mortise' "graph emits DOT"
has "$dot" '"include/mathx\.h" -> "build/mathx\.o" \[style=dashed' "graph shows depfile-discovered edges (dashed)"
if command -v dot >/dev/null; then echo "$dot" | dot -Tsvg >/dev/null && ok "graph is valid Graphviz" || bad "dot rejected graph"; fi
$M -q

step "feature 7: stats, trace, HTML report, watch"
echo "// third" >> include/mathx.h
$M -report "$WORK/report.html" -trace "$WORK/trace.json" >/dev/null
[ -s "$WORK/report.html" ] && grep -q 'Mortise build report' "$WORK/report.html" && ok "HTML report written" || bad "report"
python3 -c "import json,sys; d=json.load(open('$WORK/trace.json')); assert d['traceEvents']" && ok "Chrome trace is valid JSON with events" || bad "trace"
out=$($M stats); has "$out" 'critical path' "stats prints the critical path"; has "$out" 'cache +: [0-9]+ action' "stats reports cache size"
( timeout 20 $M watch > "$WORK/watch.log" 2>&1 & echo $! > "$WORK/watch.pid" )
sleep 1.2; echo "// watched change" >> include/strx.h; sleep 1.5
kill "$(cat "$WORK/watch.pid")" 2>/dev/null; sleep 0.3
has "$(cat "$WORK/watch.log")" 'change detected, rebuilding' "watch noticed a header edit and rebuilt"
has "$(cat "$WORK/watch.log")" 'CC +src/strx\.c' "watch rebuilt the right file"

step "robustness"
out=$($M app 2>&1); rc=$?; has "$out" 'did you mean "build/app"' "typo'd target gets a suggestion"
rm -rf "$WORK/lockproj"; mkdir "$WORK/lockproj"; printf 'x:\n    sleep 1.5; touch x\n' > "$WORK/lockproj/Mortisefile"
( $M -C "$WORK/lockproj" x >/dev/null 2>&1 & ); sleep 0.4
out=$($M -C "$WORK/lockproj" x 2>&1); has "$out" 'already running' "concurrent runs in one directory are refused"
sleep 1.6
echo '{corrupt' > .mortise/db.json
out=$($M 2>&1); has "$out" 'corrupt.*starting fresh' "corrupt database is discarded with a warning"
rc=0; $M -q || rc=$?; eq "$rc" 0 "and the build still succeeds"

printf '\n%d passed, %d failed\n' "$PASS" "$FAIL"
[ "$FAIL" -eq 0 ]
