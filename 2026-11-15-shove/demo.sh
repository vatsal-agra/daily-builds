#!/usr/bin/env bash
# End-to-end demo / verification: exercises every feature, exits non-zero on the first failure.
set -euo pipefail
cd "$(dirname "$0")"
T=$(mktemp -d); trap 'rm -rf "$T"' EXIT
pass=0; step() { printf '\n== %s\n' "$*"; }
ok() { pass=$((pass+1)); echo "   ok: $*"; }
expect_fail() { if "$@" >"$T/out" 2>&1; then echo "   FAIL: expected failure: $*"; exit 1; else ok "rejected as expected -> $(head -1 "$T/out")"; fi; }

go build -o "$T/shove" ./cmd/shove
S="$T/shove"

step "1  parser: valid pack, and precise errors"
"$S" solve levels/starter.txt -q >/dev/null && ok "starter pack parses + solves"
printf '#####\n#@$$.#\n#####\n' >"$T/bad.txt"; expect_fail "$S" solve "$T/bad.txt"
printf '#####\n#@$x#\n#####\n' >"$T/bad2.txt"; expect_fail "$S" solve "$T/bad2.txt"
printf '#####\n#@$.\n#####\n' >"$T/bad3.txt"; expect_fail "$S" solve "$T/bad3.txt"

step "2  optimal solver (Microban #1 = 8 pushes) + proof of unsolvability"
"$S" solve levels/starter.txt -n 1 | tee "$T/s1"; grep -q 'pushes 8 (optimal)' "$T/s1" && ok "8 pushes"
printf '######\n#@$$ #\n#   .#\n#   .#\n######\n' >"$T/u.txt"
"$S" solve "$T/u.txt" 2>&1 | grep -q unsolvable && ok "unsolvable level proven unsolvable"
"$S" solve levels/generated.txt -timeout 30s >"$T/gen.out" && ok "all 10 generated levels solved ($(grep -c 'optimal' "$T/gen.out") answers)"
"$S" bench levels/generated.txt --ablate -nodes 30000 | tail -5

step "3  generator: deterministic, solvable by construction, rated"
"$S" gen -w 10 -h 9 -boxes 4 -seed 7 -attempts 80 -min-pushes 12 -o "$T/g1.txt" 2>"$T/g1.err"; cat "$T/g1.err"
"$S" gen -w 10 -h 9 -boxes 4 -seed 7 -attempts 80 -min-pushes 12 -o "$T/g2.txt" 2>/dev/null
cmp "$T/g1.txt" "$T/g2.txt" && ok "same seed -> byte-identical level"
"$S" solve "$T/g1.txt" -q >"$T/g1.sol" && ok "generated level solves ($(tr -d '\n' <"$T/g1.sol" | wc -c) moves)"
"$S" pack -count 4 -w 9 -h 8 -boxes 3 -seed 3 -o "$T/pk.txt" 2>/dev/null && [ "$(grep -c '^;' "$T/pk.txt")" = 4 ] && ok "pack of 4 levels written"
expect_fail "$S" gen -w 3 -h 3
expect_fail "$S" gen -boxes 99

step "5  verifier + replay (stretch)"
"$S" solve levels/starter.txt -n 1 -q >"$T/m.txt"
"$S" check levels/starter.txt -f "$T/m.txt" -n 1 && ok "solver output verified by independent replayer"
expect_fail "$S" check levels/starter.txt "LLLL" -n 1
expect_fail "$S" check levels/starter.txt "dlUrrrdLullddrUluRuulDrddrruLdlU" -n 1   # one push short: legal but unsolved
"$S" replay levels/starter.txt -n 2 -delay 0 >"$T/r.txt" && tail -6 "$T/r.txt" && ok "ASCII replay"

step "4  HTML game export + browser test"
"$S" html levels/starter.txt levels/generated.txt -o "$T/game.html" -title "Shove demo"
if command -v node >/dev/null && node -e "require('playwright')" 2>/dev/null; then
  node tests/browser.test.js "$T/game.html" && ok "browser end-to-end suite"
else
  echo "   (skipped: node+playwright not available)"
fi

step "6  benchmark table"
"$S" bench levels/starter.txt -md >"$T/b.md"; head -4 "$T/b.md"; [ "$(wc -l <"$T/b.md")" = 6 ] && ok "markdown bench table"

step "go test"
go test ./... 2>&1 | tail -3
echo; echo "DEMO COMPLETE: $pass explicit checks passed"
