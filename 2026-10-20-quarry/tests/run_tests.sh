#!/usr/bin/env bash
# Full verification of every Quarry feature.  Exit status is non-zero if anything fails.
cd "$(dirname "$0")/.." || exit 1
B=$PWD/build
LIB=$B/libquarry.so
TMP=$(mktemp -d)
trap 'rm -rf "$TMP"' EXIT
pass=0; fail=0
ok()   { pass=$((pass+1)); printf '  \033[32mok\033[0m   %s\n' "$1"; }
bad()  { fail=$((fail+1)); printf '  \033[31mFAIL\033[0m %s\n' "$1"; [ -n "${2:-}" ] && printf '%s\n' "$2" | sed 's/^/        /' | head -${3:-12}; }
check() { # name, command...
  local name=$1; shift
  local out; out=$("$@" 2>&1); local rc=$?
  if [ $rc -eq 0 ]; then ok "$name"; else bad "$name (exit $rc)" "$out"; fi
}
section() { printf '\n== %s\n' "$1"; }

[ -f "$LIB" ] || make -s all || exit 1

section "1. allocator core"
check "API semantics, 800k assertions (malloc/calloc/realloc/memalign/stats)" "$B/t_api"
check "8 threads, cross-thread frees, thread churn" "$B/t_threads"
if gcc -fsanitize=address,undefined -O1 -g -o "$TMP/t_api_san" tests/t_api.c src/quarry_core.c -pthread 2>/dev/null; then
  check "API tests under UBSan+ASan" "$TMP/t_api_san"
fi
if gcc -fsanitize=thread -O1 -g -DUSE_Q -o "$TMP/t_thr_tsan" tests/t_threads.c src/quarry_core.c -pthread 2>/dev/null; then
  check "thread test under ThreadSanitizer" "$TMP/t_thr_tsan"
fi

section "2. LD_PRELOAD drop-in"
check "threads: preloaded malloc" env LD_PRELOAD=$LIB "$B/t_threads_pre"
check "fork with live threads + asprintf/strdup/calloc" env LD_PRELOAD=$LIB "$B/t_misc"
for cmd in "ls -la /usr/include" "find /usr/lib -maxdepth 3 -name '*.so*'" "sort -u /usr/share/common-licenses/GPL-3" \
           "awk 'BEGIN{for(i=0;i<200000;i++)a[i%5000]=a[i%5000] i; print length(a)}'" "bash -c 'for i in \$(seq 300); do echo \$i; done | sort -n | tail -1'" \
           "python3 -c 'import json,re,collections; d=[{\"k\":i,\"v\":[i]*5} for i in range(50000)]; print(len(json.dumps(d)))'" \
           "tar cf - /usr/include | gzip -9 | wc -c"; do
  want=$(bash -c "$cmd" 2>/dev/null | md5sum)
  got=$(LD_PRELOAD=$LIB bash -c "$cmd" 2>/dev/null | md5sum)
  [ "$want" = "$got" ] && ok "same output as glibc: ${cmd:0:60}" || bad "output differs: $cmd"
done
echo 'int main(){return 0;}' > "$TMP/e.c"
out=$(LD_PRELOAD=$LIB gcc -O2 -o "$TMP/e" "$TMP/e.c" 2>&1) && "$TMP/e" && ok "gcc compiles and links under quarry" || bad "gcc under quarry" "$out"
out=$(PYTHONMALLOC=malloc LD_PRELOAD=$LIB python3 -c '
import collections, random
random.seed(1)
d = collections.defaultdict(list)
for i in range(300000):
    d[random.randrange(2000)].append("x" * random.randrange(1, 200))
    if i % 7 == 0: d[random.randrange(2000)].clear()
print(sum(len(v) for v in d.values()) > 0)' 2>&1)
[ "$out" = "True" ] && ok "python3 with PYTHONMALLOC=malloc routes all objects through quarry" || bad "python3 PYTHONMALLOC=malloc" "$out"
out=$(QUARRY_STATS=1 LD_PRELOAD=$LIB ls / 2>&1 >/dev/null)
echo "$out" | grep -q "STATISTICS" && echo "$out" | grep -q "calls: malloc" && ok "QUARRY_STATS prints a report at exit" || bad "stats report" "$out"

section "3. debug mode"
D() { QUARRY_DEBUG=1 LD_PRELOAD=$LIB "$B/t_bugs" "$@"; }
expect_error() { # case, message fragment
  local out; out=$(D "$1" 2>&1); local rc=$?
  if [ $rc -ne 0 ] && echo "$out" | grep -q "$2"; then ok "$1: $2"; else bad "$1: expected '$2' (exit $rc)" "$out"; fi
}
out=$(D clean 2>&1); [ $? -eq 0 ] && echo "$out" | grep -q "no leaks" && ok "clean program: no false positives, no leaks" || bad "clean program" "$out"
expect_error overflow   "heap buffer overflow: 1 byte written past the end"
expect_error overflow8  "heap buffer overflow: 8 bytes written past the end"
expect_error underflow  "heap buffer underflow: 1 byte before"
expect_error underflow3 "heap buffer underflow: 1 byte before the block was overwritten"
expect_error doublefree "double free"
expect_error invalidfree "invalid free()"
expect_error stackfree  "not returned by malloc"
expect_error deepunder  "at least 8 bytes before the block"
expect_error smash_size "header was overwritten"
expect_error smash_magic "invalid free()"
expect_error uaf        "use after free: byte 10"
expect_error reallocoverflow "heap buffer overflow"
expect_error align      "heap buffer overflow"
out=$(D uaf_read 2>&1); echo "$out" | grep -q "reads 0xdd" && ok "freed memory is poisoned with 0xDD" || bad "poison on free" "$out"
out=$(D uninit 2>&1);   echo "$out" | grep -q "reads 0xcd" && ok "fresh memory is filled with 0xCD" || bad "fill on alloc" "$out"
out=$(D leak 2>&1);     echo "$out" | grep -q "LEAK SUMMARY: 4 blocks, 5300 bytes" && echo "$out" | grep -q "300 bytes in 3 blocks" && ok "leak report groups blocks by allocation stack" || bad "leak report" "$out"
out=$(D noleak 2>&1);   echo "$out" | grep -q "no leaks" && ok "no leak reported when everything is freed" || bad "noleak" "$out"
out=$(D usable 2>&1);   echo "$out" | grep -q "usable=33" && ok "malloc_usable_size reports the requested size in debug mode" || bad "usable size" "$out"
out=$(D checkheap 2>&1); echo "$out" | grep -q "bad=1" && ok "quarry_check_heap() finds a corrupted live block on demand" || bad "check_heap" "$out"
out=$(QUARRY_ABORT=0 QUARRY_DEBUG=1 LD_PRELOAD=$LIB "$B/t_bugs" doublefree 2>&1); rc=$?
[ $rc -eq 0 ] && echo "$out" | grep -q "double free" && ok "QUARRY_ABORT=0 reports and continues" || bad "no-abort mode" "$out"
check "threads under debug mode (headers, quarantine, live list under contention)" env QUARRY_DEBUG=1 LD_PRELOAD=$LIB "$B/t_threads_pre"
check "fork under debug mode" env QUARRY_DEBUG=1 LD_PRELOAD=$LIB "$B/t_misc"
for cmd in "ls /usr/include" "sort -u /usr/share/common-licenses/GPL-3" "awk 'BEGIN{for(i=0;i<50000;i++)a[i]=i; print length(a)}'" "python3 -c 'print(sum(range(1000)))'"; do
  out=$(QUARRY_DEBUG=1 bash -c "LD_PRELOAD=$LIB $cmd" 2>&1 >/dev/null)
  echo "$out" | grep -q "ERROR" && bad "debug mode false positive in: $cmd" "$out" || ok "no false positives in real program: ${cmd:0:50}"
done

section "4. trace recorder + replay simulator"
T=$TMP/real.qtr
QUARRY_TRACE=$T LD_PRELOAD=$LIB python3 -c 'print(sum(i*i for i in range(100000)))' >/dev/null 2>&1
[ -s "$T" ] && ok "recorded a trace of python3 ($(stat -c %s "$T") bytes)" || bad "trace not written"
out=$("$B/qsim" info "$T" 2>&1); echo "$out" | grep -q "events" && ok "qsim info parses the recorded trace" || bad "qsim info" "$out"
out=$("$B/qsim" compare "$T" -a quarry,glibc,firstfit,buddy,bump --reps 1 2>&1); rc=$?
[ $rc -eq 0 ] && [ "$(echo "$out" | grep -c ' ok')" -ge 5 ] && ok "replay of a real trace verifies on all 5 allocators" || bad "replay real trace" "$out" 20
QUARRY_TRACE=$TMP/mt.%p.qtr LD_PRELOAD=$LIB "$B/t_threads_pre" >/dev/null 2>&1
mt=$(ls "$TMP"/mt.*.qtr 2>/dev/null | head -1)
out=$("$B/qsim" info "$mt" 2>&1); echo "$out" | grep -qE "[2-9] threads|[1-9][0-9] threads" && ok "multi-threaded trace records every thread, in one total order" || bad "mt trace" "$out"
out=$("$B/qsim" compare "$mt" -a quarry,glibc --reps 1 2>&1); [ $? -eq 0 ] && ok "replaying the multi-threaded trace verifies" || bad "mt replay" "$out"
# a shell script spawns many processes; each must write its own file instead of truncating the owner's
rm -f "$TMP"/sh.qtr*
QUARRY_TRACE=$TMP/sh.qtr LD_PRELOAD=$LIB bash -c 'ls / >/dev/null; ls /usr >/dev/null; echo hi >/dev/null'
nf=$(ls "$TMP"/sh.qtr* | wc -l); bad_ops=0
for f in "$TMP"/sh.qtr*; do "$B/qsim" info "$f" | grep -qE "[1-9][0-9]* unknown opcodes" && bad_ops=1; done
[ $nf -ge 3 ] && [ $bad_ops -eq 0 ] && ok "child processes write <trace>.<pid>, nothing is clobbered ($nf files)" || bad "trace files clobbered by children ($nf files)"
python3 - "$TMP" <<'PY'
import struct, sys
hd = b'QTRACE\x01\x00' + struct.pack('<II', 1, 40) + b'\0' * 48
open(sys.argv[1] + '/reuse.qtr', 'wb').write(hd + b''.join(struct.pack('<BxxxIQQQQ', 1, 1, i, 0x5000, 64, 0) for i in range(2000)))
PY
out=$("$B/qsim" compare "$TMP/reuse.qtr" --reps 1 2>&1); [ $? -eq 0 ] && ok "2000 mallocs of one address (two events per record) replay cleanly" || bad "address reuse trace" "$out"
if gcc -fsanitize=address -O1 -g -o "$TMP/qsim_asan" src/qsim.c src/report.c src/models.c src/quarry_core.c -pthread -lm 2>/dev/null; then
  out=$("$TMP/qsim_asan" info "$TMP/reuse.qtr" 2>&1); [ $? -eq 0 ] && ok "trace loader is clean under AddressSanitizer" || bad "loader under ASan" "$out"
fi
out=$(python3 tests/fuzz_traces.py "$B" 40 2>&1); [ $? -eq 0 ] && ok "$out" || bad "corrupt-trace fuzzing" "$out"
for w in web tree queue frag vector mixed; do
  "$B/qgen" $w -n 60000 -s 3 -o "$TMP/$w.qtr" 2>/dev/null
  out=$("$B/qsim" compare "$TMP/$w.qtr" --reps 1 2>&1); rc=$?
  [ $rc -eq 0 ] && ok "qgen $w -> replay verifies on every allocator" || bad "workload $w" "$out" 14
done

section "5. stretch features: report, wrapper, symbolizer"
out=$("$B/qsim" compare "$TMP/mixed.qtr" --reps 1 --html "$TMP/rep.html" 2>&1); rc=$?
[ $rc -eq 0 ] && [ -s "$TMP/rep.html" ] && grep -q '"frames":\[' "$TMP/rep.html" && ok "qsim --html writes a self-contained report with heap-map frames" || bad "html report" "$out"
if [ -x /opt/pw-browsers/chromium-1194/chrome-linux/chrome ] && [ -d /opt/node22/lib/node_modules/playwright ]; then
  out=$(PLAYWRIGHT_MODULE=/opt/node22/lib/node_modules/playwright node tests/check_report.js "$TMP/rep.html" 2>&1 | grep -v agent-proxy); rc=$?
  echo "$out" | grep -q "report renders" && ok "report renders in headless Chromium (light+dark, no errors, no overflow at 390px)" || bad "report in browser" "$out"
fi
out=$(tools/quarry --stats -- ls / 2>&1 >/dev/null); echo "$out" | grep -q STATISTICS && ok "tools/quarry --stats wrapper" || bad "wrapper --stats" "$out"
out=$(tools/quarry --debug -- build/t_bugs doublefree 2>&1); echo "$out" | grep -q "double free" && ok "tools/quarry --debug wrapper" || bad "wrapper --debug" "$out"
out=$(tools/quarry 2>&1); [ $? -eq 2 ] && ok "wrapper prints usage and exits 2 without a command" || bad "wrapper usage"
out=$(QUARRY_DEBUG=1 LD_PRELOAD=$LIB build/t_bugs leak 2>&1 | python3 tools/qsym.py --exe build/t_bugs)
echo "$out" | grep -q "leaker at .*t_bugs.c:" && ok "qsym.py resolves leak stacks to function and file:line" || bad "qsym" "$out"
out=$(build/qgen web -n 50 -o /dev/null 2>&1); [ $? -ne 0 ] || bad "qgen accepted a tiny -n"
build/qgen nosuch -o "$TMP/x" 2>/dev/null; [ $? -eq 2 ] && ok "qgen rejects an unknown workload" || bad "qgen unknown workload"

echo
printf '%d passed, %d failed\n' $pass $fail
[ $fail -eq 0 ]
