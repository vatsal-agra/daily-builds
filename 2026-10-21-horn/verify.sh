#!/usr/bin/env bash
# Full verification: build, vet, Go tests, Prolog suites, example transcripts, REPL transcripts, CLI behaviour.
set -u
cd "$(dirname "$0")"
fail=0
ok()   { printf '  \033[32mok\033[0m   %s\n' "$1"; }
bad()  { printf '  \033[31mFAIL\033[0m %s\n' "$1"; fail=1; }

echo "== build"
go build -o horn . && ok "go build" || { bad "go build"; exit 1; }
go vet ./... && ok "go vet" || bad "go vet"
[ -z "$(gofmt -l .)" ] && ok "gofmt clean" || bad "gofmt: $(gofmt -l .)"

echo "== go tests (round-trip fuzz, arithmetic vs math/big, standard order, unify)"
go test ./... >/tmp/horn_gotest.log 2>&1 && ok "go test" || { bad "go test"; tail -20 /tmp/horn_gotest.log; }

echo "== prolog suites"
for f in tests/core.pl tests/adversarial.pl tests/tabling.pl tests/strings.pl tests/engine.pl tests/io.pl; do
  [ -f "$f" ] || continue
  out=$(timeout 120 ./horn "$f" -g halt 2>&1 | grep -E '^[0-9]+ passed' )
  case "$out" in
    *" 0 failed") ok "$f: $out";;
    *) bad "$f: ${out:-no summary}";;
  esac
done

echo "== example transcripts"
for f in examples/*.pl; do
  b=${f%.pl}
  [ -f "$b.expected" ] || continue
  if timeout 120 ./horn "$f" -g halt 2>&1 | diff -q - "$b.expected" >/dev/null; then ok "$f"; else bad "$f differs from $b.expected"; fi
done

echo "== REPL transcripts"
for f in tests/repl/*.in; do
  b=${f%.in}
  flags="-q"; [ "$(basename "$b")" = all ] && flags="-q --all"
  if ./horn $flags < "$f" 2>&1 | diff -q - "$b.out" >/dev/null; then ok "$f"; else bad "$f differs from $b.out"; fi
done

echo "== CLI behaviour"
./horn -g 'X is 6*7, write(X), nl' -t halt | grep -qx 42 && ok "-g/-t" || bad "-g/-t"
./horn -g 'halt(3)' ; [ $? -eq 3 ] && ok "halt(3) exit code" || bad "halt(3) exit code"
./horn -g fail >/dev/null 2>&1; [ $? -eq 1 ] && ok "failing -g exits 1" || bad "failing -g exit code"
./horn -g 'throw(x)' >/dev/null 2>&1; [ $? -eq 2 ] && ok "raising -g exits 2" || bad "raising -g exit code"
echo 'halt.' | ./horn -q; [ $? -eq 0 ] && ok "halt. at toplevel" || bad "halt. at toplevel"
out=$(printf 'main :- read(X), Y is X * 2, write(Y), nl.\n' > /tmp/horn_read.pl; echo '21.' | ./horn /tmp/horn_read.pl -g main -t halt)
[ "$out" = "42" ] && ok "read/1 from stdin" || bad "read/1 from stdin ($out)"

echo "== benchmark smoke (informational)"
timeout 120 ./horn examples/bench.pl -g main -t halt 2>&1 | sed 's/^/  /'

[ $fail -eq 0 ] && echo "ALL GREEN" || { echo "FAILURES"; exit 1; }
